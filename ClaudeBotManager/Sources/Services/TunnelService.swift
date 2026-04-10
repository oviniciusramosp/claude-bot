import Foundation

/// Manages the Tailscale Funnel that exposes the webhook server on port 27183
/// to the public internet. Wraps the `scripts/tailscale-funnel.sh` helper.
///
/// The funnel config persists across `tailscaled` restarts automatically —
/// once enabled it stays up until explicitly disabled.
@MainActor
final class TunnelService: ObservableObject {
    enum State: Equatable {
        case unknown
        case notInstalled
        case notLoggedIn
        case installed(baseURL: String?)     // logged in, funnel off
        case active(baseURL: String)          // funnel on

        var isActive: Bool {
            if case .active = self { return true }
            return false
        }

        var baseURL: String? {
            switch self {
            case .installed(let url): return url
            case .active(let url): return url
            default: return nil
            }
        }
    }

    @Published private(set) var state: State = .unknown
    @Published private(set) var lastError: String?
    @Published private(set) var isBusy: Bool = false
    @Published private(set) var isInstalling: Bool = false
    /// Set when Tailscale requires the user to approve Funnel feature on their
    /// tailnet admin panel. The view should show an "Open authorization" button.
    @Published private(set) var funnelAuthURL: String?

    private let webhookPort: Int
    private let scriptPath: String
    private let installScriptPath: String

    init(webhookPort: Int = 27183, scriptPath: String, installScriptPath: String) {
        self.webhookPort = webhookPort
        self.scriptPath = scriptPath
        self.installScriptPath = installScriptPath
    }

    /// Refresh `state` by invoking `detect` + `status` subcommands.
    func detect() async {
        isBusy = true
        defer { isBusy = false }
        // Detect installation + login state + base URL
        let detectRaw = await runScript(args: ["detect"])
        let detectJson = Self.parseJSON(detectRaw)
        if let ok = detectJson["ok"] as? Bool, !ok {
            let err = (detectJson["error"] as? String) ?? "unknown error"
            if err.contains("not found") || err.contains("Tailscale binary") {
                state = .notInstalled
            } else {
                state = .unknown
                lastError = err
            }
            return
        }
        guard let installed = detectJson["installed"] as? Bool, installed else {
            state = .notInstalled
            return
        }
        if (detectJson["logged_in"] as? Bool) != true {
            state = .notLoggedIn
            return
        }
        let baseURL = detectJson["base_url"] as? String

        // Now check funnel status
        let statusRaw = await runScript(args: ["status"])
        let statusJson = Self.parseJSON(statusRaw)
        if let ok = statusJson["ok"] as? Bool, ok,
           let inner = statusJson["status"] as? [String: Any],
           let entries = inner["AllowFunnel"] as? [String: Any],
           !entries.isEmpty,
           let url = baseURL
        {
            state = .active(baseURL: url)
            // Successful state — clear any stale error messages from previous
            // failed attempts (e.g. "funnel_tailnet_not_enabled" before the
            // user approved).
            lastError = nil
            funnelAuthURL = nil
        } else {
            state = .installed(baseURL: baseURL)
        }
    }

