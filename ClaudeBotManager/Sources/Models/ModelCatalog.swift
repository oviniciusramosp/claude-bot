import Foundation

struct ModelOption: Hashable, Sendable {
    let id: String          // frontmatter value, e.g. "sonnet", "glm-4.7", "gpt-5"
    let label: String       // UI label, e.g. "Sonnet 4.6", "GLM 4.7", "GPT-5"
    let provider: String    // "anthropic", "zai", or "openai"
    let description: String // short description for UI hints
}

enum ModelCatalog {
    static let all: [ModelOption] = [
        ModelOption(id: "fable",        label: "Fable 5.1",   provider: "anthropic", description: "Anthropic's most capable model — 1M context"),
        ModelOption(id: "opus",         label: "Opus 5.5",    provider: "anthropic", description: "Most capable for ambitious work — 1M context"),
        ModelOption(id: "sonnet-5",     label: "Sonnet 5.5",  provider: "anthropic", description: "Best combination of speed and intelligence — 1M context"),
        ModelOption(id: "haiku",        label: "Haiku 5.5",   provider: "anthropic", description: "Fastest and most compact"),
        ModelOption(id: "gpt",          label: "GPT",         provider: "openai",    description: "ChatGPT Plus/Pro — whatever model the account uses by default"),
    ]

    /// Label for a model key. Prefers the real id the bot last saw that key
    /// run as (~/.claude-bot/model-ids.json, written by the bot), so names
    /// follow model upgrades without editing this file; the static labels
    /// above are only the fallback.
    static func label(for id: String) -> String {
        if let learned = learnedIds()[id], let pretty = prettyName(learned) {
            return pretty
        }
        return all.first(where: { $0.id == id })?.label ?? id.capitalized
    }

    /// "claude-sonnet-5-5" → "Sonnet 5.5"; nil when the id has another shape.
    static func prettyName(_ modelId: String) -> String? {
        let base = modelId.split(separator: "[").first.map(String.init) ?? modelId
        let parts = base.split(separator: "-").map(String.init)
        guard parts.count >= 3, parts[0] == "claude", parts[2].allSatisfy(\.isNumber) else { return nil }
        var version = parts[2]
        if parts.count >= 4, parts[3].allSatisfy(\.isNumber) { version += "." + parts[3] }
        return parts[1].capitalized + " " + version
    }

    /// Tests set this to bypass the real file in the user's home.
    nonisolated(unsafe) static var learnedIdsOverride: [String: String]? = nil

    private static func learnedIds() -> [String: String] {
        if let override = learnedIdsOverride { return override }
        let url = FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".claude-bot/model-ids.json")
        guard let data = try? Data(contentsOf: url),
              let dict = try? JSONSerialization.jsonObject(with: data) as? [String: String] else { return [:] }
        return dict
    }

    static func description(for id: String) -> String {
        all.first(where: { $0.id == id })?.description ?? ""
    }

    static func provider(for id: String) -> String {
        if let match = all.first(where: { $0.id == id }) { return match.provider }
        if id.hasPrefix("glm") { return "zai" }
        if id.hasPrefix("gpt-") { return "openai" }
        return "anthropic"
    }

    /// Tuples for SwiftUI Picker that uses `options:` with (id, label).
    static var pickerOptions: [(String, String)] {
        all.map { ($0.id, label(for: $0.id)) }
    }
}
