import XCTest
@testable import ClaudeBotManager

final class ModelCatalogTests: XCTestCase {
    func testAllModelsHaveUniqueIDs() {
        let ids = ModelCatalog.all.map { $0.id }
        XCTAssertEqual(ids.count, Set(ids).count, "Duplicate model IDs in catalog")
    }

    func testCatalogContainsExpectedModels() {
        let ids = Set(ModelCatalog.all.map { $0.id })
        XCTAssertEqual(ids, ["fable", "sonnet-5", "opus", "haiku",
                             "gpt-5", "gpt-5-codex", "gpt-5.5"])
    }

    func testLabelForKnownID() {
        XCTAssertEqual(ModelCatalog.label(for: "fable"), "Fable 5.1")
        XCTAssertEqual(ModelCatalog.label(for: "sonnet-5"), "Sonnet 5.5")
        XCTAssertEqual(ModelCatalog.label(for: "opus"), "Opus 5")
        XCTAssertEqual(ModelCatalog.label(for: "haiku"), "Haiku 5.5")
    }

    func testLabelForUnknownIDFallsBack() {
        XCTAssertEqual(ModelCatalog.label(for: "mystery"), "Mystery")
    }

    func testProviderInference() {
        XCTAssertEqual(ModelCatalog.provider(for: "sonnet-5"), "anthropic")
        XCTAssertEqual(ModelCatalog.provider(for: "gpt-5"), "openai")
        XCTAssertEqual(ModelCatalog.provider(for: "gpt-future-99"), "openai")
        XCTAssertEqual(ModelCatalog.provider(for: "unknown"), "anthropic")
    }
}
