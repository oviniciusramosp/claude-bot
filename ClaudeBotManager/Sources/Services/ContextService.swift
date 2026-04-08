import Foundation

actor ContextService {
    private let dataDir: String

    init(dataDir: String) {
        self.dataDir = dataDir
    }

    struct TopicContext: Sendable {
        var chatId: String
        var threadId: String?
        var sessionName: String
    }

    func loadContexts() -> [TopicContext] {
        let path = (dataDir as NSString).appendingPathComponent("contexts.json")
        guard let data = FileManager.default.contents(atPath: path),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let contexts = json["contexts"] as? [[String: Any]] else {
            return []
        }

        return contexts.compactMap { c in
            guard let chatId = c["chat_id"].map({ "\($0)" }) else { return nil }
            let threadId = c["thread_id"].flatMap { v -> String? in
                if v is NSNull { return nil }
                return "\(v)"
            }
            let sessionName = c["session_name"] as? String ?? ""
            return TopicContext(chatId: chatId, threadId: threadId, sessionName: sessionName)
        }
    }

    func addMapping(chatId: String, threadId: String?, agentId: String, sessions: SessionsFile) throws {
        // Find or create a session for this agent
        let path = (dataDir as NSString).appendingPathComponent("contexts.json")
        var contexts = loadContexts()

        // Check if mapping already exists
        let alreadyExists = contexts.contains { $0.chatId == chatId && $0.threadId == threadId }
        if alreadyExists { return }

        // Find an existing session for this agent
        let sessionName = sessions.sessions.values
            .first { $0.agentId == agentId }?.name ?? "agent-\(agentId)"

        contexts.append(TopicContext(chatId: chatId, threadId: threadId, sessionName: sessionName))
        try saveContexts(contexts, to: path)
    }

    func removeMapping(chatId: String, threadId: String?) throws {
        let path = (dataDir as NSString).appendingPathComponent("contexts.json")
        var contexts = loadContexts()
        contexts.removeAll { $0.chatId == chatId && $0.threadId == threadId }
        try saveContexts(contexts, to: path)
    }

    private func saveContexts(_ contexts: [TopicContext], to path: String) throws {
        let arr: [[String: Any]] = contexts.map { c in
            var dict: [String: Any] = ["chat_id": c.chatId, "session_name": c.sessionName]
            if let tid = c.threadId {
                dict["thread_id"] = Int(tid) ?? tid
            } else {
                dict["thread_id"] = NSNull()
            }
            return dict
        }
        let wrapper: [String: Any] = ["contexts": arr]
        let data = try JSONSerialization.data(withJSONObject: wrapper, options: [.prettyPrinted])
        try data.write(to: URL(fileURLWithPath: path))
    }
}
