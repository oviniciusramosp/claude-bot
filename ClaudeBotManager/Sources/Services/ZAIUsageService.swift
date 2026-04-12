import Foundation
import os

/// Fetches z.ai Coding Plan quota and local cost data for the Dashboard card.
///
/// The z.ai endpoint is `GET api.z.ai/api/monitor/usage/quota/limit`. Auth is a
/// RAW API key in the Authorization header (NOT `Bearer <key>`), with a Bearer
/// fallback on 401 for compatibility. Schema is documented in the z.AI Coding
/// Plan quota research note — see the commit that introduced this file.
actor ZAIUsageService {
    fileprivate static let logger = Logger(subsystem: "com.claudebot.manager", category: "ZAIUsageService")
    private let costService: CostHistoryService

    init(dataDir: String) {
        self.costService = CostHistoryService(dataDir: dataDir)
    }

    /// Fetch z.ai usage given current config. Returns `.empty` when key is unset.
    /// Never throws — errors are logged and the card degrades to local cost data.
    func fetchUsage(apiKey: String, baseUrl: String) async -> ZAIUsage {
        let trimmedKey = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedKey.isEmpty else { return .empty }

        // --- Tier 2 first (local cost, always free) ---
        var weeklyCost: Double = 0
        var todayCost: Double = 0
        do {
            weeklyCost = try await costService.totalThisWeek(provider: "zai")
            todayCost  = try await costService.totalToday(provider: "zai")
        } catch {
            Self.logger.error("Local cost read failed: \(error.localizedDescription, privacy: .public)")
        }

        // --- Tier 1: z.ai quota endpoint ---
        let parsed = await fetchQuota(apiKey: trimmedKey, baseUrl: baseUrl)

        var usage = ZAIUsage.empty
        usage.isConfigured = true
        usage.weeklyCostUSD = weeklyCost
        usage.todayCostUSD = todayCost

        if let p = parsed {
            usage.isAvailable = true
            usage.planLevel = p.level
            usage.sessionPercent = p.sessionPercent
            usage.weeklyPercent = p.weeklyPercent
            usage.sessionResetsAt = p.sessionResetsAt
            usage.weeklyResetsAt = p.weeklyResetsAt
            usage.weeklyTokensUsed = p.weeklyTokensUsed
            usage.weeklyTokensLimit = p.weeklyTokensLimit
        }
        return usage
    }

    // MARK: - HTTP

    struct ParsedQuota: Equatable {
        let level: String?
        let sessionPercent: Double
        let weeklyPercent: Double
        let sessionResetsAt: Date?
        let weeklyResetsAt: Date?
        let weeklyTokensUsed: Int64
        let weeklyTokensLimit: Int64
    }

    /// Build the quota URL from the configured base URL. Strips whatever path
    /// the user set (e.g. `/api/anthropic`) and replaces with
    /// `/api/monitor/usage/quota/limit`.
    private func quotaURL(from baseUrl: String) -> URL? {
        guard let configured = URL(string: baseUrl),
              let scheme = configured.scheme,
              let host = configured.host else { return nil }
        var components = URLComponents()
        components.scheme = scheme
        components.host = host
        if let port = configured.port { components.port = port }
        components.path = "/api/monitor/usage/quota/limit"
        return components.url
    }

    private func makeRequest(url: URL, apiKey: String, bearer: Bool) -> URLRequest {
        var request = URLRequest(url: url)
        request.httpMethod = "GET"
        request.setValue(bearer ? "Bearer \(apiKey)" : apiKey, forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("en-US,en", forHTTPHeaderField: "Accept-Language")
        request.timeoutInterval = 10
        return request
    }

    private func fetchQuota(apiKey: String, baseUrl: String) async -> ParsedQuota? {
        guard let url = quotaURL(from: baseUrl) else {
            Self.logger.error("Invalid zaiBaseUrl, cannot build quota URL")
            return nil
        }

        // Try raw token first (the confirmed working mode), Bearer fallback on 401.
        for useBearer in [false, true] {
            let request = makeRequest(url: url, apiKey: apiKey, bearer: useBearer)
            do {
                let (data, response) = try await URLSession.shared.data(for: request)
                guard let http = response as? HTTPURLResponse else {
                    Self.logger.debug("z.ai quota: non-HTTP response")
                    return nil
                }
                if http.statusCode == 401 && !useBearer {
                    Self.logger.debug("z.ai quota: 401 on raw token, retrying with Bearer")
                    continue
                }
                guard http.statusCode == 200 else {
                    Self.logger.debug("z.ai quota HTTP \(http.statusCode)")
                    return nil
                }
                // Log raw response once per fetch so we can diagnose field-shape drift.
                // Capped at 2 KB — the payload is small (< 1 KB in practice).
                if let raw = String(data: data.prefix(2048), encoding: .utf8) {
                    Self.logger.info("z.ai quota raw response: \(raw, privacy: .public)")
                }
                return Self.parseQuotaResponse(data)
            } catch {
                Self.logger.debug("z.ai quota request failed: \(error.localizedDescription, privacy: .public)")
                return nil
            }
        }
        return nil
    }

    /// Parse the `{code, msg, success, data: {limits, level}}` envelope.
    /// Exposed as `internal static` so unit tests can exercise the parser
    /// without hitting the network.
    static func parseQuotaResponse(_ data: Data) -> ParsedQuota? {
        guard let raw = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            logger.debug("z.ai quota: JSON parse failed")
            return nil
        }
        let code = (raw["code"] as? NSNumber)?.intValue ?? -1
        let success = raw["success"] as? Bool ?? false
        guard code == 200, success else {
            logger.debug("z.ai quota: envelope not success (code=\(code), success=\(success))")
            return nil
        }
        guard let dataObj = raw["data"] as? [String: Any] else { return nil }

        let level = dataObj["level"] as? String

        guard let limitsArr = dataObj["limits"] as? [[String: Any]] else {
            return ParsedQuota(
                level: level,
                sessionPercent: 0, weeklyPercent: 0,
                sessionResetsAt: nil, weeklyResetsAt: nil,
                weeklyTokensUsed: 0, weeklyTokensLimit: 0
            )
        }

        // Keep TOKENS_LIMIT entries only (drop TIME_LIMIT = MCP/web-search monthly).
        var tokensEntries: [TokensLimit] = []
        for item in limitsArr {
            guard (item["type"] as? String) == "TOKENS_LIMIT" else { continue }
            tokensEntries.append(TokensLimit.from(dict: item))
        }

        // Sort by window duration (shortest first). GLM Coding Plan uses `unit`
        // + `number` to describe each window:
        //   unit=3 → hours, unit=6 → weeks (observed from real responses)
        // The shortest-duration entry is the "session" (5-hour) window, the
        // longest is the "weekly" window. When `unit` is absent we fall back
        // to `nextResetTime` ascending, then to the original array order.
        tokensEntries.sort { a, b in
            let da = a.windowSeconds ?? .greatestFiniteMagnitude
            let db = b.windowSeconds ?? .greatestFiniteMagnitude
            if da != db { return da < db }
            switch (a.resetsAt, b.resetsAt) {
            case (nil, nil): return false
            case (nil, _):   return false
            case (_, nil):   return true
            case (let x?, let y?): return x < y
            }
        }

        let session: TokensLimit
        let weekly: TokensLimit
        if tokensEntries.count >= 2 {
            session = tokensEntries[0]              // shortest window → session
            weekly  = tokensEntries.last!           // longest window → weekly
        } else if let only = tokensEntries.first {
            session = only                           // old plan: same window for both
            weekly  = only
        } else {
            return ParsedQuota(
                level: level,
                sessionPercent: 0, weeklyPercent: 0,
                sessionResetsAt: nil, weeklyResetsAt: nil,
                weeklyTokensUsed: 0, weeklyTokensLimit: 0
            )
        }

        // Fallback reset times for responses that omit `nextResetTime`.
        // Session: `now + windowSeconds` (or 5h), weekly: `now + windowSeconds`
        // (or next Monday 00:00 local). The window duration from `unit`+`number`
        // is preferred so the fallback tracks the plan's real window size.
        let now = Date()
        let sessionFallback = session.windowSeconds.map { now.addingTimeInterval($0) }
            ?? now.addingTimeInterval(5 * 3600)
        let weeklyFallback = weekly.windowSeconds.map { now.addingTimeInterval($0) }
            ?? nextMondayMidnight(after: now)
        let sessionReset = session.resetsAt ?? sessionFallback
        let weeklyReset = weekly.resetsAt ?? weeklyFallback

        return ParsedQuota(
            level: level,
            sessionPercent: Double(session.percent) / 100.0,
            weeklyPercent: Double(weekly.percent) / 100.0,
            sessionResetsAt: sessionReset,
            weeklyResetsAt: weeklyReset,
            weeklyTokensUsed: weekly.currentValue,
            weeklyTokensLimit: weekly.limit
        )
    }

    /// Next Monday at 00:00 in the local calendar — used as a fallback weekly
    /// reset time when z.ai omits `nextResetTime` on minimal responses.
    private static func nextMondayMidnight(after date: Date) -> Date {
        var cal = Calendar(identifier: .iso8601)
        cal.firstWeekday = 2  // Monday
        cal.timeZone = TimeZone.current
        let comps = cal.dateComponents([.yearForWeekOfYear, .weekOfYear], from: date)
        guard let thisMonday = cal.date(from: comps),
              let nextMonday = cal.date(byAdding: .day, value: 7, to: thisMonday) else {
            return date.addingTimeInterval(7 * 24 * 3600)
        }
        return nextMonday
    }
}

