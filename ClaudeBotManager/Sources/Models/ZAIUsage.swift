import Foundation

/// Snapshot of z.ai GLM usage displayed on the Dashboard's Z.AI Usage card.
/// Designed to be a drop-in visual parallel to `ClaudeUsage` — the Dashboard
/// renders both cards with the same layout.
struct ZAIUsage: Sendable, Equatable {
    /// True when the user has configured `ZAI_API_KEY`. When false the card
    /// shows a "Not Connected" call-to-action.
    var isConfigured: Bool

    /// True when the z.ai quota endpoint returned live data. When false and
    /// `isConfigured` is true, the card falls back to local cost tracking.
    var isAvailable: Bool

    // --- Tier 1: live quota from z.ai's /api/monitor/usage/quota/limit ---
    var sessionPercent: Double      // 0.0–1.0 — 5-hour window
    var weeklyPercent: Double       // 0.0–1.0 — weekly window (= session on old plans)
    var sessionResetsAt: Date?
    var weeklyResetsAt: Date?

    /// Plan tier string as reported by `data.level` — `"pro"`, `"lite"`, `"max"`,
    /// `"unknown"`. Already uppercased. `nil` when the API hasn't been queried.
    var planLevel: String?

    /// Raw token counts from the weekly window (may be 0 if z.ai omitted them).
    var weeklyTokensUsed: Int64
    var weeklyTokensLimit: Int64

    // --- Tier 2: local cost tracking (always available when isConfigured) ---
    var weeklyCostUSD: Double
    var todayCostUSD: Double

    static var empty: ZAIUsage {
        ZAIUsage(
            isConfigured: false, isAvailable: false,
            sessionPercent: 0, weeklyPercent: 0,
            sessionResetsAt: nil, weeklyResetsAt: nil,
            planLevel: nil,
            weeklyTokensUsed: 0, weeklyTokensLimit: 0,
            weeklyCostUSD: 0, todayCostUSD: 0
        )
    }

    var hasPlanInfo: Bool { planLevel != nil }

    /// Display name for the plan — "GLM Coding Plan · PRO" or "GLM Coding Plan".
    var planName: String {
        if let lvl = planLevel, !lvl.isEmpty, lvl.lowercased() != "unknown" {
            return "GLM Coding Plan · \(lvl.uppercased())"
        }
        return "GLM Coding Plan"
    }

    /// True when the local cost tracker has at least one GLM entry this week.
    var hasCostData: Bool { weeklyCostUSD > 0 || todayCostUSD > 0 }

    /// Formatted weekly label for the big number on the card.
    /// Priority: API weekly % > local cost $.
    var weeklyLabel: String {
        if isAvailable { return "\(Int(weeklyPercent * 100))%" }
        if hasCostData { return String(format: "$%.2f", weeklyCostUSD) }
        return "—"
    }
}
