import Foundation

struct VaultEnvEntry: Identifiable {
    let id: String   // env var name (immutable key)
    var value: String
    var friendlyName: String?  // user-defined label stored as inline comment

    var friendlyLabel: String {
        if let name = friendlyName, !name.isEmpty {
            return name
        }
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
        "NOTION_API_KEY": "API Key",
        "TELEGRAM_GROUP_ID": "Group ID",
        "FIGMA_TOKEN": "Token",
        "GEMINI_API_KEY": "API Key",
        "OPENAI_API_KEY": "API Key",
        "X_AUTH_TOKEN": "Auth Token",
        "X_CT0": "CT0 Cookie",
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

// MARK: - Key Groups

struct VaultKeyGroup: Identifiable {
    let id: String
    let name: String
    let symbol: String
    let predefinedKeys: [(envKey: String, label: String)]
    let prefix: String           // used to match entries to groups
    let customLabel: String?     // button label for adding custom entries
    let customSuggestedSuffix: String?  // suggested suffix for new keys

    static let allGroups: [VaultKeyGroup] = [
        VaultKeyGroup(
            id: "notion",
            name: "Notion",
            symbol: "book.closed",
            predefinedKeys: [("NOTION_API_KEY", "API Key")],
            prefix: "NOTION_",
            customLabel: "Add Database",
            customSuggestedSuffix: "_DB_ID"
        ),
        VaultKeyGroup(
            id: "openai",
            name: "OpenAI",
            symbol: "brain",
            predefinedKeys: [("OPENAI_API_KEY", "API Key")],
            prefix: "OPENAI_",
            customLabel: nil,
            customSuggestedSuffix: nil
        ),
        VaultKeyGroup(
            id: "gemini",
            name: "Gemini",
            symbol: "sparkles",
            predefinedKeys: [("GEMINI_API_KEY", "API Key")],
            prefix: "GEMINI_",
            customLabel: "Add Key",
            customSuggestedSuffix: "_API_KEY"
        ),
        VaultKeyGroup(
            id: "x",
            name: "X (Twitter)",
            symbol: "at",
            predefinedKeys: [
                ("X_AUTH_TOKEN", "Auth Token"),
                ("X_CT0", "CT0 Cookie"),
            ],
            prefix: "X_",
            customLabel: "Add Custom",
            customSuggestedSuffix: nil
        ),
        VaultKeyGroup(
            id: "figma",
            name: "Figma",
            symbol: "paintbrush",
            predefinedKeys: [("FIGMA_TOKEN", "Token")],
            prefix: "FIGMA_",
            customLabel: nil,
            customSuggestedSuffix: nil
        ),
    ]

    // Extra prefixes that route to a group but aren't the group's primary prefix
    private static let extraPrefixes: [String: String] = [
        "TWITTER_": "x",
    ]

    /// Find the group for a given env key. Returns nil if it belongs to "Other".
    static func group(for envKey: String) -> VaultKeyGroup? {
        let upper = envKey.uppercased()
        // Check extra prefixes first
        for (prefix, groupId) in extraPrefixes {
            if upper.hasPrefix(prefix) {
                return allGroups.first { $0.id == groupId }
            }
        }
        // Check primary prefixes
        return allGroups.first { upper.hasPrefix($0.prefix) }
    }
}
