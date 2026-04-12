import XCTest
@testable import ClaudeBotManager

final class CostHistoryServiceTests: XCTestCase {

    private var tmpDir: URL!

    override func setUp() async throws {
        tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cost-history-tests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: tmpDir)
    }

    // MARK: - Fixtures

    /// Matches the exact shape written by `_track_cost` in claude-fallback-bot.py.
    private let sampleJSON = """
    {
      "current_week": "2026-W15",
      "weeks": {
        "2026-W14": {
          "total": 2.50,
          "days": {
            "2026-04-01": 1.00,
            "2026-04-02": 0.50,
            "2026-04-03": 1.00
          }
        },
        "2026-W15": {
          "total": 4.25,
          "days": {
            "2026-04-06": 2.00,
            "2026-04-07": 1.25,
            "2026-04-08": 1.00
          }
        }
      }
    }
    """

    private func writeSample(_ json: String, as filename: String = "costs.json") throws {
        let url = tmpDir.appendingPathComponent(filename)
        try json.data(using: .utf8)!.write(to: url)
    }

    // MARK: - Tests

    func test_loadMissingFile_returnsEmptyHistory() async throws {
        let service = CostHistoryService(dataDir: tmpDir.path)
        let history = try await service.loadHistory()
        XCTAssertTrue(history.weeks.isEmpty)
        XCTAssertTrue(history.isEmpty)
        XCTAssertNil(history.currentWeek)
    }

    func test_allEntries_returnsEmptyWhenMissing() async throws {
        let service = CostHistoryService(dataDir: tmpDir.path)
        let entries = try await service.allEntries()
        XCTAssertTrue(entries.isEmpty)
    }

    func test_totalForLastDays_returnsZeroWhenMissing() async throws {
        let service = CostHistoryService(dataDir: tmpDir.path)
        let total = try await service.totalForLastDays(7)
        XCTAssertEqual(total, 0, accuracy: 0.0001)
    }

    func test_decode_parsesValidPayload() async throws {
        try writeSample(sampleJSON)
        let service = CostHistoryService(dataDir: tmpDir.path)
        let history = try await service.loadHistory()

        XCTAssertEqual(history.currentWeek, "2026-W15")
        XCTAssertEqual(history.weeks.count, 2)

        // Weeks are sorted ascending by key.
        XCTAssertEqual(history.weeks[0].weekKey, "2026-W14")
        XCTAssertEqual(history.weeks[1].weekKey, "2026-W15")

        XCTAssertEqual(history.weeks[0].total, 2.5, accuracy: 0.0001)
        XCTAssertEqual(history.weeks[1].total, 4.25, accuracy: 0.0001)

        // Days inside a week are sorted ascending.
        XCTAssertEqual(history.weeks[1].days.map(\.day), ["2026-04-06", "2026-04-07", "2026-04-08"])
        XCTAssertEqual(history.weeks[1].days[0].cost, 2.0, accuracy: 0.0001)
    }

    func test_allEntries_flatSortedByDate() async throws {
        try writeSample(sampleJSON)
        let service = CostHistoryService(dataDir: tmpDir.path)
        let entries = try await service.allEntries()

        XCTAssertEqual(entries.count, 6)
        XCTAssertEqual(entries.map(\.day), [
            "2026-04-01",
            "2026-04-02",
            "2026-04-03",
            "2026-04-06",
            "2026-04-07",
            "2026-04-08",
        ])
    }

    func test_malformedJSON_throwsTypedError() async throws {
        try writeSample("this is not json at all")
        let service = CostHistoryService(dataDir: tmpDir.path)

        do {
            _ = try await service.loadHistory()
            XCTFail("Expected loadHistory to throw")
        } catch let err as CostHistoryService.CostHistoryError {
            switch err {
            case .malformedJSON(let detail):
                XCTAssertFalse(detail.isEmpty)
            }
        } catch {
            XCTFail("Expected CostHistoryError, got \(error)")
        }
    }

    func test_nonObjectTopLevel_throws() async throws {
        try writeSample("[1, 2, 3]")
        let service = CostHistoryService(dataDir: tmpDir.path)
        do {
            _ = try await service.loadHistory()
            XCTFail("Expected throw on non-object top level")
        } catch is CostHistoryService.CostHistoryError {
            // expected
        }
    }

    func test_emptyFile_returnsEmptyHistoryInsteadOfThrowing() async throws {
        try writeSample("")
        let service = CostHistoryService(dataDir: tmpDir.path)
        let history = try await service.loadHistory()
        XCTAssertTrue(history.isEmpty)
    }

    func test_missingWeeksKey_returnsEmptyWeeks() async throws {
        // File exists but the bot hasn't written any weeks yet.
        try writeSample("{\"current_week\": \"2026-W15\"}")
        let service = CostHistoryService(dataDir: tmpDir.path)
        let history = try await service.loadHistory()
        XCTAssertEqual(history.currentWeek, "2026-W15")
        XCTAssertTrue(history.weeks.isEmpty)
    }

    func test_dailySeries_fillsMissingDaysWithZero() async throws {
        // Build a payload where only "today" has a cost so we can assert
        // missing days are filled in with zero.
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        fmt.timeZone = TimeZone.current
        let today = Date()
        let todayKey = fmt.string(from: today)

        var cal = Calendar(identifier: .iso8601)
        cal.firstWeekday = 2
        cal.minimumDaysInFirstWeek = 4
        let weekComponents = cal.dateComponents([.yearForWeekOfYear, .weekOfYear], from: today)
        let weekKey = String(format: "%04d-W%02d",
                             weekComponents.yearForWeekOfYear ?? 2026,
                             weekComponents.weekOfYear ?? 1)

        let json = """
        {
          "current_week": "\(weekKey)",
          "weeks": {
            "\(weekKey)": {
              "total": 0.75,
              "days": { "\(todayKey)": 0.75 }
            }
          }
        }
        """
        try writeSample(json)

        let service = CostHistoryService(dataDir: tmpDir.path)
        let series = try await service.dailySeries(forLastDays: 7)

        XCTAssertEqual(series.count, 7)
        // Last entry must be today with the recorded cost.
        XCTAssertEqual(series.last?.day, todayKey)
        XCTAssertEqual(series.last?.cost ?? 0, 0.75, accuracy: 0.0001)
        // All other days filled with zero.
        for entry in series.dropLast() {
            XCTAssertEqual(entry.cost, 0, accuracy: 0.0001, "Day \(entry.day) should be zero-filled")
        }
    }

    func test_totalForLastDays_sumsOnlyRecordedDays() async throws {
        // Put a large amount in a day far in the past and a small amount today.
        // Only today's value should show up in a 7-day total.
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        fmt.timeZone = TimeZone.current
        let today = Date()
        let todayKey = fmt.string(from: today)
        let oldKey = "2020-01-01"

        let json = """
        {
          "current_week": "old-W1",
          "weeks": {
            "old-W1": {
              "total": 999.0,
              "days": { "\(oldKey)": 999.0 }
            },
            "now": {
              "total": 0.50,
              "days": { "\(todayKey)": 0.50 }
            }
          }
        }
        """
        try writeSample(json)

        let service = CostHistoryService(dataDir: tmpDir.path)
        let total = try await service.totalForLastDays(7)
        XCTAssertEqual(total, 0.50, accuracy: 0.0001)
    }

    func test_recentWeeks_honoursLimit() async throws {
        try writeSample(sampleJSON)
        let service = CostHistoryService(dataDir: tmpDir.path)
        let last1 = try await service.recentWeeks(1)
        XCTAssertEqual(last1.count, 1)
        XCTAssertEqual(last1.first?.weekKey, "2026-W15")

        let last5 = try await service.recentWeeks(5)
        XCTAssertEqual(last5.count, 2)  // file only has two weeks
    }

    func test_totalThisWeek_usesCurrentWeekKey() async throws {
        try writeSample(sampleJSON)
        let service = CostHistoryService(dataDir: tmpDir.path)
        let total = try await service.totalThisWeek()
        // current_week = 2026-W15 → total 4.25 from the fixture
        XCTAssertEqual(total, 4.25, accuracy: 0.0001)
    }

    func test_totalToday_returnsZeroWhenTodayNotRecorded() async throws {
        try writeSample(sampleJSON)
        let service = CostHistoryService(dataDir: tmpDir.path)
        let today = try await service.totalToday()
        // Sample fixture days are from April 2026, unlikely to equal the
        // actual current date — either way, if they don't match, total is 0.
        let fmt = DateFormatter()
        fmt.dateFormat = "yyyy-MM-dd"
        fmt.timeZone = TimeZone.current
        let key = fmt.string(from: Date())
        let expected = ["2026-04-01", "2026-04-02", "2026-04-03",
                        "2026-04-06", "2026-04-07", "2026-04-08"].contains(key)
        if expected {
            XCTAssertGreaterThan(today, 0)
        } else {
            XCTAssertEqual(today, 0, accuracy: 0.0001)
        }
    }
}

