import XCTest
@testable import ClaudeBotManager

final class ModelCatalogTests: XCTestCase {
    func testAllModelsHaveUniqueIDs() {
        let ids = ModelCatalog.all.map { $0.id }
        XCTAssertEqual(ids.count, Set(ids).count, "Duplicate model IDs in catalog")
    }

    func testCatalogContainsExpectedModels() {
        let ids = Set(ModelCatalog.all.map { $0.id })
        XCTAssertEqual(ids, ["fable", "sonnet-5", "sonnet", "opus", "haiku",
                             "glm-5.1", "glm-4.7", "glm-4.5-air",
                             "gpt-5", "gpt-5-codex", "gpt-5.5"])
    }

    func testLabelForKnownID() {
        XCTAssertEqual(ModelCatalog.label(for: "fable"), "Fable 5")
        XCTAssertEqual(ModelCatalog.label(for: "sonnet-5"), "Sonnet 5")
        XCTAssertEqual(ModelCatalog.label(for: "sonnet"), "Sonnet 4.6")
        XCTAssertEqual(ModelCatalog.label(for: "opus"), "Opus 4.8")
        XCTAssertEqual(ModelCatalog.label(for: "glm-5.1"), "GLM 5.1")
    }

    func testLabelForUnknownIDFallsBack() {
        XCTAssertEqual(ModelCatalog.label(for: "mystery"), "Mystery")
    }

    func testProviderInference() {
        XCTAssertEqual(ModelCatalog.provider(for: "sonnet"), "anthropic")
        XCTAssertEqual(ModelCatalog.provider(for: "glm-4.7"), "zai")
        XCTAssertEqual(ModelCatalog.provider(for: "glm-future-99"), "zai")
        XCTAssertEqual(ModelCatalog.provider(for: "unknown"), "anthropic")
    }
}
