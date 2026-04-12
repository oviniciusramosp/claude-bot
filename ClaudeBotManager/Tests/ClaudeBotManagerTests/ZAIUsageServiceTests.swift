import XCTest
@testable import ClaudeBotManager

/// Exercises the graceful-degradation and parsing paths of `ZAIUsageService`.
///
/// The real HTTP request hits `api.z.ai` and is out of scope for unit tests —
/// what matters is:
///   1. The service never crashes and never throws.
///   2. The envelope parser correctly maps the z.ai quota response into a
///      `ParsedQuota` matching the documented schema (see the commit that
///      introduced this file for the field-level spec).
final class ZAIUsageServiceTests: XCTestCase {

    private var tmpDir: URL!

    override func setUp() async throws {
        tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("zai-usage-tests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: tmpDir)
    }

    private func writeCosts(_ json: String) throws {
        let url = tmpDir.appendingPathComponent("costs.json")
        try json.data(using: .utf8)!.write(to: url)
    }

    /// ISO week key for "now" matching the bot's "%G-W%V" format.
    private var currentWeekKey: String {
        var cal = Calendar(identifier: .iso8601)
        cal.firstWeekday = 2
        cal.minimumDaysInFirstWeek = 4
        let c = cal.dateComponents([.yearForWeekOfYear, .weekOfYear], from: Date())
        return String(format: "%04d-W%02d", c.yearForWeekOfYear ?? 2026, c.weekOfYear ?? 1)
    }

    private var todayKey: String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone.current
        return f.string(from: Date())
    }

    // MARK: - fetchUsage (end-to-end, no network)

    func test_fetchUsage_returnsEmpty_whenKeyEmpty() async throws {
        let service = ZAIUsageService(dataDir: tmpDir.path)
        let usage = await service.fetchUsage(apiKey: "", baseUrl: "https://api.z.ai/api/anthropic")
        XCTAssertEqual(usage, .empty)
        XCTAssertFalse(usage.isConfigured)
        XCTAssertFalse(usage.isAvailable)
    }

    func test_fetchUsage_trimsWhitespaceKey_asEmpty() async throws {
        let service = ZAIUsageService(dataDir: tmpDir.path)
        let usage = await service.fetchUsage(apiKey: "   \n", baseUrl: "https://api.z.ai/api/anthropic")
        XCTAssertFalse(usage.isConfigured)
    }

    func test_fetchUsage_populatesLocalCostTier_evenWithoutHTTP() async throws {
        // Write a costs.json with a zai provider slice so Tier 2 fills in.
        let week = currentWeekKey
        let today = todayKey
        let json = """
        {
          "current_week": "\(week)",
          "weeks": {
            "\(week)": {
              "total": 1.23,
              "days": { "\(today)": 0.12 },
              "providers": {
                "anthropic": {"total": 0.80, "days": {"\(today)": 0.08}},
                "zai":       {"total": 0.43, "days": {"\(today)": 0.04}}
              }
            }
          }
        }
        """
        try writeCosts(json)

        // Point baseUrl at an invalid host so the HTTP request fails quickly.
        let service = ZAIUsageService(dataDir: tmpDir.path)
        let usage = await service.fetchUsage(
            apiKey: "fake-key",
            baseUrl: "https://invalid.example/api/anthropic"
        )

        XCTAssertTrue(usage.isConfigured, "Non-empty key must mark configured even when HTTP fails")
        XCTAssertFalse(usage.isAvailable, "Invalid host should never produce API data")
        XCTAssertEqual(usage.weeklyCostUSD, 0.43, accuracy: 0.0001)
        XCTAssertEqual(usage.todayCostUSD, 0.04, accuracy: 0.0001)

        // Weekly label falls back to the dollar amount in Tier 2.
        XCTAssertEqual(usage.weeklyLabel, "$0.43")
    }

    func test_fetchUsage_handlesMissingCostsFile_gracefully() async throws {
        // No costs.json written at all.
        let service = ZAIUsageService(dataDir: tmpDir.path)
        let usage = await service.fetchUsage(
            apiKey: "fake-key",
            baseUrl: "https://invalid.example/api/anthropic"
        )
        XCTAssertTrue(usage.isConfigured)
        XCTAssertFalse(usage.isAvailable)
        XCTAssertEqual(usage.weeklyCostUSD, 0)
        XCTAssertEqual(usage.todayCostUSD, 0)
        XCTAssertEqual(usage.weeklyLabel, "—")
    }

