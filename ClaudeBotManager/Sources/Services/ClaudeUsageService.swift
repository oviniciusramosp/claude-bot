import Foundation

actor ClaudeUsageService {
    private let claudePath: String
    private let credentialsPath: String

    init(claudePath: String = "/opt/homebrew/bin/claude") {
        self.claudePath = claudePath
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        self.credentialsPath = "\(home)/.claude/.credentials.json"
    }

    func fetchUsage() async -> ClaudeUsage {
        // Try OAuth API first
        if let token = readOAuthToken(), let usage = await fetchFromAPI(token: token) {
            return usage
        }
        // Fallback to claude /usage CLI
        return await fetchFromCLI()
    }

    // MARK: - OAuth API

    private func readOAuthToken() -> String? {
        guard let data = FileManager.default.contents(atPath: credentialsPath),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        // The credentials file stores the access token
        return json["access_token"] as? String ?? json["token"] as? String
    }

    private func fetchFromAPI(token: String) async -> ClaudeUsage? {
        guard let url = URL(string: "https://api.anthropic.com/api/oauth/usage") else { return nil }
        var request = URLRequest(url: url)
        request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        request.timeoutInterval = 10

        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rateLimits = json["rate_limits"] as? [String: Any] else {
            return nil
        }

        let fiveHour = rateLimits["five_hour"] as? [String: Any] ?? [:]
        let sevenDay = rateLimits["seven_day"] as? [String: Any] ?? [:]

        let sessionPct = (fiveHour["used_percentage"] as? Double ?? 0) / 100.0
        let weeklyPct = (sevenDay["used_percentage"] as? Double ?? 0) / 100.0

        let sessionReset = (fiveHour["resets_at"] as? Double).map { Date(timeIntervalSince1970: $0) }
        let weeklyReset = (sevenDay["resets_at"] as? Double).map { Date(timeIntervalSince1970: $0) }

        return ClaudeUsage(
            sessionPercent: min(sessionPct, 1.0),
            weeklyPercent: min(weeklyPct, 1.0),
            sessionResetsAt: sessionReset,
            weeklyResetsAt: weeklyReset,
            isAvailable: true
        )
    }

    // MARK: - CLI Fallback

    private func fetchFromCLI() async -> ClaudeUsage {
        return await withCheckedContinuation { continuation in
            let process = Process()
            let pipe = Pipe()
            process.executableURL = URL(fileURLWithPath: claudePath)
            process.arguments = ["/usage"]
            process.standardOutput = pipe
            process.standardError = Pipe()

            do {
                try process.run()
                // Timeout after 8 seconds
                DispatchQueue.global().asyncAfter(deadline: .now() + 8) {
                    if process.isRunning { process.terminate() }
                }
                process.waitUntilExit()
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(data: data, encoding: .utf8) ?? ""
                continuation.resume(returning: parseCLIOutput(output))
            } catch {
                continuation.resume(returning: .unavailable)
            }
        }
    }

    private func parseCLIOutput(_ output: String) -> ClaudeUsage {
        // Parse lines like:
        // "Current session: 42%"
        // "Current week: 15%"
        var sessionPct: Double = 0
        var weeklyPct: Double = 0

        for line in output.components(separatedBy: "\n") {
            let lower = line.lowercased()
            if lower.contains("session") || lower.contains("5-hour") || lower.contains("5 hour") {
                sessionPct = extractPercent(from: line)
            } else if lower.contains("week") {
                weeklyPct = extractPercent(from: line)
            }
        }

        let isAvailable = sessionPct > 0 || weeklyPct > 0
        return ClaudeUsage(
            sessionPercent: min(sessionPct / 100.0, 1.0),
            weeklyPercent: min(weeklyPct / 100.0, 1.0),
            sessionResetsAt: nil,
            weeklyResetsAt: nil,
            isAvailable: isAvailable
        )
    }

    private func extractPercent(from line: String) -> Double {
        // Find digits followed by %
        let pattern = #"(\d+(?:\.\d+)?)%"#
        if let range = line.range(of: pattern, options: .regularExpression) {
            let match = String(line[range]).replacingOccurrences(of: "%", with: "")
            return Double(match) ?? 0
        }
        return 0
    }
}