// MARK: - Decoded limit row

private struct TokensLimit {
    let percent: Int
    let currentValue: Int64    // tokens used (may be 0 when omitted by z.ai)
    let limit: Int64           // token cap (the `usage` field — misleading name)
    let resetsAt: Date?
    /// Observed window unit code from z.ai. Known values from real payloads:
    ///   3 → hours, 6 → weeks. Used with `number` to compute total window length.
    let unit: Int?
    /// Multiplier paired with `unit` (e.g. `unit=3, number=5` → 5 hours).
    let number: Int?

    /// Total window duration in seconds, derived from (`unit`, `number`) when
    /// both are present. Returns `nil` when z.ai omits the unit indicator.
    var windowSeconds: TimeInterval? {
        guard let u = unit, let n = number, n > 0 else { return nil }
        let perUnit: TimeInterval
        switch u {
        case 1: perUnit = 1              // seconds
        case 2: perUnit = 60             // minutes
        case 3: perUnit = 3600           // hours
        case 4: perUnit = 86_400         // days
        case 5: perUnit = 2_629_800      // months (ignored — TIME_LIMIT only)
        case 6: perUnit = 7 * 86_400     // weeks
        case 7: perUnit = 365.25 * 86_400 // years
        default: return nil
        }
        return perUnit * TimeInterval(n)
    }