    // MARK: - parseQuotaResponse (envelope parser)

    func test_parseQuotaResponse_newPlanTwoTokenLimits_pickWeeklyByLaterReset() throws {
        // Session resets at ms=1_700_000_000_000, weekly at ms=1_700_500_000_000.
        let json = """
        {
          "code": 200,
          "msg": "操作成功",
          "success": true,
          "data": {
            "level": "pro",
            "limits": [
              {"type":"TOKENS_LIMIT","percentage":44,"currentValue":1000,"usage":5000,"nextResetTime":1700000000000},
              {"type":"TOKENS_LIMIT","percentage":53,"currentValue":8000,"usage":100000,"nextResetTime":1700500000000},
              {"type":"TIME_LIMIT","percentage":7,"nextResetTime":1800000000000}
            ]
          }
        }
        """
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        XCTAssertEqual(parsed.level, "pro")
        XCTAssertEqual(parsed.sessionPercent, 0.44, accuracy: 0.001)
        XCTAssertEqual(parsed.weeklyPercent, 0.53, accuracy: 0.001)
        XCTAssertEqual(parsed.weeklyTokensUsed, 8000)
        XCTAssertEqual(parsed.weeklyTokensLimit, 100000)

        let expectedWeekly = Date(timeIntervalSince1970: 1_700_500_000_000 / 1000.0)
        let expectedSession = Date(timeIntervalSince1970: 1_700_000_000_000 / 1000.0)
        XCTAssertEqual(parsed.weeklyResetsAt, expectedWeekly)
        XCTAssertEqual(parsed.sessionResetsAt, expectedSession)
        XCTAssertLessThan(parsed.sessionResetsAt!, parsed.weeklyResetsAt!)
    }

    func test_parseQuotaResponse_oldPlanSingleTokenLimit_sessionEqualsWeekly() throws {
        let json = """
        {
          "code": 200,
          "msg": "ok",
          "success": true,
          "data": {
            "level": "lite",
            "limits": [
              {"type":"TOKENS_LIMIT","percentage":72,"currentValue":7200,"usage":10000,"nextResetTime":1700000000000}
            ]
          }
        }
        """
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        XCTAssertEqual(parsed.level, "lite")
        XCTAssertEqual(parsed.sessionPercent, 0.72, accuracy: 0.001)
        XCTAssertEqual(parsed.weeklyPercent, 0.72, accuracy: 0.001)
        XCTAssertEqual(parsed.weeklyTokensUsed, 7200)
        XCTAssertEqual(parsed.weeklyTokensLimit, 10000)
        XCTAssertEqual(parsed.sessionResetsAt, parsed.weeklyResetsAt)
    }

    func test_parseQuotaResponse_newPlanMinimalFields_degradeGracefully() throws {
        // Only type + percentage present — no currentValue, no usage, no nextResetTime.
        // The parser fills in calculated fallback reset times (session = +5h,
        // weekly = next Monday 00:00 local) so the card's renew row always has
        // something meaningful to display even when z.ai omits the timestamps.
        let json = """
        {
          "code": 200,
          "msg": "ok",
          "success": true,
          "data": {
            "level": "pro",
            "limits": [
              {"type":"TOKENS_LIMIT","percentage":44},
              {"type":"TOKENS_LIMIT","percentage":53}
            ]
          }
        }
        """
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        XCTAssertEqual(parsed.level, "pro")
        XCTAssertEqual(parsed.sessionPercent, 0.44, accuracy: 0.001)
        XCTAssertEqual(parsed.weeklyPercent, 0.53, accuracy: 0.001)
        XCTAssertEqual(parsed.weeklyTokensLimit, 0)
        XCTAssertEqual(parsed.weeklyTokensUsed, 0)

        // Fallback reset times must be filled in.
        let session = try XCTUnwrap(parsed.sessionResetsAt)
        let weekly  = try XCTUnwrap(parsed.weeklyResetsAt)
        // Session fallback is "now + 5h" — must be roughly 4h-6h ahead.
        let sessionHoursAhead = session.timeIntervalSinceNow / 3600
        XCTAssertGreaterThan(sessionHoursAhead, 4.5)
        XCTAssertLessThan(sessionHoursAhead, 5.5)
        // Weekly fallback is next Monday 00:00 local — must be in the future
        // and less than 8 days away (strict: at most 7 days + a few seconds).
        let weeklyDaysAhead = weekly.timeIntervalSinceNow / 86400
        XCTAssertGreaterThan(weeklyDaysAhead, 0)
        XCTAssertLessThanOrEqual(weeklyDaysAhead, 7.01)
        // And it must be a Monday at 00:00 local.
        var cal = Calendar(identifier: .iso8601)
        cal.firstWeekday = 2
        cal.timeZone = TimeZone.current
        let comps = cal.dateComponents([.weekday, .hour, .minute], from: weekly)
        XCTAssertEqual(comps.weekday, 2, "Fallback weekly reset should be a Monday")
        XCTAssertEqual(comps.hour, 0)
        XCTAssertEqual(comps.minute, 0)
    }

