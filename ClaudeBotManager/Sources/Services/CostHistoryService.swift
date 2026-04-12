import Foundation
import os

/// Reads the bot's cost tracker file (~/.claude-bot/costs.json).
///
/// The schema matches what `_track_cost()` in claude-fallback-bot.py writes:
///
/// ```json
/// {
///   "current_week": "2026-W15",
///   "weeks": {
///     "2026-W15": {
///       "total": 1.2345,
///       "days": { "2026-04-07": 0.12, "2026-04-08": 0.34 }
///     }
///   }
/// }
/// ```
///
/// The bot keeps the last 4 weeks in the file. This service is tolerant of a
/// missing file (new users) and throws a typed error on malformed JSON so the
/// caller can show an empty state without crashing.
actor CostHistoryService {
    private let filePath: String
    private static let logger = Logger(subsystem: "com.claudebot.manager", category: "CostHistoryService")

    /// ISO-8601 date formatter for per-day keys: "YYYY-MM-DD".
    /// Shared on the instance to avoid allocating per call.
    private let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone.current
        return f
    }()

    /// Calendar fixed to ISO weeks (week starts Monday) so it matches the
    /// Python "%G-W%V" week key the bot writes.
    private let isoCalendar: Calendar = {
        var cal = Calendar(identifier: .iso8601)
        cal.firstWeekday = 2  // Monday
        cal.minimumDaysInFirstWeek = 4
        return cal
    }()

    init(dataDir: String) {
        self.filePath = (dataDir as NSString).appendingPathComponent("costs.json")
    }

    // MARK: - Public API

    enum CostHistoryError: Error, LocalizedError {
        case malformedJSON(String)

        var errorDescription: String? {
            switch self {
            case .malformedJSON(let detail):
                return "Malformed costs.json: \(detail)"
            }
        }
    }

    /// Load the entire cost history. Returns an empty value if the file does
    /// not exist yet (new users). Throws `CostHistoryError.malformedJSON` if
    /// the file exists but cannot be decoded.
    func loadHistory() throws -> CostHistory {
        guard FileManager.default.fileExists(atPath: filePath) else {
            return .empty
        }
        let url = URL(fileURLWithPath: filePath)
        let data: Data
        do {
            data = try Data(contentsOf: url)
        } catch {
            Self.logger.error("Failed to read costs.json at \(self.filePath, privacy: .public): \(error.localizedDescription, privacy: .public)")
            throw CostHistoryError.malformedJSON("read failed: \(error.localizedDescription)")
        }
        guard !data.isEmpty else { return .empty }
        do {
            return try decode(data: data)
        } catch let err as CostHistoryError {
            Self.logger.error("Decode failure on costs.json: \(err.localizedDescription, privacy: .public)")
            throw err
        }
    }

    /// Parse from raw data (exposed for tests so we don't need disk access).
    func decode(data: Data) throws -> CostHistory {
        let parsed: Any
        do {
            parsed = try JSONSerialization.jsonObject(with: data, options: [])
        } catch {
            throw CostHistoryError.malformedJSON("invalid JSON: \(error.localizedDescription)")
        }
        guard let obj = parsed as? [String: Any] else {
            throw CostHistoryError.malformedJSON("top level is not an object")
        }

        let currentWeek = obj["current_week"] as? String
        guard let weeksRaw = obj["weeks"] as? [String: Any] else {
            // File exists but has no weeks yet — treat as empty rather than a failure.
            return CostHistory(currentWeek: currentWeek, weeks: [])
        }

        var weeks: [WeekBucket] = []
        for (key, rawWeek) in weeksRaw {
            guard let w = rawWeek as? [String: Any] else { continue }
            let total = doubleValue(w["total"]) ?? 0
            var days: [DayBucket] = []
            if let daysRaw = w["days"] as? [String: Any] {
                for (dayStr, rawCost) in daysRaw {
                    guard let cost = doubleValue(rawCost), let date = dayFormatter.date(from: dayStr) else {
                        continue
                    }
                    days.append(DayBucket(day: dayStr, date: date, cost: cost))
                }
            }
            days.sort { $0.day < $1.day }

            // Optional per-provider slice — present only when the bot tagged
            // entries with a provider key. Old files without this key are
            // treated as 100% anthropic at query time.
            var providers: [String: ProviderBucket] = [:]
            if let provsRaw = w["providers"] as? [String: Any] {
                for (providerKey, rawProv) in provsRaw {
                    guard let pDict = rawProv as? [String: Any] else { continue }
                    let pTotal = doubleValue(pDict["total"]) ?? 0
                    var pDays: [DayBucket] = []
                    if let pDaysRaw = pDict["days"] as? [String: Any] {
                        for (dayStr, rawCost) in pDaysRaw {
                            guard let cost = doubleValue(rawCost),
                                  let date = dayFormatter.date(from: dayStr) else { continue }
                            pDays.append(DayBucket(day: dayStr, date: date, cost: cost))
                        }
                    }
                    pDays.sort { $0.day < $1.day }
                    providers[providerKey] = ProviderBucket(total: pTotal, days: pDays)
                }
            }

            weeks.append(WeekBucket(weekKey: key, total: total, days: days, providers: providers))
        }
        weeks.sort { $0.weekKey < $1.weekKey }
        return CostHistory(currentWeek: currentWeek, weeks: weeks)
    }

    // MARK: - Aggregation helpers

    /// Flat list of (date, cost) entries across every week in the file,
    /// sorted ascending by date. Days without data are NOT injected here;
    /// use `dailySeries(forLastDays:)` for a dense series.
    func allEntries() throws -> [CostEntry] {
        let history = try loadHistory()
        return history.weeks
            .flatMap { $0.days }
            .map { CostEntry(date: $0.date, day: $0.day, cost: $0.cost) }
            .sorted { $0.date < $1.date }
    }

    /// Returns a dense day-by-day cost series for the last `days` days,
    /// including days with zero cost so a chart has a continuous x-axis.
    func dailySeries(forLastDays days: Int) throws -> [CostEntry] {
        precondition(days > 0, "days must be positive")
        let entries = try allEntries()
        let byDay = Dictionary(uniqueKeysWithValues: entries.map { ($0.day, $0.cost) })

        let cal = Calendar.current
        let today = cal.startOfDay(for: Date())
        var result: [CostEntry] = []
        for offset in (0..<days).reversed() {
            guard let d = cal.date(byAdding: .day, value: -offset, to: today) else { continue }
            let key = dayFormatter.string(from: d)
            result.append(CostEntry(date: d, day: key, cost: byDay[key] ?? 0))
        }
        return result
    }

    /// Total cost over the last `days` days (inclusive of today).
    func totalForLastDays(_ days: Int) throws -> Double {
        try dailySeries(forLastDays: days).reduce(0) { $0 + $1.cost }
    }

    /// Total cost for the current ISO week as tracked by the bot.
    /// Falls back to summing today+previous 6 days if the file has no current week.
    func totalThisWeek() throws -> Double {
        let history = try loadHistory()
        if let key = history.currentWeek, let bucket = history.weeks.first(where: { $0.weekKey == key }) {
            return bucket.total
        }
        return try totalForLastDays(7)
    }

    /// Total cost for today (YYYY-MM-DD).
    func totalToday() throws -> Double {
        let entries = try allEntries()
        let today = dayFormatter.string(from: Date())
        return entries.first(where: { $0.day == today })?.cost ?? 0
    }

    // MARK: - Provider-aware queries
    //
    // Back-compat rule: weeks with no `providers` dict are assumed to be 100%
    // anthropic. This lets the Dashboard show zeros for newer providers (zai)
    // on files written by older bot versions without breaking on upgrade.

    /// Total cost for the current ISO week, filtered by provider.
    /// Returns 0 if the requested provider has no data yet.
    func totalThisWeek(provider: String) throws -> Double {
        let history = try loadHistory()
        guard let key = history.currentWeek,
              let bucket = history.weeks.first(where: { $0.weekKey == key }) else {
            return 0
        }
        if bucket.providers.isEmpty {
            return provider == "anthropic" ? bucket.total : 0
        }
        return bucket.providers[provider]?.total ?? 0
    }

    /// Total cost for today, filtered by provider.
    func totalToday(provider: String) throws -> Double {
        let history = try loadHistory()
        guard let key = history.currentWeek,
              let bucket = history.weeks.first(where: { $0.weekKey == key }) else {
            return 0
        }
        let todayKey = dayFormatter.string(from: Date())
        if bucket.providers.isEmpty {
            guard provider == "anthropic" else { return 0 }
            return bucket.days.first(where: { $0.day == todayKey })?.cost ?? 0
        }
        guard let prov = bucket.providers[provider] else { return 0 }
        return prov.days.first(where: { $0.day == todayKey })?.cost ?? 0
    }

    /// Max of past complete weeks for this provider — used as the "100%"
    /// reference for progress bars when no HTTP quota is available. Excludes
    /// the current week so the bar can exceed 100% when the user is burning
    /// faster than their worst past week.
    func weeklyReference(provider: String) throws -> Double {
        let history = try loadHistory()
        let pastWeeks = history.weeks.filter { $0.weekKey != history.currentWeek }
        let maxVal = pastWeeks.map { bucket -> Double in
            if bucket.providers.isEmpty {
                return provider == "anthropic" ? bucket.total : 0
            }
            return bucket.providers[provider]?.total ?? 0
        }.max() ?? 0
        return maxVal
    }

    /// Returns up to the last `count` weeks present in the file (newest last),
    /// useful for a weekly-total bar chart.
    func recentWeeks(_ count: Int) throws -> [WeekBucket] {
        precondition(count > 0)
        let history = try loadHistory()
        return Array(history.weeks.suffix(count))
    }

    // MARK: - Private

    private func doubleValue(_ raw: Any?) -> Double? {
        if let d = raw as? Double { return d }
        if let i = raw as? Int { return Double(i) }
        if let n = raw as? NSNumber { return n.doubleValue }
        if let s = raw as? String { return Double(s) }
        return nil
    }
}

