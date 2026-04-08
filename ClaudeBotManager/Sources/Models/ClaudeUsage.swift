import Foundation

struct ClaudeUsage: Sendable {
    var sessionPercent: Double      // 0.0 – 1.0
    var weeklyPercent: Double       // 0.0 – 1.0  (derived from token counts when available)
    var sessionResetsAt: Date?
    var weeklyResetsAt: Date?
    var isAvailable: Bool           // true only when live % data from API is available

    // Plan info from Keychain (always available when credentials exist)
    var planName: String?
    var rateTier: String?
    var credentialsExpireAt: Date?

    // Token accounting from local project JSONL files
    var weeklyTokensUsed: Int64  = 0   // tokens consumed this week (Mon–now)
    var weeklyTokensRef:  Int64  = 0   // reference for 100% (max of past 4 weeks)

    static var unavailable: ClaudeUsage {
        ClaudeUsage(sessionPercent: 0, weeklyPercent: 0, sessionResetsAt: nil,
                    weeklyResetsAt: nil, isAvailable: false,
                    planName: nil, rateTier: nil, credentialsExpireAt: nil)
    }

    // Derived percent from scanned token counts
    var weeklyTokenPercent: Double {
        guard weeklyTokensRef > 0 else { return 0 }
        return min(1.0, Double(weeklyTokensUsed) / Double(weeklyTokensRef))
    }

    var hasTokenData: Bool { weeklyTokensUsed > 0 || weeklyTokensRef > 0 }

    var sessionLabel: String {
        isAvailable ? "\(Int(sessionPercent * 100))%" : "—"
    }

    var weeklyLabel: String {
        if isAvailable { return "\(Int(weeklyPercent * 100))%" }
        if hasTokenData { return formatTokens(weeklyTokensUsed) }
        return "—"
    }

    var hasPlanInfo: Bool { planName != nil }

    var credentialsAreValid: Bool {
        guard let exp = credentialsExpireAt else { return false }
        return exp > Date()
    }

    func formatTokens(_ n: Int64) -> String {
        if n >= 1_000_000_000 { return String(format: "%.1fB", Double(n) / 1e9) }
        if n >= 1_000_000     { return String(format: "%.1fM", Double(n) / 1e6) }
        if n >= 1_000         { return String(format: "%.0fK", Double(n) / 1e3) }
        return "\(n)"
    }
}
