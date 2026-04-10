import XCTest
@testable import ClaudeBotManager

final class SessionServiceTests: XCTestCase {

    private var tmpDir: URL!

    override func setUp() async throws {
        tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("claude-bot-tests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: tmpDir)
    }

    func test_loadMissingFile_returnsEmpty() async throws {
        let service = SessionService(dataDir: tmpDir.path)
        let file = try await service.loadSessions()
        XCTAssertTrue(file.sessions.isEmpty)
        XCTAssertNil(file.activeSession)
        XCTAssertEqual(file.cumulativeTurns, 0)
    }

    func test_loadValidJSON_parsesCorrectly() async throws {
        let payload: [String: Any] = [
            "active_session": "alpha",
            "cumulative_turns": 12,
            "sessions": [
                "alpha": [
                    "name": "alpha",
                    "session_id": "sess-uuid",
                    "model": "opus",
                    "workspace": "/Users/test/vault",
                    "agent": NSNull(),
                    "created_at": 1_750_000_000.0,
                    "message_count": 5,
                    "total_turns": 9,
                ]
            ]
        ]
        let data = try JSONSerialization.data(withJSONObject: payload, options: .prettyPrinted)
        let path = tmpDir.appendingPathComponent("sessions.json")
        try data.write(to: path)

        let service = SessionService(dataDir: tmpDir.path)
        let file = try await service.loadSessions()
        XCTAssertEqual(file.sessions.count, 1)
        XCTAssertEqual(file.activeSession, "alpha")
        XCTAssertEqual(file.cumulativeTurns, 12)
        let alpha = file.sessions["alpha"]
        XCTAssertNotNil(alpha)
        XCTAssertEqual(alpha?.model, "opus")
        XCTAssertEqual(alpha?.sessionId, "sess-uuid")
        XCTAssertEqual(alpha?.messageCount, 5)
        XCTAssertEqual(alpha?.totalTurns, 9)
        XCTAssertTrue(alpha?.isActive ?? false)
    }

    func test_loadCorruptJSON_throws() async throws {
        // Current behavior: SessionService throws on invalid JSON. Documenting
        // the contract here so it's a deliberate decision rather than an
        // accident — if this changes, the test must be updated together.
        let path = tmpDir.appendingPathComponent("sessions.json")
        try "not valid json".write(to: path, atomically: true, encoding: .utf8)

        let service = SessionService(dataDir: tmpDir.path)
        do {
            _ = try await service.loadSessions()
            XCTFail("Expected loadSessions to throw on corrupt JSON")
        } catch {
            // expected
        }
    }

    func test_loadIgnoresUnknownFields() async throws {
        let payload: [String: Any] = [
            "active_session": "x",
            "cumulative_turns": 0,
            "sessions": [
                "x": [
                    "name": "x",
                    "model": "sonnet",
                    "workspace": "/tmp",
                    "created_at": 1_750_000_000.0,
                    "message_count": 0,
                    "total_turns": 0,
                    "future_field": "ignored",
                ]
            ]
        ]
        let data = try JSONSerialization.data(withJSONObject: payload)
        try data.write(to: tmpDir.appendingPathComponent("sessions.json"))
        let service = SessionService(dataDir: tmpDir.path)
        let file = try await service.loadSessions()
        // Should not crash; unknown fields silently dropped
        XCTAssertEqual(file.sessions.count, 1)
    }
}
