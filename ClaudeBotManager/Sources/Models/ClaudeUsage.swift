import Foundation

struct ClaudeUsage: Sendable {
    var sessionPercent: Double      // 0.0 – 1.0
    var weeklyPercent: Double       // 0.0 – 1.0
    var sessionResetsAt: Date?
    var weeklyResetsAt: Date?
    var isAvailable: Bool           // false if no credentials / API unreachable

    static var unavailable: ClaudeUsage {
        ClaudeUsage(sessionPercent: 0, weeklyPercent: 0, sessionResetsAt: nil, weeklyResetsAt: nil, isAvailable: false)
    }

    var sessionLabel: String {
        isAvailable ? "\(Int(sessionPercent * 100))%" : "—"
    }

    var weeklyLabel: String {
        isAvailable ? "\(Int(weeklyPercent * 100))%" : "—"
    }
}
