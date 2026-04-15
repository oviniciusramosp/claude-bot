import Foundation

actor BotProcessService {
    private let plistLabel = "com.claudebot.bot"
    private let webPlistLabel = "com.claudebot.web"
    private let claudePath: String

    init(claudePath: String = "/opt/homebrew/bin/claude") {
        self.claudePath = claudePath
    }

    enum BotStatus: Sendable {
        case running(pid: Int, uptime: TimeInterval)
        case stopped
        case unknown
    }

    func status() -> BotStatus {
        let result = shell("launchctl", "list", plistLabel)
        guard result.exitCode == 0 else { return .stopped }

        // Parse PID from launchctl output: "{ ... "PID" = 1234; ... }"
        let pid: Int
        if let match = result.output.range(of: #""PID" = (\d+);"#, options: .regularExpression) {
            let pidStr = result.output[match].components(separatedBy: CharacterSet.decimalDigits.inverted)
                .joined()
            pid = Int(pidStr) ?? -1
        } else {
            return .stopped // Listed but no PID = not running
        }

        guard pid > 0 else { return .stopped }

        // Get process start time via ps
        let ps = shell("ps", "-o", "etime=", "-p", "\(pid)")
        let uptimeSecs = parseElapsed(ps.output.trimmingCharacters(in: .whitespacesAndNewlines))
        return .running(pid: pid, uptime: uptimeSecs)
    }

    func start() {
        _ = shell("launchctl", "load", plistPath(for: plistLabel))
        _ = shell("launchctl", "load", plistPath(for: webPlistLabel))
    }

    func stop() {
        _ = shell("launchctl", "unload", plistPath(for: plistLabel))
        _ = shell("launchctl", "unload", plistPath(for: webPlistLabel))
    }

    func restart() {
        stop()
        Thread.sleep(forTimeInterval: 1.0)
        start()
    }

    /// Run a routine prompt immediately (dry-run)
    func runRoutineNow(prompt: String, model: String, agentId: String?, workspace: String) async throws {
        var args = [claudePath, "--output-format", "json", "--model", model, "-p", prompt]
        let process = Process()
        process.executableURL = URL(fileURLWithPath: claudePath)
        process.arguments = ["--output-format", "json", "--model", model, "-p", prompt]
        process.currentDirectoryURL = URL(fileURLWithPath: workspace)
        try process.run()
        process.waitUntilExit()
        _ = args // suppress warning
    }

    // MARK: - Private

    private func plistPath(for label: String) -> String {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        return "\(home)/Library/LaunchAgents/\(label).plist"
    }

    private struct ShellResult {
        var output: String
        var exitCode: Int32
    }

    @discardableResult
    private func shell(_ cmd: String, _ args: String...) -> ShellResult {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/env")
        process.arguments = [cmd] + args
        process.standardOutput = pipe
        process.standardError = Pipe()
        do {
            try process.run()
            process.waitUntilExit()
        } catch { return ShellResult(output: "", exitCode: -1) }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        let output = String(data: data, encoding: .utf8) ?? ""
        return ShellResult(output: output, exitCode: process.terminationStatus)
    }

    // Parse ps etime format: [[dd-]hh:]mm:ss
    private func parseElapsed(_ s: String) -> TimeInterval {
        let parts = s.components(separatedBy: ":")
        switch parts.count {
        case 2:
            let m = Double(parts[0]) ?? 0
            let sec = Double(parts[1]) ?? 0
            return m * 60 + sec
        case 3:
            // Could be dd-hh or hh:mm:ss
            if parts[0].contains("-") {
                let dp = parts[0].components(separatedBy: "-")
                let d = Double(dp[0]) ?? 0
                let h = Double(dp[1]) ?? 0
                let m = Double(parts[1]) ?? 0
                let sec = Double(parts[2]) ?? 0
                return d * 86400 + h * 3600 + m * 60 + sec
            } else {
                let h = Double(parts[0]) ?? 0
                let m = Double(parts[1]) ?? 0
                let sec = Double(parts[2]) ?? 0
                return h * 3600 + m * 60 + sec
            }
        default:
            return 0
        }
    }
}
