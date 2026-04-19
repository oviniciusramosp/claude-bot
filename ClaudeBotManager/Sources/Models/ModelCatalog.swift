import Foundation

struct ModelOption: Hashable, Sendable {
    let id: String          // frontmatter value, e.g. "sonnet", "glm-4.7"
    let label: String       // UI label, e.g. "Sonnet 4.6", "GLM 4.7"
    let provider: String    // "anthropic" or "zai"
    let description: String // short description for UI hints
}

enum ModelCatalog {
    static let all: [ModelOption] = [
        ModelOption(id: "sonnet",       label: "Sonnet 4.6",  provider: "anthropic", description: "Balanced performance and speed"),
        ModelOption(id: "opus",         label: "Opus 4.7",    provider: "anthropic", description: "Most capable for ambitious work"),
        ModelOption(id: "haiku",        label: "Haiku 4.5",   provider: "anthropic", description: "Fastest and most compact"),
        ModelOption(id: "glm-5.1",      label: "GLM 5.1",     provider: "zai",       description: "z.AI flagship — 200K context"),
        ModelOption(id: "glm-4.7",      label: "GLM 4.7",     provider: "zai",       description: "z.AI balanced — 131K context"),
        ModelOption(id: "glm-4.5-air",  label: "GLM 4.5 Air", provider: "zai",       description: "z.AI fast and lightweight"),
    ]

    static func label(for id: String) -> String {
        all.first(where: { $0.id == id })?.label ?? id.capitalized
    }

    static func description(for id: String) -> String {
        all.first(where: { $0.id == id })?.description ?? ""
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