    func test_parseQuotaResponse_acceptsStringEpoch() throws {
        // Some API variants serialize numeric epochs as strings.
        let json = """
        {"code":200,"success":true,"data":{"level":"pro","limits":[
          {"type":"TOKENS_LIMIT","percentage":30,"currentValue":"3000","usage":"10000","nextResetTime":"1700000000000"}
        ]}}
        """
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        XCTAssertEqual(parsed.weeklyTokensUsed, 3000)
        XCTAssertEqual(parsed.weeklyTokensLimit, 10000)
        XCTAssertEqual(parsed.weeklyResetsAt, Date(timeIntervalSince1970: 1_700_000_000))
    }

    func test_parseQuotaResponse_acceptsAlternateKeyNames() throws {
        // Key aliases: reset_time (snake_case), limit (instead of usage), used.
        let json = """
        {"code":200,"success":true,"data":{"level":"pro","limits":[
          {"type":"TOKENS_LIMIT","percentage":15,"used":1500,"limit":10000,"reset_time":1700000000000}
        ]}}
        """
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        XCTAssertEqual(parsed.weeklyTokensUsed, 1500)
        XCTAssertEqual(parsed.weeklyTokensLimit, 10000)
        XCTAssertEqual(parsed.weeklyResetsAt, Date(timeIntervalSince1970: 1_700_000_000))
    }

    func test_parseQuotaResponse_acceptsEpochSeconds() throws {
        // When the value is below 1e12 it should be treated as epoch seconds.
        let json = """
        {"code":200,"success":true,"data":{"level":"pro","limits":[
          {"type":"TOKENS_LIMIT","percentage":10,"currentValue":100,"usage":1000,"nextResetTime":1700000000}
        ]}}
        """
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        XCTAssertEqual(parsed.weeklyResetsAt, Date(timeIntervalSince1970: 1_700_000_000))
    }

