import Foundation

struct Agent: Identifiable, Hashable, Sendable {
    var id: String          // directory name (kebab-case)
    var name: String
    var icon: String        // emoji
    var description: String
    var personality: String
    var model: String       // sonnet | opus | haiku
    var tags: [String]
    var isDefault: Bool
    var source: String?     // e.g. "openclaw"
    var sourceId: String?
    var instructions: String // content of CLAUDE.md
    var created: String
    var updated: String

    static let modelOptions = ["sonnet", "opus", "haiku"]

    // Agent-topic mapping (from contexts.json cross-referenced with sessions.json)
    var topicMappings: [TopicMapping] = []

    struct TopicMapping: Identifiable, Hashable, Sendable {
        var id: String { "\(chatId)-\(threadId ?? "nil")" }
        var chatId: String
        var threadId: String?   // nil = private chat
        var sessionName: String
    }
}
