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
            schedule: Routine.Schedule(times: ["08:00", "20:00"], days: ["mon", "wed"], until: nil, interval: nil, monthdays: []),
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
            schedule: Routine.Schedule(times: ["09:00"], days: ["*"], until: nil, interval: nil, monthdays: []),
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
            schedule: Routine.Schedule(times: ["00:00"], days: ["*"], until: nil, interval: nil, monthdays: []),
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

    func test_pipelineSave_generatesStepsSection() async throws {
        // Pipeline parent file must own parent->step graph edges via a
        // `## Steps` section appended after the ```pipeline block.
        // Step files must NOT contain wikilinks.
        // See vault/CLAUDE.md "Pipeline graph: parent owns the relationship".
        var stepA = PipelineStepDef(model: "haiku")
        stepA.stepId = "collect"
        stepA.name = "Collect"
        stepA.prompt = "Fetch data from the API."

        var stepB = PipelineStepDef(model: "opus")
        stepB.stepId = "analyze"
        stepB.name = "Analyze"
        stepB.dependsOn = ["collect"]
        stepB.prompt = "Analyze the collected data."
        stepB.outputType = "telegram"

        var routine = Routine(
            id: "test-pipe",
            title: "Test Pipeline",
            description: "A test pipeline",
            schedule: Routine.Schedule(times: ["08:00"], days: ["*"], until: nil, interval: nil, monthdays: []),
            model: "sonnet",
            agentId: nil,
            enabled: true,
            promptBody: "",
            created: "2026-04-11",
            updated: "2026-04-11",
            tags: ["pipeline", "test"],
            routineType: "pipeline",
            stepCount: 2,
            notify: "final",
            minimalContext: false
        )
        routine.pipelineStepDefs = [stepA, stepB]

        try await service.saveRoutine(routine)

        // Parent file: must contain `## Steps` section with execution-order links
        let parentURL = tmpVault.appendingPathComponent("Routines/test-pipe.md")
        let parentContent = try String(contentsOf: parentURL, encoding: .utf8)
        XCTAssertTrue(parentContent.contains("## Steps"),
                      "parent pipeline file must include `## Steps` section")
        XCTAssertTrue(parentContent.contains("[[test-pipe/steps/collect|collect]]"),
                      "parent must link to first step with path-aliased wikilink")
        XCTAssertTrue(parentContent.contains("[[test-pipe/steps/analyze|analyze]]"),
                      "parent must link to second step with path-aliased wikilink")
        // Order matters: collect comes before analyze
        let collectIdx = parentContent.range(of: "collect|collect")!.lowerBound
        let analyzeIdx = parentContent.range(of: "analyze|analyze")!.lowerBound
        XCTAssertLessThan(collectIdx, analyzeIdx, "steps must be listed in execution order")

        // Step files: NO wikilinks, NO frontmatter, just the prompt
        let stepAURL = tmpVault.appendingPathComponent("Routines/test-pipe/steps/collect.md")
        let stepAContent = try String(contentsOf: stepAURL, encoding: .utf8)
        XCTAssertFalse(stepAContent.contains("[["),
                       "step files must contain zero wikilinks")
        XCTAssertFalse(stepAContent.contains("rotina:"),
                       "no legacy rotina: backlink")
        XCTAssertFalse(stepAContent.contains("routine:"),
                       "no legacy routine: backlink")
        XCTAssertFalse(stepAContent.hasPrefix("---"),
                       "step files must not have frontmatter")
        XCTAssertEqual(stepAContent.trimmingCharacters(in: .whitespacesAndNewlines),
                       "Fetch data from the API.")

        let stepBURL = tmpVault.appendingPathComponent("Routines/test-pipe/steps/analyze.md")
        let stepBContent = try String(contentsOf: stepBURL, encoding: .utf8)
        XCTAssertFalse(stepBContent.contains("[["),
                       "step files must contain zero wikilinks")
        XCTAssertEqual(stepBContent.trimmingCharacters(in: .whitespacesAndNewlines),
                       "Analyze the collected data.")
    }

    func test_pipelineRoundTrip_loadsLegacyStepWithBacklink() async throws {
        // Legacy step files (written by older app versions) end with
        // `rotina: [[name]]`. The loader must strip it cleanly.
        var step = PipelineStepDef(model: "haiku")
        step.stepId = "scout"
        step.name = "Scout"
        step.prompt = "First version body."
        step.outputType = "telegram"

        var routine = Routine(
            id: "legacy",
            title: "Legacy",
            description: "",
            schedule: Routine.Schedule(times: ["09:00"], days: ["*"], until: nil, interval: nil, monthdays: []),
            model: "sonnet",
            agentId: nil,
            enabled: true,
            promptBody: "",
            created: "2026-04-11",
            updated: "2026-04-11",
            tags: ["pipeline"],
            routineType: "pipeline",
            stepCount: 1,
            notify: "final"
        )
        routine.pipelineStepDefs = [step]
        try await service.saveRoutine(routine)

        // Manually overwrite the step file with the legacy backlink format
        let stepURL = tmpVault.appendingPathComponent("Routines/legacy/steps/scout.md")
        try "Legacy body content.\n\nrotina: [[legacy]]\n"
            .write(to: stepURL, atomically: true, encoding: .utf8)

        // Load and verify the prompt is clean
        let loaded = try await service.loadRoutines()
        XCTAssertEqual(loaded.count, 1)
        let loadedDefs = await service.loadPipelineStepDefs(
            routineId: "legacy", promptBody: loaded[0].promptBody)
        XCTAssertEqual(loadedDefs.count, 1)
        XCTAssertFalse(loadedDefs[0].prompt.contains("[["),
                       "loader must strip trailing wikilinks from legacy step files")
        XCTAssertFalse(loadedDefs[0].prompt.contains("rotina:"))
        XCTAssertEqual(loadedDefs[0].prompt.trimmingCharacters(in: .whitespacesAndNewlines),
                       "Legacy body content.")
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
