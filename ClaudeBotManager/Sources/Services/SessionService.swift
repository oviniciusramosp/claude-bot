import Foundation

actor SessionService {
    private let dataDir: String

    init(dataDir: String) {
        self.dataDir = dataDir
    }

    func loadSessions() throws -> SessionsFile {
        let path = (dataDir as NSString).appendingPathComponent("sessions.json")
        guard FileManager.default.fileExists(atPath: path),
              let data = FileManager.default.contents(atPath: path) else {
            return SessionsFile(sessions: [:], activeSession: nil, cumulativeTurns: 0)
        }

        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return SessionsFile(sessions: [:], activeSession: nil, cumulativeTurns: 0)
        }

        let activeSession = json["active_session"] as? String
        let cumulativeTurns = json["cumulative_turns"] as? Int ?? 0
        let sessionsDict = json["sessions"] as? [String: [String: Any]] ?? [:]

        var sessions: [String: SessionData] = [:]
        for (name, raw) in sessionsDict {
            let createdAt = Date(timeIntervalSince1970: raw["created_at"] as? Double ?? 0)
            let s = SessionData(
                name: name,
                sessionId: raw["session_id"] as? String,
                model: raw["model"] as? String ?? "sonnet",
                workspace: raw["workspace"] as? String ?? "",
                agentId: raw["agent"] as? String,
                createdAt: createdAt,
                messageCount: raw["message_count"] as? Int ?? 0,
                totalTurns: raw["total_turns"] as? Int ?? 0,
                isActive: name == activeSession
            )
            sessions[name] = s
        }

        return SessionsFile(sessions: sessions, activeSession: activeSession, cumulativeTurns: cumulativeTurns)
    }
}
