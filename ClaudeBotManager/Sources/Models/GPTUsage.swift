import Foundation

/// Snapshot of OpenAI/Codex usage displayed on the Dashboard's GPT Usage card.
/// Unlike Claude and z.AI, there is no public quota API for ChatGPT Plus, so
/// this card is cost-tracking only (sourced from costs.json, provider "openai").
struct GPTUsage: Sendable, Equatable {
    /// True when the Codex CLI binary exists at the configured `CODEX_PATH`.
    var isConfigured: Bool

    /// Total cost for the current ISO week (provider "openai" slice).
    var weeklyCostUSD: Double

    /// Total cost for today (provider "openai" slice).
    var todayCostUSD: Double

    static var empty: GPTUsage {
        GPTUsage(isConfigured: false, weeklyCostUSD: 0, todayCostUSD: 0)
    }

    var hasCostData: Bool { weeklyCostUSD > 0 || todayCostUSD > 0 }

    /// Formatted weekly label for the big number on the card.
    var weeklyLabel: String {
        if hasCostData { return String(format: "$%.2f", weeklyCostUSD) }
        return "—"
    }
}
