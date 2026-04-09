import Foundation

struct VaultEnvEntry: Identifiable {
    let id: String   // env var name (immutable key)
    var value: String

    var friendlyLabel: String {
        if let known = Self.knownLabels[id] {
            return known
        }
        return Self.autoLabel(for: id)
    }

    var isSensitive: Bool {
        let upper = id.uppercased()
        return ["API_KEY", "TOKEN", "SECRET", "PASSWORD", "PRIVATE_KEY"]
            .contains(where: { upper.contains($0) })
    }

    // Telegram routing config (group IDs, thread IDs) belongs in Agent settings, not here
    var isAgentRouting: Bool {
        id.uppercased().hasPrefix("TELEGRAM_")
    }

    // MARK: - Known labels

    private static let knownLabels: [String: String] = [
        "NOTION_API_KEY": "Notion API Key",
        "NOTION_POSTS_DB_ID": "Notion Posts Database",
        "NOTION_PALMEIRAS_DB_ID": "Notion Palmeiras Database",
        "TELEGRAM_GROUP_ID": "Telegram Group ID",
        "TELEGRAM_CRYPTO_THREAD": "Telegram Crypto Thread",
        "TELEGRAM_PALMEIRAS_THREAD": "Telegram Palmeiras Thread",
        "FIGMA_TOKEN": "Figma Token",
        "GEMINI_API_KEY": "Gemini API Key",
        "OPENAI_API_KEY": "OpenAI API Key",
    ]

    // MARK: - Auto-label for unknown keys

    private static let suffixMap: [(suffix: String, label: String)] = [
        ("_API_KEY", "API Key"),
        ("_PRIVATE_KEY", "Private Key"),
        ("_SECRET_KEY", "Secret Key"),
        ("_SECRET", "Secret"),
        ("_TOKEN", "Token"),
        ("_PASSWORD", "Password"),
        ("_DB_ID", "Database"),
        ("_THREAD", "Thread"),
        ("_GROUP_ID", "Group ID"),
    ]

    private static func autoLabel(for key: String) -> String {
        let upper = key.uppercased()

        for (suffix, label) in suffixMap {
            if upper.hasSuffix(suffix) {
                let prefix = String(key.dropLast(suffix.count))
                let words = prefix.split(separator: "_").map { titleCase(String($0)) }
                if words.isEmpty { return label }
                return words.joined(separator: " ") + " " + label
            }
        }

        // Fallback: title-case all parts
        return key.split(separator: "_")
            .map { titleCase(String($0)) }
            .joined(separator: " ")
    }

    private static func titleCase(_ s: String) -> String {
        guard !s.isEmpty else { return s }
        return s.prefix(1).uppercased() + s.dropFirst().lowercased()
    }
}
