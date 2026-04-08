import Foundation

struct SessionData: Identifiable, Hashable, Sendable {
    var id: String { name }
    var name: String
    var sessionId: String?
    var model: String
    var workspace: String
    var agentId: String?
    var createdAt: Date
    var messageCount: Int
    var totalTurns: Int
    var isActive: Bool = false
}

struct SessionsFile: Sendable {
    var sessions: [String: SessionData]
    var activeSession: String?
    var cumulativeTurns: Int

    var active: SessionData? {
        guard let name = activeSession else { return nil }
        return sessions[name]
    }
}
