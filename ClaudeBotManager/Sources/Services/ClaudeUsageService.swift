import Foundation

actor ClaudeUsageService {

    func fetchUsage() async -> ClaudeUsage {
        // Start with Keychain credentials/plan info
        var usage = readFromKeychain() ?? .unavailable

        // Try to get real utilization from the Anthropic usage API
        if let apiUsage = await fetchFromAPI(oauthToken: keychainOAuthToken()) {
            usage.sessionPercent  = apiUsage.sessionPercent
            usage.weeklyPercent   = apiUsage.weeklyPercent
            usage.sessionResetsAt = apiUsage.sessionResetsAt
            usage.weeklyResetsAt  = apiUsage.weeklyResetsAt
            usage.isAvailable     = true
        }

        // Fetch organization name
        if let orgName = await fetchOrganizationName(oauthToken: keychainOAuthToken()) {
            usage.organizationName = orgName
        }

        // Scan local project JSONL files for real token counts (shown as supplemental info)
        let (thisWeek, reference) = scanWeeklyTokens()
        usage.weeklyTokensUsed = thisWeek
        usage.weeklyTokensRef  = reference

        return usage
    }

    // MARK: - Live API (anthropic.com/api/oauth/usage)

    /// Fetches real session and weekly utilization from the Anthropic usage API.
    private func fetchFromAPI(oauthToken: String?) async -> ClaudeUsage? {
        guard let token = oauthToken, !token.isEmpty else { return nil }

        guard let url = URL(string: "https://api.anthropic.com/api/oauth/usage") else { return nil }

        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)",         forHTTPHeaderField: "Authorization")
        request.setValue("claude_cli_macos",        forHTTPHeaderField: "anthropic-client-platform")
        request.setValue("2023-06-01",              forHTTPHeaderField: "anthropic-version")
        request.setValue("oauth-2025-04-20",        forHTTPHeaderField: "anthropic-beta")
        request.setValue("application/json",        forHTTPHeaderField: "Accept")

        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return nil }

        let isoFmt = ISO8601DateFormatter()
        isoFmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        func parseDate(_ obj: [String: Any]?, key: String) -> Date? {
            guard let str = obj?[key] as? String else { return nil }
            return isoFmt.date(from: str)
        }

        let fiveHour  = json["five_hour"]  as? [String: Any]
        let sevenDay  = json["seven_day"]  as? [String: Any]

        let sessionPct = (fiveHour?["utilization"] as? Double ?? 0) / 100.0
        let weeklyPct  = (sevenDay?["utilization"]  as? Double ?? 0) / 100.0

        return ClaudeUsage(
            sessionPercent:  sessionPct,
            weeklyPercent:   weeklyPct,
            sessionResetsAt: parseDate(fiveHour, key: "resets_at"),
            weeklyResetsAt:  parseDate(sevenDay,  key: "resets_at"),
            isAvailable:     true,
            planName:        nil,
            rateTier:        nil,
            credentialsExpireAt: nil
        )
    }

    /// Extracts the raw OAuth access token from the Keychain credentials JSON.
    private func keychainOAuthToken() -> String? {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/security")
        process.arguments = ["find-generic-password", "-s", "Claude Code-credentials", "-w"]
        process.standardOutput = pipe
        process.standardError = Pipe()
        do { try process.run(); process.waitUntilExit() } catch { return nil }
        guard process.terminationStatus == 0 else { return nil }

        let raw = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let trimmed = String(data: raw, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines),
              let jsonData = trimmed.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
              let oauth = json["claudeAiOauth"] as? [String: Any],
              let token = oauth["accessToken"] as? String
        else { return nil }

        return token
    }

    // MARK: - Organization info

    private func fetchOrganizationName(oauthToken: String?) async -> String? {
        guard let token = oauthToken, !token.isEmpty else { return nil }
        guard let url = URL(string: "https://api.anthropic.com/api/oauth/claude_cli/roles") else { return nil }

        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 10)
        request.httpMethod = "GET"
        request.setValue("Bearer \(token)",         forHTTPHeaderField: "Authorization")
        request.setValue("claude_cli_macos",        forHTTPHeaderField: "anthropic-client-platform")
        request.setValue("2023-06-01",              forHTTPHeaderField: "anthropic-version")
        request.setValue("oauth-2025-04-20",        forHTTPHeaderField: "anthropic-beta")
        request.setValue("application/json",        forHTTPHeaderField: "Accept")

        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let orgName = json["organization_name"] as? String
        else { return nil }

        return orgName
    }

    // MARK: - Keychain (plan / credentials)

    private func readFromKeychain() -> ClaudeUsage? {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/security")
        process.arguments = ["find-generic-password", "-s", "Claude Code-credentials", "-w"]
        process.standardOutput = pipe
        process.standardError = Pipe()
        do { try process.run(); process.waitUntilExit() } catch { return nil }
        guard process.terminationStatus == 0 else { return nil }

        let raw = pipe.fileHandleForReading.readDataToEndOfFile()
        guard let trimmed = String(data: raw, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines),
              let jsonData = trimmed.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
              let oauth = json["claudeAiOauth"] as? [String: Any] else { return nil }

        let planName = planDisplayName(oauth["subscriptionType"] as? String)
        let rateTier = rateTierDisplay(oauth["rateLimitTier"] as? String)
        let expiresAt = (oauth["expiresAt"] as? Double).map { Date(timeIntervalSince1970: $0 / 1000.0) }

        return ClaudeUsage(
            sessionPercent: 0,
            weeklyPercent: 0,
            sessionResetsAt: nil,
            weeklyResetsAt: nil,
            isAvailable: false,
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
        if let range = raw.range(of: #"(\d+)x"#, options: .regularExpression) {
            return "\(raw[range].dropLast())×"
        }
        return nil
    }

    // MARK: - Token scanning from ~/.claude/projects/**/*.jsonl

    /// Returns (thisWeekTokens, referenceTokens) where reference = max of past 4 complete weeks.
    private func scanWeeklyTokens() -> (Int64, Int64) {
        let fm   = FileManager.default
        let home = fm.homeDirectoryForCurrentUser
        let projectsDir = home.appendingPathComponent(".claude/projects")

        // Gregorian calendar, week starts Monday
        var cal = Calendar(identifier: .gregorian)
        cal.firstWeekday = 2
        let now = Date()

        // Monday of current week
        let weekStart = cal.date(
            from: cal.dateComponents([.yearForWeekOfYear, .weekOfYear], from: now)
        ) ?? now

        // How far back to scan (5 weeks to cover current + 4 reference)
        let scanFrom = cal.date(byAdding: .day, value: -35, to: weekStart) ?? weekStart

        // Accumulate per-week token sums keyed by week-start Date
        var weeklyTotals: [Date: Int64] = [:]
        var seen = Set<String>()                  // deduplicate by requestId
        let isoFmt = ISO8601DateFormatter()
        isoFmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        guard let enumerator = fm.enumerator(
            at: projectsDir,
            includingPropertiesForKeys: [.contentModificationDateKey],
            options: .skipsHiddenFiles
        ) else { return (0, 0) }

        for case let url as URL in enumerator {
            guard url.pathExtension == "jsonl" else { continue }

            // Skip files not modified recently (quick pre-filter)
            if let modDate = try? url.resourceValues(forKeys: [.contentModificationDateKey])
                                       .contentModificationDate,
               modDate < scanFrom { continue }

            guard let text = try? String(contentsOf: url, encoding: .utf8) else { continue }

            for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
                guard let data = line.data(using: .utf8),
                      let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else { continue }

                // Assistant messages only
                guard let msg = obj["message"] as? [String: Any],
                      (msg["role"] as? String) == "assistant",
                      let usage = msg["usage"] as? [String: Any],
                      let outTok = usage["output_tokens"] as? Int,
                      outTok > 0 else { continue }

                // Deduplicate
                let reqId = obj["requestId"] as? String ?? ""
                if !reqId.isEmpty {
                    if seen.contains(reqId) { continue }
                    seen.insert(reqId)
                }

                // Parse timestamp
                guard let tsStr = obj["timestamp"] as? String,
                      let ts = isoFmt.date(from: tsStr) ?? parseTimestampFallback(tsStr),
                      ts >= scanFrom else { continue }

                // Sum all token types
                let total: Int64 =
                    Int64(usage["input_tokens"]                as? Int ?? 0) +
                    Int64(outTok) +
                    Int64(usage["cache_creation_input_tokens"] as? Int ?? 0) +
                    Int64(usage["cache_read_input_tokens"]     as? Int ?? 0)

                // Bucket by week start
                let wk = cal.date(
                    from: cal.dateComponents([.yearForWeekOfYear, .weekOfYear], from: ts)
                ) ?? ts
                weeklyTotals[wk, default: 0] += total
            }
        }

        let thisWeek   = weeklyTotals[weekStart] ?? 0
        let pastValues = weeklyTotals.filter { $0.key < weekStart }.values
        let reference  = max(pastValues.max() ?? thisWeek, 1)

        return (thisWeek, reference)
    }

    /// Fallback parser for timestamps without fractional seconds
    private func parseTimestampFallback(_ s: String) -> Date? {
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd'T'HH:mm:ssZ"
        fmt.locale = Locale(identifier: "en_US_POSIX")
        return fmt.date(from: s)
    }
}
