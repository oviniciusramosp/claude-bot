import Foundation

struct RoutineExecution: Identifiable, Hashable, Sendable {
    var id: String { "\(routineName)-\(timeSlot)-\(date)" }
    var routineName: String
    var timeSlot: String    // "HH:MM"
    var date: String        // "YYYY-MM-DD"
    var status: Status
    var startedAt: Date?
    var finishedAt: Date?
    var error: String?
    var isPipeline: Bool = false
    var pipelineSteps: [StepExecution] = []
    var workspace: String?  // Pipeline workspace path (/tmp/claude-pipeline-...)

    enum Status: String, Sendable {
        case pending
        case running
        case completed
        case failed
        case skipped

        var label: String {
            switch self {
            case .pending: "Pending"
            case .running: "Running"
            case .completed: "Completed"
            case .failed: "Failed"
            case .skipped: "Skipped"
            }
        }

        var symbol: String {
            switch self {
            case .pending: "clock"
            case .running: "arrow.trianglehead.2.clockwise"
            case .completed: "checkmark.circle.fill"
            case .failed: "xmark.circle.fill"
            case .skipped: "forward.fill"
            }
        }

        var color: String {
            switch self {
            case .pending: "secondary"
            case .running: "statusBlue"
            case .completed: "statusGreen"
            case .failed: "statusRed"
            case .skipped: "secondary"
            }
        }
    }

    var duration: String? {
        guard let start = startedAt, let end = finishedAt else { return nil }
        let secs = Int(end.timeIntervalSince(start))
        if secs < 60 { return "\(secs)s" }
        return "\(secs / 60)m \(secs % 60)s"
    }

    /// Duration for running executions (measures from startedAt to now)
    var liveDuration: String? {
        guard let start = startedAt else { return nil }
        let end = finishedAt ?? Date()
        let secs = Int(end.timeIntervalSince(start))
        if secs < 60 { return "\(secs)s" }
        return "\(secs / 60)m \(secs % 60)s"
    }

    /// Time label: "17:20" from startedAt, or timeSlot if no startedAt
    var timeLabel: String {
        if let start = startedAt {
            let f = DateFormatter()
            f.dateFormat = "HH:mm"
            return f.string(from: start)
        }
        return timeSlot
    }
}

struct StepActivity: Hashable, Sendable {
    var activityType: String  // "thinking", "tool", "text"
    var detail: String        // e.g. "Bash: curl -s https://..."
    var tools: [String]       // last 3 tool calls
}

struct StepExecution: Identifiable, Hashable, Sendable {
    var id: String      // step id
    var status: RoutineExecution.Status
    var startedAt: Date?
    var finishedAt: Date?
    var error: String?
    var attempt: Int
    var outputType: String?     // "none", "file", "telegram", or vault-relative path
    var activity: StepActivity?  // live activity (from sidecar, only while running)

    var duration: String? {
        guard let start = startedAt, let end = finishedAt else { return nil }
        let secs = Int(end.timeIntervalSince(start))
        if secs < 60 { return "\(secs)s" }
        return "\(secs / 60)m \(secs % 60)s"
    }

    var liveDuration: String? {
        guard let start = startedAt else { return nil }
        let end = finishedAt ?? Date()
        let secs = Int(end.timeIntervalSince(start))
        if secs < 60 { return "\(secs)s" }
        return "\(secs / 60)m \(secs % 60)s"
    }
}
