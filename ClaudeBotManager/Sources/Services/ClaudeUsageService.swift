import Foundation

actor ClaudeUsageService {

    func fetchUsage() async -> ClaudeUsage {
        // Read plan info from macOS Keychain where Claude Code stores OAuth credentials.
        // The oauth/usage API endpoint does not support OAuth tokens, so we show plan
        // metadata instead of usage percentages.
        return readFromKeychain() ?? .unavailable
    }

    // MARK: - Keychain

    private func readFromKeychain() -> ClaudeUsage? {
        let process = Process()
        let pipe = Pipe()
        let errPipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/security")
        process.arguments = ["find-generic-password", "-s", "Claude Code-credentials", "-w"]
        process.standardOutput = pipe
        process.standardError = errPipe

        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return nil
        }

        guard process.terminationStatus == 0 else { return nil }

        let raw = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let trimmed = String(data: raw, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines),
              let jsonData = trimmed.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
              let oauth = json["claudeAiOauth"] as? [String: Any] else {
            return nil
        }

        let planName = planDisplayName(oauth["subscriptionType"] as? String)
        let rateTier = rateTierDisplay(oauth["rateLimitTier"] as? String)
        let expiresAt = (oauth["expiresAt"] as? Double).map { Date(timeIntervalSince1970: $0 / 1000.0) }

        return ClaudeUsage(
            sessionPercent: 0,
            weeklyPercent: 0,
            sessionResetsAt: nil,
            weeklyResetsAt: nil,
            isAvailable: false,          // no live % data available
            planName: planName,
            rateTier: rateTier,
            credentialsExpireAt: expiresAt
        )
    }

    private func planDisplayName(_ raw: String?) -> String? {
        switch raw?.lowercased() {
        case "max":   return "Claude Max"
        case "pro":   return "Claude Pro"
        case "free":  return "Claude Free"
        case .none:   return nil
        default:      return raw?.capitalized
        }
    }

    private func rateTierDisplay(_ raw: String?) -> String? {
        guard let raw else { return nil }
        // e.g. "default_claude_max_20x" → "20×"
        if let range = raw.range(of: #"(\d+)x"#, options: .regularExpression) {
            let digits = raw[range].dropLast() // remove trailing 'x'
            return "\(digits)×"
        }
        return nil
    }
}
