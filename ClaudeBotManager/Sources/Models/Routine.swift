import Foundation

struct Routine: Identifiable, Hashable, Sendable {
    var id: String          // filename without .md
    var title: String
    var description: String
    var schedule: Schedule
    var model: String
    var agentId: String?
    var enabled: Bool
    var promptBody: String  // text after frontmatter
    var created: String
    var updated: String
    var tags: [String]
    var routineType: String = "routine"  // "routine" or "pipeline"
    var stepCount: Int = 0               // number of pipeline steps (0 for regular)
    var notify: String = "final"         // pipeline notify mode: final | all | summary | none
    var minimalContext: Bool = false      // true = skip vault system prompt, use only CLAUDE.md
    var pipelineStepDefs: [PipelineStepDef] = []  // step definitions for UI editing

    struct Schedule: Hashable, Sendable {
        var times: [String]     // ["HH:MM", ...]
        var days: [String]      // ["mon", "tue", ...] or ["*"]
        var until: String?      // "YYYY-MM-DD" optional
    }

    // Today's execution status (loaded from routines-state)
    var todayExecutions: [RoutineExecution] = []

    var nextExecutionDescription: String {
        guard enabled else { return "Disabled" }
        let now = Date()
        let calendar = Calendar.current
        let formatter = DateFormatter()
        formatter.dateFormat = "HH:mm"

        let dayMap = ["mon": 2, "tue": 3, "wed": 4, "thu": 5, "fri": 6, "sat": 7, "sun": 1]
        let todayWeekday = calendar.component(.weekday, from: now)
        let allDays = schedule.days.contains("*")

        for timeStr in schedule.times.sorted() {
            let parts = timeStr.split(separator: ":").compactMap { Int($0) }
            guard parts.count == 2 else { continue }
            var comps = calendar.dateComponents([.year, .month, .day], from: now)
            comps.hour = parts[0]
            comps.minute = parts[1]
            comps.second = 0
            if let target = calendar.date(from: comps), target > now {
                if allDays { return "Today at \(timeStr)" }
                let abbr: String
                switch todayWeekday {
                case 1: abbr = "sun"
                case 2: abbr = "mon"
                case 3: abbr = "tue"
                case 4: abbr = "wed"
                case 5: abbr = "thu"
                case 6: abbr = "fri"
                case 7: abbr = "sat"
                default: abbr = ""
                }
                if schedule.days.contains(abbr) { return "Today at \(timeStr)" }
            }
        }
        return schedule.times.first.map { "Next: \($0)" } ?? "No schedule"
    }

    var lastExecution: RoutineExecution? {
        todayExecutions.last
    }

    var isPipeline: Bool { routineType == "pipeline" }

    /// Built-in routines shipped with the repo — can be disabled but not deleted
    static let builtInIds: Set<String> = ["update-check", "vault-graph-update", "journal-audit"]
    var isBuiltIn: Bool { Self.builtInIds.contains(id) }

    /// For pipelines: count of completed/failed/skipped steps across today's executions
    var pipelineStepsCompleted: Int {
        guard let exec = lastExecution else { return 0 }
        return exec.pipelineSteps.filter { $0.status == .completed }.count
    }

    var pipelineStepsTotal: Int {
        guard let exec = lastExecution, !exec.pipelineSteps.isEmpty else { return stepCount }
        return exec.pipelineSteps.count
    }
}

// MARK: - Pipeline Step Definition (for UI editing)

struct PipelineStepDef: Identifiable, Hashable, Sendable {
    var id = UUID()
    var stepId: String = ""         // kebab-case slug
    var name: String = ""           // human-readable name
    var model: String = "sonnet"
    var dependsOn: [String] = []    // step ids this step depends on
    var prompt: String = ""         // prompt text
    var timeout: Int = 1200         // max wall-clock seconds (hard limit)
    var inactivityTimeout: Int = 300  // max seconds without output
    var retry: Int = 0
    var outputToTelegram: Bool = false
    var outputType: String = "file"  // "none", "file", "telegram", or vault-relative path
    var outputFile: String = ""      // custom output filename (empty = {stepId}.md)

    /// Resolved output filename: custom if set, otherwise {stepId}.md
    var resolvedFilename: String {
        outputFile.isEmpty ? "\(stepId).md" : outputFile
    }

    /// Auto-generate stepId from name
    mutating func autoId() {
        stepId = name.lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .filter { $0.isLetter || $0.isNumber || $0 == "-" }
    }

    /// Build the ```pipeline block line for this step
    func toYamlLines() -> [String] {
        var lines = [
            "  - id: \(stepId)",
            "    name: \"\(name)\"",
            "    model: \(model)",
        ]
        if !dependsOn.isEmpty {
            lines.append("    depends_on: [\(dependsOn.joined(separator: ", "))]")
        }
        lines.append("    prompt_file: steps/\(stepId).md")
        if timeout != 1200 { lines.append("    timeout: \(timeout)") }
        if inactivityTimeout != 300 { lines.append("    inactivity_timeout: \(inactivityTimeout)") }
        if retry > 0 { lines.append("    retry: \(retry)") }
        if outputType != "file" { lines.append("    output: \(outputType)") }
        if !outputFile.isEmpty { lines.append("    output_file: \(outputFile)") }
        return lines
    }

    /// Build the full ```pipeline block from an array of steps
    static func buildPipelineBody(_ steps: [PipelineStepDef]) -> String {
        var lines = ["```pipeline", "steps:"]
        for step in steps {
            lines.append(contentsOf: step.toYamlLines())
            lines.append("")
        }
        lines.append("```")
        return lines.joined(separator: "\n")
    }
}
