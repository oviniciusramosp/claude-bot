import Foundation

struct ModelOption: Hashable, Sendable {
    let id: String          // frontmatter value, e.g. "sonnet", "glm-4.7", "gpt-5"
    let label: String       // UI label, e.g. "Sonnet 4.6", "GLM 4.7", "GPT-5"
    let provider: String    // "anthropic", "zai", or "openai"
    let description: String // short description for UI hints
}

enum ModelCatalog {
    static let all: [ModelOption] = [
        ModelOption(id: "fable",        label: "Fable 5",     provider: "anthropic", description: "Anthropic's most capable model — 1M context"),
        ModelOption(id: "opus",         label: "Opus 5",      provider: "anthropic", description: "Most capable for ambitious work — 1M context"),
        ModelOption(id: "sonnet-5",     label: "Sonnet 5",    provider: "anthropic", description: "Best combination of speed and intelligence — 1M context"),
        ModelOption(id: "haiku",        label: "Haiku 4.5",   provider: "anthropic", description: "Fastest and most compact"),
        ModelOption(id: "gpt-5",        label: "GPT-5",       provider: "openai",    description: "OpenAI general — ChatGPT Plus/Pro"),
        ModelOption(id: "gpt-5-codex",  label: "GPT-5 Codex", provider: "openai",    description: "OpenAI coding-tuned — requires API key (not ChatGPT OAuth)"),
        ModelOption(id: "gpt-5.5",      label: "GPT-5.5",     provider: "openai",    description: "OpenAI latest — ChatGPT Plus/Pro default"),
    ]

    static func label(for id: String) -> String {
        all.first(where: { $0.id == id })?.label ?? id.capitalized
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
        all.map { ($0.id, $0.label) }
    }
}
