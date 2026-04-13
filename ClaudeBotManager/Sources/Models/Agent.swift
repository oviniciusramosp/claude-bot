import Foundation

struct Agent: Identifiable, Hashable, Sendable {
    var id: String          // directory name (kebab-case)
    var name: String
    var icon: String        // emoji
    var description: String
    var personality: String  // kept in agent-<id>.md frontmatter for bot routing
    var model: String       // sonnet | opus | haiku
    var color: String = "grey"  // graph-view color group: see AGENT_COLOR_PALETTE
    var tags: [String]
    var isDefault: Bool
    var source: String?     // e.g. "openclaw"
    var sourceId: String?
    var created: String
    var updated: String

    // Structured CLAUDE.md sections
    var personalityAndTone: String = ""
    var instructions: String = ""
    var specializations: String = ""
    var otherInstructions: String = ""

    // Telegram topic (1:1 — one chat/thread per agent)
    var chatId: String = ""
    var threadId: String = ""

    static var modelOptions: [String] { ModelCatalog.all.map(\.id) }
    static let colorOptions = ["grey", "red", "orange", "yellow", "green", "teal", "blue", "purple"]

    // MARK: - CLAUDE.md parsing

    /// Parse CLAUDE.md content into structured sections
    static func parseCLAUDEmd(_ content: String) -> (personality: String, instructions: String, specializations: String, other: String) {
        var personality = ""
        var instructions = ""
        var specializations = ""
        var other = ""

        var currentSection: String? = nil
        var currentLines: [String] = []

        func flush() {
            let text = currentLines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            switch currentSection {
            case "personality":     personality = text
            case "instructions":    instructions = text
            case "specializations": specializations = text
            case let s? where !s.isEmpty: other += (other.isEmpty ? "" : "\n\n## \(s.capitalized)\n\n") + text
            default: break
            }
            currentLines = []
        }

        for line in content.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            // Skip the top-level heading (# Name 🤖)
            if trimmed.hasPrefix("# ") && !trimmed.hasPrefix("## ") { continue }

            if trimmed.hasPrefix("## ") {
                flush()
                let heading = String(trimmed.dropFirst(3)).trimmingCharacters(in: .whitespaces).lowercased()
                if heading.contains("personality") || heading.contains("tone") {
                    currentSection = "personality"
                } else if heading.contains("instruction") {
                    currentSection = "instructions"
                } else if heading.contains("specializ") {
                    currentSection = "specializations"
                } else {
                    currentSection = heading
                }
                continue
            }

            currentLines.append(line)
        }
        flush()

        return (personality, instructions, specializations, other)
    }

    /// Serialize structured sections back to CLAUDE.md format
    func toCLAUDEmd() -> String {
        var parts: [String] = ["# \(name) \(icon)"]

        if !personalityAndTone.isEmpty {
            parts.append("\n## Personality\n\n\(personalityAndTone)")
        }
        if !instructions.isEmpty {
            parts.append("\n## Instructions\n\n\(instructions)")
        }
        if !specializations.isEmpty {
            parts.append("\n## Specializations\n\n\(specializations)")
        }
        if !otherInstructions.isEmpty {
            parts.append("\n## Other\n\n\(otherInstructions)")
        }

        return parts.joined(separator: "\n") + "\n"
    }
}