// MARK: - Provider-aware queries

final class CostHistoryProviderQueries: XCTestCase {

    private var tmpDir: URL!

    override func setUp() async throws {
        tmpDir = FileManager.default.temporaryDirectory
            .appendingPathComponent("cost-history-provider-tests-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: tmpDir, withIntermediateDirectories: true)
    }

    override func tearDown() async throws {
        try? FileManager.default.removeItem(at: tmpDir)
    }

    private func writeSample(_ json: String) throws {
        let url = tmpDir.appendingPathComponent("costs.json")
        try json.data(using: .utf8)!.write(to: url)
    }

    /// Returns today's YYYY-MM-DD in the current timezone — used so we can
    /// assert on a provider-today query without timezone drift.
    private var todayKey: String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.timeZone = TimeZone.current
        return f.string(from: Date())
    }

    /// ISO week key for "now" matching the Python "%G-W%V" format.
    private var currentWeekKey: String {
        var cal = Calendar(identifier: .iso8601)
        cal.firstWeekday = 2
        cal.minimumDaysInFirstWeek = 4
        let c = cal.dateComponents([.yearForWeekOfYear, .weekOfYear], from: Date())
        return String(format: "%04d-W%02d", c.yearForWeekOfYear ?? 2026, c.weekOfYear ?? 1)
    }

