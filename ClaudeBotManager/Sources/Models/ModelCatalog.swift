import Foundation

struct ModelOption: Hashable, Sendable {
    let id: String       // frontmatter value, e.g. "sonnet", "glm-4.7"
    let label: String    // UI label, e.g. "Sonnet 4.6", "GLM 4.7"
    let provider: String // "anthropic" or "zai"
}

enum ModelCatalog {
    static let all: [ModelOption] = [
        ModelOption(id: "sonnet",       label: "Sonnet 4.6",  provider: "anthropic"),
        ModelOption(id: "opus",         label: "Opus 4.6",    provider: "anthropic"),
        ModelOption(id: "haiku",        label: "Haiku 4.5",   provider: "anthropic"),
        ModelOption(id: "glm-5.1",      label: "GLM 5.1",     provider: "zai"),
        ModelOption(id: "glm-4.7",      label: "GLM 4.7",     provider: "zai"),
        ModelOption(id: "glm-4.5-air",  label: "GLM 4.5 Air", provider: "zai"),
    ]

    static func label(for id: String) -> String {
        all.first(where: { $0.id == id })?.label ?? id.capitalized
    }

    static func provider(for id: String) -> String {
        if let match = all.first(where: { $0.id == id }) { return match.provider }
        return id.hasPrefix("glm") ? "zai" : "anthropic"
    }

    /// Tuples for SwiftUI Picker that uses `options:` with (id, label).
    static var pickerOptions: [(String, String)] {
        all.map { ($0.id, $0.label) }
    }
}