    /// Real payload captured from a live z.ai Coding Plan "pro" account.
    /// Two TOKENS_LIMIT entries distinguished by `unit`+`number`:
    ///   - unit=3, number=5  → 5-hour session window (0% used)
    ///   - unit=6, number=1  → 1-week weekly window (100% used)
    /// Only the weekly entry has `nextResetTime`. The parser MUST treat the
    /// 1-week window as "weekly" (not "session"), even though it's the one
    /// with the reset timestamp.
    func test_parseQuotaResponse_realCodingPlanPayload_discriminatesByUnit() throws {
        let json = #"""
        {
          "code": 200,
          "msg": "Operation successful",
          "success": true,
          "data": {
            "level": "pro",
            "limits": [
              {"type":"TOKENS_LIMIT","unit":3,"number":5,"percentage":0},
              {"type":"TOKENS_LIMIT","unit":6,"number":1,"percentage":100,"nextResetTime":1775961477998},
              {"type":"TIME_LIMIT","unit":5,"number":1,"usage":1000,"currentValue":2,"remaining":998,"percentage":1,"nextResetTime":1777948677998}
            ]
          }
        }
        """#
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        XCTAssertEqual(parsed.level, "pro")
        // Session = 5-hour window (0%). Weekly = 1-week window (100%).
        XCTAssertEqual(parsed.sessionPercent, 0.0, accuracy: 0.001)
        XCTAssertEqual(parsed.weeklyPercent, 1.0, accuracy: 0.001)

        // Weekly reset comes from the real timestamp on the 1-week entry.
        let expectedWeekly = Date(timeIntervalSince1970: 1775961477998 / 1000.0)
        XCTAssertEqual(parsed.weeklyResetsAt, expectedWeekly)

        // Session reset is synthesized: now + 5 hours (the `unit=3, number=5` window).
        let session = try XCTUnwrap(parsed.sessionResetsAt)
        let hoursAhead = session.timeIntervalSinceNow / 3600
        XCTAssertGreaterThan(hoursAhead, 4.5)
        XCTAssertLessThan(hoursAhead, 5.5)
    }

    func test_parseQuotaResponse_windowDurationComputation() throws {
        // Sanity: hours (unit=3) maps to 3600 × number, weeks (unit=6) maps to 7d × number.
        // We test this indirectly: two entries with known units should sort shortest-first.
        let json = #"""
        {"code":200,"success":true,"data":{"level":"pro","limits":[
          {"type":"TOKENS_LIMIT","unit":6,"number":1,"percentage":25},
          {"type":"TOKENS_LIMIT","unit":3,"number":2,"percentage":80}
        ]}}
        """#
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        // 2 hours < 1 week, so the 2h entry must be session.
        XCTAssertEqual(parsed.sessionPercent, 0.80, accuracy: 0.001)
        XCTAssertEqual(parsed.weeklyPercent, 0.25, accuracy: 0.001)
    }

    func test_parseQuotaResponse_envelopeFailureReturnsNil() {
        let json = """
        {"code": 401, "msg": "unauthorized", "success": false, "data": null}
        """
        let result = ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!)
        XCTAssertNil(result)
    }

    func test_parseQuotaResponse_successFalseReturnsNil() {
        let json = """
        {"code": 200, "success": false, "data": {"limits": []}}
        """
        let result = ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!)
        XCTAssertNil(result)
    }

    func test_parseQuotaResponse_ignoresTimeLimit() throws {
        let json = """
        {
          "code": 200,
          "msg": "ok",
          "success": true,
          "data": {
            "level": "unknown",
            "limits": [
              {"type":"TIME_LIMIT","percentage":7,"nextResetTime":1800000000000}
            ]
          }
        }
        """
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        XCTAssertEqual(parsed.level, "unknown")
        // No TOKENS_LIMIT at all → percents are 0 but the parse doesn't crash.
        XCTAssertEqual(parsed.sessionPercent, 0)
        XCTAssertEqual(parsed.weeklyPercent, 0)
        XCTAssertEqual(parsed.weeklyTokensLimit, 0)
        XCTAssertNil(parsed.weeklyResetsAt)
    }

    func test_parseQuotaResponse_emptyLimitsArray_returnsZeros() throws {
        let json = """
        {"code":200,"success":true,"data":{"level":"pro","limits":[]}}
        """
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        XCTAssertEqual(parsed.level, "pro")
        XCTAssertEqual(parsed.sessionPercent, 0)
        XCTAssertEqual(parsed.weeklyPercent, 0)
    }

    func test_parseQuotaResponse_nextResetTimeInMilliseconds() throws {
        // Sanity check: we must convert ms → seconds, not treat it as seconds.
        let ms: Int64 = 1_700_000_000_000
        let json = """
        {"code":200,"success":true,"data":{"level":"pro","limits":[
          {"type":"TOKENS_LIMIT","percentage":10,"currentValue":1,"usage":10,"nextResetTime":\(ms)}
        ]}}
        """
        let parsed = try XCTUnwrap(ZAIUsageService.parseQuotaResponse(json.data(using: .utf8)!))
        let expected = Date(timeIntervalSince1970: Double(ms) / 1000.0)
        XCTAssertEqual(parsed.weeklyResetsAt, expected)
        // Sanity: not treated as seconds (which would be year ~55_862).
        XCTAssertLessThan(parsed.weeklyResetsAt!.timeIntervalSince1970, 3_000_000_000)
    }

    // MARK: - ZAIUsage model

    func test_weeklyLabel_priority_apiOverCostOverDash() {
        var u = ZAIUsage.empty
        u.isConfigured = true
        XCTAssertEqual(u.weeklyLabel, "—")

        u.weeklyCostUSD = 1.234
        XCTAssertEqual(u.weeklyLabel, "$1.23")

        u.isAvailable = true
        u.weeklyPercent = 0.42
        XCTAssertEqual(u.weeklyLabel, "42%")
    }

    func test_planName_uppercasesKnownLevel() {
        var u = ZAIUsage.empty
        u.planLevel = "pro"
        XCTAssertEqual(u.planName, "GLM Coding Plan · PRO")

        u.planLevel = "unknown"
        XCTAssertEqual(u.planName, "GLM Coding Plan")

        u.planLevel = nil
        XCTAssertEqual(u.planName, "GLM Coding Plan")
    }
}
