import XCTest
@testable import ClaudeBotManager

final class FrontmatterParserTests: XCTestCase {

    // MARK: - Parsing

    func test_emptyContent_returnsEmpty() {
        let (fm, body) = FrontmatterParser.parse("")
        XCTAssertTrue(fm.isEmpty)
        XCTAssertEqual(body, "")
    }

    func test_noFrontmatter_returnsEmptyDict() {
        let (fm, body) = FrontmatterParser.parse("# just markdown\n\nbody text")
        XCTAssertTrue(fm.isEmpty)
        XCTAssertEqual(body, "# just markdown\n\nbody text")
    }

    func test_simpleScalars() {
        let text = """
        ---
        title: My Routine
        type: routine
        enabled: true
        model: sonnet
        ---
        body
        """
        let (fm, body) = FrontmatterParser.parse(text)
        XCTAssertEqual(fm["title"] as? String, "My Routine")
        XCTAssertEqual(fm["type"] as? String, "routine")
        XCTAssertEqual(fm["enabled"] as? Bool, true)
        XCTAssertEqual(fm["model"] as? String, "sonnet")
        XCTAssertEqual(body, "body")
    }

    func test_quotedString() {
        let text = """
        ---
        title: "Quoted Title"
        ---
        """
        let (fm, _) = FrontmatterParser.parse(text)
        XCTAssertEqual(fm["title"] as? String, "Quoted Title")
    }

    func test_flowList() {
        let text = """
        ---
        tags: [a, b, c]
        ---
        """
        let (fm, _) = FrontmatterParser.parse(text)
        let tags = fm["tags"] as? [String]
        XCTAssertEqual(tags, ["a", "b", "c"])
    }

    func test_emptyFlowList() {
        let text = """
        ---
        tags: []
        ---
        """
        let (fm, _) = FrontmatterParser.parse(text)
        let tags = fm["tags"] as? [String]
        XCTAssertEqual(tags, [])
    }

    func test_intParsing() {
        let text = """
        ---
        count: 42
        ---
        """
        let (fm, _) = FrontmatterParser.parse(text)
        XCTAssertEqual(fm["count"] as? Int, 42)
    }

    func test_boolFalse() {
        let text = """
        ---
        enabled: false
        ---
        """
        let (fm, _) = FrontmatterParser.parse(text)
        XCTAssertEqual(fm["enabled"] as? Bool, false)
    }

    func test_nestedScheduleBlock() {
        let text = """
        ---
        title: r
        type: routine
        schedule:
          times: ["08:00", "20:00"]
          days: [mon, tue]
        enabled: true
        ---
        body
        """
        let (fm, body) = FrontmatterParser.parse(text)
        let schedule = fm["schedule"] as? [String: Any]
        XCTAssertNotNil(schedule)
        let times = schedule?["times"] as? [String]
        XCTAssertEqual(times, ["08:00", "20:00"])
        let days = schedule?["days"] as? [String]
        XCTAssertEqual(days, ["mon", "tue"])
        XCTAssertEqual(fm["enabled"] as? Bool, true)
        XCTAssertEqual(body, "body")
    }

    // MARK: - Serialization

    func test_serialize_roundTrip() {
        let fm: [String: Any] = [
            "title": "My Routine",
            "type": "routine",
            "enabled": true,
            "tags": ["x", "y"],
        ]
        let serialized = FrontmatterParser.serialize(
            fm,
            orderedKeys: ["title", "type", "enabled", "tags"],
            body: "body content"
        )
        XCTAssertTrue(serialized.contains("title: My Routine"))
        XCTAssertTrue(serialized.contains("type: routine"))
        XCTAssertTrue(serialized.contains("enabled: true"))
        XCTAssertTrue(serialized.contains("tags: [x, y]"))
        XCTAssertTrue(serialized.contains("body content"))

        // Now reparse
        let (parsed, body) = FrontmatterParser.parse(serialized)
        XCTAssertEqual(parsed["title"] as? String, "My Routine")
        XCTAssertEqual(parsed["enabled"] as? Bool, true)
        XCTAssertEqual(body, "body content")
    }

    func test_serialize_quotesNonAscii() {
        let fm: [String: Any] = ["icon": "💸"]
        let out = FrontmatterParser.serialize(fm, orderedKeys: ["icon"], body: "")
        // Non-ASCII (emoji) must be quoted to remain valid YAML
        XCTAssertTrue(out.contains("\"💸\""), "Expected emoji to be quoted, got: \(out)")
    }

    func test_serialize_preservesKeyOrder() {
        let fm: [String: Any] = [
            "z_last": "z",
            "a_first": "a",
            "m_mid": "m",
        ]
        let out = FrontmatterParser.serialize(
            fm,
            orderedKeys: ["a_first", "m_mid", "z_last"],
            body: ""
        )
        let aIdx = out.range(of: "a_first")!.lowerBound
        let mIdx = out.range(of: "m_mid")!.lowerBound
        let zIdx = out.range(of: "z_last")!.lowerBound
        XCTAssertLessThan(aIdx, mIdx)
        XCTAssertLessThan(mIdx, zIdx)
    }
}