    private static func parseJSON(_ raw: String) -> [String: Any] {
        guard let data = raw.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return ["ok": false, "error": raw.isEmpty ? "empty response" : raw]
        }
        return json
    }

    /// Enable the Funnel — exposes `127.0.0.1:webhookPort` publicly.
    func enable() async {
        isBusy = true
        defer { isBusy = false }
        funnelAuthURL = nil
        let raw = await runScript(args: ["enable", String(webhookPort)])
        let json = Self.parseJSON(raw)
        if let ok = json["ok"] as? Bool, !ok {
            let errorCode = (json["error"] as? String) ?? "enable failed"
            if errorCode == "funnel_tailnet_not_enabled" {
                funnelAuthURL = json["auth_url"] as? String
                lastError = "Your tailnet needs to approve Funnel once. Click the button below to authorize, then toggle Funnel again."
            } else {
                lastError = errorCode
            }
        } else {
            lastError = nil
            funnelAuthURL = nil
        }
        await detect()
    }

    /// Clear the pending funnel auth URL (called after user opens it in browser).
    func clearFunnelAuthURL() {
        funnelAuthURL = nil
    }

    /// Download and install the latest Tailscale .pkg from pkgs.tailscale.com.
    /// Triggers a GUI password dialog once (inherent to all macOS .pkg installs).
    /// Does NOT bypass the Network Extension approval that macOS shows on first
    /// Tailscale.app launch — that is a system-managed dialog.
    func install() async {
        isInstalling = true
        defer { isInstalling = false }
        let raw = await runInstallScript()
        let json = Self.parseJSON(raw)
        if let ok = json["ok"] as? Bool, !ok {
            lastError = (json["error"] as? String) ?? "install failed"
        } else {
            lastError = nil
        }
        // After install, Tailscale.app may need to be launched at least once to
        // register its services; do a detect to refresh state.
        await detect()
    }

    private func runInstallScript() async -> String {
        let path = installScriptPath
        return await Task.detached(priority: .userInitiated) { () -> String in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/bash")
            process.arguments = [path]
            let stdoutPipe = Pipe()
            let stderrPipe = Pipe()
            process.standardOutput = stdoutPipe
            process.standardError = stderrPipe
            do {
                try process.run()
            } catch {
                return #"{"ok":false,"error":"failed to run install script: \#(error.localizedDescription)"}"#
            }
            process.waitUntilExit()
            let stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
            let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let stdoutStr = String(data: stdoutData, encoding: .utf8) ?? ""
            let stderrStr = String(data: stderrData, encoding: .utf8) ?? ""
            if !stdoutStr.isEmpty { return stdoutStr }
            return stderrStr
        }.value
    }

    /// Disable the Funnel — traffic to the public URL will stop.
    func disable() async {
        isBusy = true
        defer { isBusy = false }
        let raw = await runScript(args: ["disable"])
        let json = Self.parseJSON(raw)
        if let ok = json["ok"] as? Bool, !ok {
            lastError = (json["error"] as? String) ?? "disable failed"
        } else {
            lastError = nil
        }
        await detect()
    }

    /// Full webhook URL for a given reaction id.
    /// Returns the public Funnel URL when active, otherwise the local loopback URL.
    /// When a token is provided, appends it as `?token=...` so the URL is ready
    /// to paste directly into services like TradingView or Notion.
    func webhookURL(for reactionId: String, token: String? = nil) -> String {
        let base: String
        if case .active(let tunnelBase) = state {
            base = "\(tunnelBase)/webhook/\(reactionId)"
        } else {
            base = "http://127.0.0.1:\(webhookPort)/webhook/\(reactionId)"
        }
        if let token, !token.isEmpty {
            // Percent-encode the token just in case (shouldn't contain special chars,
            // but defensive against future formats).
            let encoded = token.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? token
            return "\(base)?token=\(encoded)"
        }
        return base
    }

    /// Whether the current URL is only reachable locally (loopback).
    var isLocalOnly: Bool {
        if case .active = state { return false }
        return true
    }

    // MARK: - Private

    /// Runs the helper script and returns raw stdout (stderr appended on failure).
    /// Returns a String (Sendable), parsed into JSON by callers via `parseJSON`.
    private func runScript(args: [String]) async -> String {
        let path = scriptPath
        return await Task.detached(priority: .userInitiated) { () -> String in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/bash")
            process.arguments = [path] + args
            let stdoutPipe = Pipe()
            let stderrPipe = Pipe()
            process.standardOutput = stdoutPipe
            process.standardError = stderrPipe
            do {
                try process.run()
            } catch {
                return #"{"ok":false,"error":"failed to run script: \#(error.localizedDescription)"}"#
            }
            process.waitUntilExit()
            let stdoutData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
            let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            let stdoutStr = String(data: stdoutData, encoding: .utf8) ?? ""
            let stderrStr = String(data: stderrData, encoding: .utf8) ?? ""
            if !stdoutStr.isEmpty { return stdoutStr }
            return stderrStr
        }.value
    }
}
