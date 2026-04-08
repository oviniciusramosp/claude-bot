import Foundation

struct LogEntry: Identifiable, Sendable {
    var id = UUID()
    var timestamp: Date
    var level: Level
    var message: String
    var rawLine: String

    enum Level: String, Sendable, CaseIterable {
        case debug = "DEBUG"
        case info = "INFO"
        case warning = "WARNING"
        case error = "ERROR"

        var label: String { rawValue }
    }

    // Parse a log line like: "2026-04-07 08:30:15,123 - INFO - message here"
    static func parse(_ line: String) -> LogEntry {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss,SSS"

        var date = Date()
        var level = Level.info
        var message = line

        // "2026-04-07 08:30:15,123 - INFO - rest of message"
        let parts = line.components(separatedBy: " - ")
        if parts.count >= 3 {
            if let d = formatter.date(from: parts[0].trimmingCharacters(in: .whitespaces)) {
                date = d
            }
            let lvlStr = parts[1].trimmingCharacters(in: .whitespaces)
            level = Level(rawValue: lvlStr) ?? .info
            message = parts[2...].joined(separator: " - ")
        }

        return LogEntry(timestamp: date, level: level, message: message, rawLine: line)
    }
}