// MARK: - Models

/// Full decoded view of costs.json.
struct CostHistory: Sendable, Equatable {
    var currentWeek: String?
    var weeks: [WeekBucket]  // sorted ascending by weekKey

    static let empty = CostHistory(currentWeek: nil, weeks: [])

    var isEmpty: Bool { weeks.allSatisfy { $0.days.isEmpty } }
}

/// One ISO-week bucket as written by the bot ("2026-W15").
struct WeekBucket: Sendable, Equatable, Identifiable {
    var weekKey: String
    var total: Double                                 // combined, back-compat
    var days: [DayBucket]                             // combined, back-compat
    var providers: [String: ProviderBucket] = [:]    // optional per-provider slice

    var id: String { weekKey }
}

/// One provider's slice of a week (anthropic | zai).
struct ProviderBucket: Sendable, Equatable {
    var total: Double
    var days: [DayBucket]
}

/// One day of cost inside a week bucket.
struct DayBucket: Sendable, Equatable, Identifiable {
    var day: String   // "YYYY-MM-DD" (as written in JSON)
    var date: Date
    var cost: Double

    var id: String { day }
}

/// A flat, chart-friendly cost entry.
struct CostEntry: Sendable, Equatable, Identifiable, Hashable {
    var date: Date
    var day: String
    var cost: Double

    var id: String { day }
}