    func test_totalThisWeek_forZaiProvider_parsesProviderBucket() async throws {
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
        try writeSample(json)

        let service = CostHistoryService(dataDir: tmpDir.path)
        let zaiTotal = try await service.totalThisWeek(provider: "zai")
        XCTAssertEqual(zaiTotal, 0.43, accuracy: 0.0001)

        let anthropicTotal = try await service.totalThisWeek(provider: "anthropic")
        XCTAssertEqual(anthropicTotal, 0.80, accuracy: 0.0001)
    }

    func test_totalThisWeek_backCompat_oldEntriesCountAsAnthropic() async throws {
        // NO providers key — represents a costs.json written by an older bot.
        let week = currentWeekKey
        let today = todayKey
        let json = """
        {
          "current_week": "\(week)",
          "weeks": {
            "\(week)": {
              "total": 2.50,
              "days": { "\(today)": 2.50 }
            }
          }
        }
        """
        try writeSample(json)

        let service = CostHistoryService(dataDir: tmpDir.path)
        let anthropicTotal = try await service.totalThisWeek(provider: "anthropic")
        XCTAssertEqual(anthropicTotal, 2.50, accuracy: 0.0001)

        let zaiTotal = try await service.totalThisWeek(provider: "zai")
        XCTAssertEqual(zaiTotal, 0, accuracy: 0.0001)
    }

    func test_weeklyReference_excludesCurrentWeek() async throws {
        let currentWeek = currentWeekKey
        // Three past weeks plus the current week. The current week's zai total
        // is intentionally huge so we can prove it's ignored.
        let json = """
        {
          "current_week": "\(currentWeek)",
          "weeks": {
            "2026-W10": {
              "total": 1.0, "days": {},
              "providers": { "zai": {"total": 1.0, "days": {}} }
            },
            "2026-W11": {
              "total": 3.0, "days": {},
              "providers": { "zai": {"total": 3.0, "days": {}} }
            },
            "2026-W12": {
              "total": 2.0, "days": {},
              "providers": { "zai": {"total": 2.0, "days": {}} }
            },
            "\(currentWeek)": {
              "total": 99.0, "days": {},
              "providers": { "zai": {"total": 99.0, "days": {}} }
            }
          }
        }
        """
        try writeSample(json)

        let service = CostHistoryService(dataDir: tmpDir.path)
        let ref = try await service.weeklyReference(provider: "zai")
        XCTAssertEqual(ref, 3.0, accuracy: 0.0001, "Reference should be max of the 3 past weeks, ignoring current")
    }

    func test_totalToday_forZaiProvider() async throws {
        let week = currentWeekKey
        let today = todayKey
        let json = """
        {
          "current_week": "\(week)",
          "weeks": {
            "\(week)": {
              "total": 1.00,
              "days": { "\(today)": 1.00 },
              "providers": {
                "zai": {"total": 0.60, "days": {"\(today)": 0.15}}
              }
            }
          }
        }
        """
        try writeSample(json)

        let service = CostHistoryService(dataDir: tmpDir.path)
        let todayZai = try await service.totalToday(provider: "zai")
        XCTAssertEqual(todayZai, 0.15, accuracy: 0.0001)

        // Unknown provider → 0
        let todayOther = try await service.totalToday(provider: "cohere")
        XCTAssertEqual(todayOther, 0, accuracy: 0.0001)
    }
}