    /// Keys z.ai has shipped across plan generations for the reset timestamp.
    /// The schema is undocumented so we probe them all before giving up.
    static let resetTimeKeys = [
        "nextResetTime", "next_reset_time",
        "nextReset", "next_reset",
        "resetTime", "reset_time",
        "resetsAt", "resets_at",
        "resetAt", "reset_at",
    ]
    static let percentKeys = ["percentage", "percent", "percentValue"]
    static let currentKeys = ["currentValue", "current", "used", "consumed"]
    /// z.ai returns the LIMIT under the misleading key `usage`. `limit`/`total`
    /// are defensive fallbacks for possible future renames.
    static let limitKeys = ["usage", "limit", "quotaLimit", "totalQuota", "total"]

    static func from(dict: [String: Any]) -> TokensLimit {
        let percent = intValue(dict, keys: percentKeys) ?? 0
        let current = int64Value(dict, keys: currentKeys) ?? 0
        let limit = int64Value(dict, keys: limitKeys) ?? 0
        let resetsAt = dateValue(dict, keys: resetTimeKeys)
        let unit = intValue(dict, keys: ["unit"])
        let number = intValue(dict, keys: ["number"])
        return TokensLimit(
            percent: Int(percent),
            currentValue: current,
            limit: limit,
            resetsAt: resetsAt,
            unit: unit,
            number: number
        )
    }

    private static func intValue(_ dict: [String: Any], keys: [String]) -> Int? {
        for k in keys {
            guard let v = dict[k] else { continue }
            if let n = v as? NSNumber { return n.intValue }
            if let i = v as? Int { return i }
            if let d = v as? Double { return Int(d) }
            if let s = v as? String, let parsed = Int(s) { return parsed }
        }
        return nil
    }

    private static func int64Value(_ dict: [String: Any], keys: [String]) -> Int64? {
        for k in keys {
            guard let v = dict[k] else { continue }
            if let n = v as? NSNumber { return n.int64Value }
            if let i = v as? Int { return Int64(i) }
            if let d = v as? Double { return Int64(d) }
            if let s = v as? String, let parsed = Int64(s) { return parsed }
        }
        return nil
    }

    /// Accepts unix epoch (seconds or milliseconds — auto-detected by magnitude)
    /// either as a number or a numeric string. Also accepts ISO-8601 strings.
    private static func dateValue(_ dict: [String: Any], keys: [String]) -> Date? {
        for k in keys {
            guard let v = dict[k] else { continue }
            // Numeric epoch
            if let n = v as? NSNumber {
                return epochToDate(n.doubleValue)
            }
            if let i = v as? Int {
                return epochToDate(Double(i))
            }
            if let d = v as? Double {
                return epochToDate(d)
            }
            // String — try numeric epoch first, ISO-8601 second
            if let s = v as? String {
                if let num = Double(s) { return epochToDate(num) }
                let iso = ISO8601DateFormatter()
                iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
                if let d = iso.date(from: s) { return d }
                let iso2 = ISO8601DateFormatter()
                if let d = iso2.date(from: s) { return d }
            }
        }
        return nil
    }

    /// Heuristic: values above 1e12 are milliseconds, else seconds.
    private static func epochToDate(_ raw: Double) -> Date {
        if raw <= 0 { return Date() }
        let secs = raw > 1e12 ? raw / 1000.0 : raw
        return Date(timeIntervalSince1970: secs)
    }
}
