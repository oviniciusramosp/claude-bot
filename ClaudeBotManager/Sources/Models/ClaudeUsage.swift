import Foundation

struct ClaudeUsage: Sendable {
    var sessionPercent: Double      // 0.0 – 1.0
    var weeklyPercent: Double       // 0.0 – 1.0
    var sessionResetsAt: Date?
    var weeklyResetsAt: Date?
    var isAvailable: Bool           // false if no credentials / API unreachable

    // Plan info from Keychain (always available when credentials exist)
    var planName: String?           // e.g. "Claude Max", "Claude Pro"
    var rateTier: String?           // e.g. "20×", "1×"
    var credentialsExpireAt: Date?  // OAuth token expiry

    static var unavailable: ClaudeUsage {
        ClaudeUsage(sessionPercent: 0, weeklyPercent: 0, sessionResetsAt: nil,
                    weeklyResetsAt: nil, isAvailable: false,
                    planName: nil, rateTier: nil, credentialsExpireAt: nil)
    }

    var sessionLabel: String {
        isAvailable ? "\(Int(sessionPercent * 100))%" : "—"
    }

    var weeklyLabel: String {
        isAvailable ? "\(Int(weeklyPercent * 100))%" : "—"
    }

    var hasPlanInfo: Bool { planName != nil }

    var credentialsAreValid: Bool {
        guard let exp = credentialsExpireAt else { return false }
        return exp > Date()
    }
}
