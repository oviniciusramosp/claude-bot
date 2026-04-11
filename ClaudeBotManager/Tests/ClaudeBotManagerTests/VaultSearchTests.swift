import XCTest
@testable import ClaudeBotManager

/// Tests for VaultSearch — the frontmatter-aware filter helper used by the
/// macOS app's list views. Mirrors the shape of `scripts/vault_query.py`'s
/// filter expressions and their semantics.
final class VaultSearchTests: XCTestCase {

    // MARK: - Fixtures

    private func makeRoutine(
        id: String = "alpha",
        title: String = "Alpha",
        description: String = "An alpha routine",
        model: String = "sonnet",
        agentId: String? = nil,
        enabled: Bool = true,
        tags: [String] = ["routine"],
        type: String = "routine"
    ) -> Routine {
        Routine(
            id: id,
            title: title,
            description: description,
            schedule: Routine.Schedule(times: ["09:00"], days: ["*"], until: nil, interval: nil, monthdays: []),
            model: model,
            agentId: agentId,
            enabled: enabled,
            promptBody: "",
            created: "2026-04-11",
            updated: "2026-04-11",
            tags: tags,
            routineType: type
        )
    }

    private func makeSkill(
        id: String = "publish-notion",
        title: String = "Publish to Notion",
        description: String = "Publish content to Notion",
        trigger: String = "when posting to Notion",
        tags: [String] = ["skill", "publishing", "notion"]
    ) -> Skill {
        Skill(
            id: id,
            title: title,
            description: description,
            trigger: trigger,
            tags: tags,
            created: "2026-04-11",
            updated: "2026-04-11",
            body: ""
        )
    }

    private func makeAgent(
        id: String = "crypto-bro",
        name: String = "Crypto Bro",
        description: String = "Crypto specialist",
        model: String = "sonnet",
        tags: [String] = ["agent", "crypto"]
    ) -> Agent {
        Agent(
            id: id,
            name: name,
            icon: "🪙",
            description: description,
            personality: "friendly and accessible",
            model: model,
            tags: tags,
            isDefault: false,
            source: nil,
            sourceId: nil,
            created: "2026-04-11",
            updated: "2026-04-11"
        )
    }

    // MARK: - Empty / no-op behaviour

    func test_emptySearch_matchesEverything() {
        let s = VaultSearch("")
        XCTAssertTrue(s.isEmpty)
        XCTAssertTrue(s.matches(makeRoutine()))
        XCTAssertTrue(s.matches(makeSkill()))
        XCTAssertTrue(s.matches(makeAgent()))
    }

    func test_whitespaceOnly_isEmpty() {
        XCTAssertTrue(VaultSearch("   ").isEmpty)
    }

    // MARK: - Free text matching

    func test_freeText_matchesTitle() {
        let s = VaultSearch("alpha")
        XCTAssertTrue(s.matches(makeRoutine(title: "Alpha")))
        // Override every text-bearing field so the only "alpha" signal would
        // come from the title (which we set to Bravo) — i.e. no match.
        XCTAssertFalse(s.matches(makeRoutine(
            id: "bravo",
            title: "Bravo",
            description: "Bravo routine",
            tags: ["routine"]
        )))
    }

    func test_freeText_matchesDescription() {
        let s = VaultSearch("technical analysis")
        XCTAssertTrue(s.matches(makeRoutine(description: "Daily technical analysis pipeline")))
        XCTAssertFalse(s.matches(makeRoutine(description: "News pipeline")))
    }

    func test_freeText_matchesTag() {
        let s = VaultSearch("crypto")
        XCTAssertTrue(s.matches(makeRoutine(tags: ["routine", "crypto"])))
        XCTAssertFalse(s.matches(makeRoutine(tags: ["routine", "palmeiras"])))
    }

    func test_freeText_caseInsensitive() {
        let s = VaultSearch("CRYPTO")
        XCTAssertTrue(s.matches(makeRoutine(tags: ["routine", "crypto"])))
    }

    // MARK: - key=value

    func test_modelFilter() {
        let s = VaultSearch("model:opus")
        XCTAssertTrue(s.matches(makeRoutine(model: "opus")))
        XCTAssertFalse(s.matches(makeRoutine(model: "sonnet")))
    }

    func test_typeFilter_distinguishesRoutineFromPipeline() {
        let s = VaultSearch("type:pipeline")
        XCTAssertTrue(s.matches(makeRoutine(type: "pipeline")))
        XCTAssertFalse(s.matches(makeRoutine(type: "routine")))
    }

    func test_enabledFilter() {
        let s = VaultSearch("enabled:false")
        XCTAssertTrue(s.matches(makeRoutine(enabled: false)))
        XCTAssertFalse(s.matches(makeRoutine(enabled: true)))
    }

    func test_agentFilter() {
        let s = VaultSearch("agent:crypto-bro")
        XCTAssertTrue(s.matches(makeRoutine(agentId: "crypto-bro")))
        XCTAssertFalse(s.matches(makeRoutine(agentId: "parmeirense")))
        XCTAssertFalse(s.matches(makeRoutine(agentId: nil)))
    }

    func test_tagShorthand() {
        let s = VaultSearch("tag:publishing")
        XCTAssertTrue(s.matches(makeSkill(tags: ["skill", "publishing", "notion"])))
        XCTAssertFalse(s.matches(makeSkill(tags: ["skill", "data"])))
    }

    // MARK: - Combined terms (AND)

    func test_combinedTerms_areAnded() {
        let s = VaultSearch("model:opus tag:crypto")
        let opusCrypto = makeRoutine(model: "opus", tags: ["routine", "crypto"])
        let opusPalmeiras = makeRoutine(model: "opus", tags: ["routine", "palmeiras"])
        let sonnetCrypto = makeRoutine(model: "sonnet", tags: ["routine", "crypto"])
        XCTAssertTrue(s.matches(opusCrypto))
        XCTAssertFalse(s.matches(opusPalmeiras))
        XCTAssertFalse(s.matches(sonnetCrypto))
    }

    func test_freeText_plus_filter() {
        let s = VaultSearch("crypto model:opus")
        XCTAssertTrue(s.matches(makeRoutine(description: "crypto routine", model: "opus")))
        XCTAssertFalse(s.matches(makeRoutine(description: "palmeiras routine", model: "opus")))
        XCTAssertFalse(s.matches(makeRoutine(description: "crypto routine", model: "sonnet")))
    }

    // MARK: - Skill / Agent specific keys

    func test_skillTriggerFilter() {
        let s = VaultSearch("trigger:notion")
        XCTAssertTrue(s.matches(makeSkill(trigger: "when posting to Notion")))
        XCTAssertFalse(s.matches(makeSkill(trigger: "when posting to X")))
    }

    func test_agentModelFilter() {
        let s = VaultSearch("model:opus")
        XCTAssertTrue(s.matches(makeAgent(model: "opus")))
        XCTAssertFalse(s.matches(makeAgent(model: "sonnet")))
    }

    // MARK: - Quoted values

    func test_quotedValuePreservesSpaces() {
        let s = VaultSearch("\"alpha routine\"")
        XCTAssertTrue(s.matches(makeRoutine(description: "An alpha routine here")))
        XCTAssertFalse(s.matches(makeRoutine(description: "An alpha and a routine")))
    }
}
