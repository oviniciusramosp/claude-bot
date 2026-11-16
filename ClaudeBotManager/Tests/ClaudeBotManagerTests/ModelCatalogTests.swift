import XCTest
@testable import ClaudeBotManager

final class ModelCatalogTests: XCTestCase {
    override func setUp() {
        super.setUp()
        ModelCatalog.learnedIdsOverride = [:]
    }

    override func tearDown() {
        ModelCatalog.learnedIdsOverride = nil
        super.tearDown()
    }

    func testLabelFollowsTheModelTheBotSawRun() {
        ModelCatalog.learnedIdsOverride = ["opus": "claude-opus-6[1m]"]
        XCTAssertEqual(ModelCatalog.label(for: "opus"), "Opus 6")
    }

    func testAllModelsHaveUniqueIDs() {
        let ids = ModelCatalog.all.map { $0.id }
        XCTAssertEqual(ids.count, Set(ids).count, "Duplicate model IDs in catalog")
    }

    func testCatalogContainsExpectedModels() {
        let ids = Set(ModelCatalog.all.map { $0.id })
        XCTAssertEqual(ids, ["fable", "sonnet-5", "opus", "haiku",
                             "gpt"])
    }

    func testLabelForKnownID() {
        XCTAssertEqual(ModelCatalog.label(for: "fable"), "Fable 5.1")
        XCTAssertEqual(ModelCatalog.label(for: "sonnet-5"), "Sonnet 5.5")
        XCTAssertEqual(ModelCatalog.label(for: "opus"), "Opus 5.5")
        XCTAssertEqual(ModelCatalog.label(for: "haiku"), "Haiku 5.5")
    }

    func testLabelForUnknownIDFallsBack() {
        XCTAssertEqual(ModelCatalog.label(for: "mystery"), "Mystery")
    }

    func testProviderInference() {
        XCTAssertEqual(ModelCatalog.provider(for: "sonnet-5"), "anthropic")
        XCTAssertEqual(ModelCatalog.provider(for: "gpt"), "openai")
        XCTAssertEqual(ModelCatalog.provider(for: "gpt-5"), "openai")
        XCTAssertEqual(ModelCatalog.prettyName("claude-sonnet-5-5[1m]"), "Sonnet 5.5")
        XCTAssertEqual(ModelCatalog.prettyName("claude-opus-6"), "Opus 6")
        XCTAssertNil(ModelCatalog.prettyName("gpt-6.1-sol"))
        XCTAssertEqual(ModelCatalog.provider(for: "gpt-future-99"), "openai")
        XCTAssertEqual(ModelCatalog.provider(for: "unknown"), "anthropic")
    }
}
