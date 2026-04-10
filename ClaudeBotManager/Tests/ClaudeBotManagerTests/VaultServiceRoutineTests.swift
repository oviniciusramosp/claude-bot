import XCTest
@testable import ClaudeBotManager

/// Round-trip tests for VaultService.saveRoutine + loadRoutines.
/// These verify the Swift parser stays byte-compatible with Python's frontmatter format.
final class VaultServiceRoutineTests: XCTestCase {

    private var tmpVault: URL!
    private var service: VaultService!

    override func setUp() async throws {
        tmpVault = FileManager.default.temporaryDirectory
            .appendingPathComponent("claude-vault-tests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmpVault, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(
            at: tmpVault.appendingPathComponent("Routines"),
            withIntermediateDirectories: true
        )
        service = VaultService(vaultPath: tmpVault.path)
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: tmpVault)
    }

    func test_saveAndLoadRoutine_roundTrip() async throws {
        let routine = Routine(
            id: "test-routine",
            title: "Test Routine",
            description: "A test routine",
            schedule: Routine.Schedule(times: ["08:00", "20:00"], days: ["mon", "wed"], until: nil),
            model: "sonnet",
            agentId: nil,
            enabled: true,
            promptBody: "Do the thing.",
            created: "2026-04-10",
            updated: "2026-04-10",
            tags: ["routine", "test"],
            routineType: "routine",
            stepCount: 0,
            notify: "final",
            minimalContext: false
        )

        try await service.saveRoutine(routine)
        let loaded = try await service.loadRoutines()

        XCTAssertEqual(loaded.count, 1)
        let r = loaded[0]
        XCTAssertEqual(r.id, "test-routine")
        XCTAssertEqual(r.title, "Test Routine")
        XCTAssertEqual(r.description, "A test routine")
        XCTAssertEqual(r.schedule.times, ["08:00", "20:00"])
        XCTAssertEqual(r.schedule.days, ["mon", "wed"])
        XCTAssertEqual(r.model, "sonnet")
        XCTAssertTrue(r.enabled)
        XCTAssertEqual(r.routineType, "routine")
    }

    func test_minimalContextFlag_roundTrip() async throws {
        let routine = Routine(
            id: "minctx",
            title: "Minimal context",
            description: "",
            schedule: Routine.Schedule(times: ["09:00"], days: ["*"], until: nil),
            model: "haiku",
            agentId: nil,
            enabled: true,
            promptBody: "do",
            created: "2026-04-10",
            updated: "2026-04-10",
            tags: ["routine"],
            routineType: "routine",
            minimalContext: true
        )
        try await service.saveRoutine(routine)
        let loaded = try await service.loadRoutines()
        XCTAssertEqual(loaded.count, 1)
        XCTAssertTrue(loaded[0].minimalContext, "minimal context flag must round-trip")
    }

    func test_saveAndLoadDisabled() async throws {
        let routine = Routine(
            id: "off",
            title: "Off",
            description: "",
            schedule: Routine.Schedule(times: ["00:00"], days: ["*"], until: nil),
            model: "sonnet",
            agentId: nil,
            enabled: false,
            promptBody: "x",
            created: "2026-04-10",
            updated: "2026-04-10",
            tags: ["routine"]
        )
        try await service.saveRoutine(routine)
        let loaded = try await service.loadRoutines()
        XCTAssertEqual(loaded.count, 1)
        XCTAssertFalse(loaded[0].enabled)
    }

    func test_loadFromExternalRoutineFile() async throws {
        // Simulate a file written by the Python bot — must parse identically
        let yaml = """
        ---
        title: External
        description: From Python
        type: routine
        created: 2026-04-10
        updated: 2026-04-10
        tags: [routine]
        schedule:
          times: ["07:30"]
          days: ["*"]
        model: opus
        enabled: true
        ---
        Hello from Python.
        """
        let path = tmpVault.appendingPathComponent("Routines/external.md")
        try yaml.write(to: path, atomically: true, encoding: .utf8)

        let loaded = try await service.loadRoutines()
        XCTAssertEqual(loaded.count, 1)
        let r = loaded[0]
        XCTAssertEqual(r.title, "External")
        XCTAssertEqual(r.schedule.times, ["07:30"])
        XCTAssertEqual(r.model, "opus")
        XCTAssertTrue(r.enabled)
    }
}
