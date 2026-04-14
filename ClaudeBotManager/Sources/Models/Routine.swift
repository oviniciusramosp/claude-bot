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
    /// Owning agent id (v3.5 flat per-agent vault layout). Defaults to "main".
    /// This determines where the routine file lives on disk:
    /// `vault/<ownerAgentId>/Routines/<id>.md`. It is separate from
    /// `agentId` which is the execution-time routing target (legacy field).
    var ownerAgentId: String = "main"

    struct Schedule: Hashable, Sendable {
        var times: [String]       // ["HH:MM", ...] — used in clock mode
        var days: [String]        // ["mon", "tue", ...] or ["*"]
        var until: String?        // "YYYY-MM-DD" optional
        var interval: String?     // "30m", "4h", "3d", "2w" — replaces times
        var monthdays: [Int]      // [1, 15] — day-of-month filter (empty = all)

        var isIntervalMode: Bool { interval != nil && !(interval?.isEmpty ?? true) }
    }

    // Today's execution status (loaded from routines-state)
    var todayExecutions: [RoutineExecution] = []

    var nextExecutionDescription: String {
        guard enabled else { return "Disabled" }

        if schedule.isIntervalMode {
            guard let iv = schedule.interval else { return "No schedule" }
            let unitMap = ["m": "min", "h": "h", "d": "d", "w": "w"]
            if let last = iv.last.map(String.init), let unit = unitMap[last] {
                let val = String(iv.dropLast())
                return "Every \(val)\(unit)"
            }
            return "Every \(iv)"
        }

        let now = Date()
        let calendar = Calendar.current
        let todayWeekday = calendar.component(.weekday, from: now)
        let allDays = schedule.days.contains("*")

        for timeStr in schedule.times.sorted() {
            let parts = timeStr.split(separator: ":").compactMap { Int($0) }
            guard parts.count == 2 else { continue }
            var comps = calendar.dateComponents([.year, .month, .day], from: now)
            comps.hour = parts[0]; comps.minute = parts[1]; comps.second = 0
            if let target = calendar.date(from: comps), target > now {
                if allDays { return "Today at \(timeStr)" }
                let abbr: String
                switch todayWeekday {
                case 1: abbr = "sun"; case 2: abbr = "mon"; case 3: abbr = "tue"
                case 4: abbr = "wed"; case 5: abbr = "thu"; case 6: abbr = "fri"
                case 7: abbr = "sat"; default: abbr = ""
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
    static let builtInIds: Set<String> = [
        "update-check", "vault-nightly", "vault-lint",
        "journal-audit", "journal-weekly-rollup",
    ]
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
    var isManual: Bool = false        // true = human review gate, no Claude invocation
    var manualInputFile: String = "" // explicit .md to review (empty = derived from depends_on[0])
    var manualTunnel: Bool = true    // include Tailscale Funnel web editor link in Telegram message
    /// When true (default), this step is auto-skipped if ALL its dependencies
    /// returned NO_REPLY. Set false for steps with side effects that must
    /// always run even when upstream found nothing (cleanup, heartbeat, etc.).
    var skipOnNoReply: Bool = true

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
        ]
        if isManual {
            lines.append("    manual: true")
            if !manualInputFile.isEmpty { lines.append("    input_file: \(manualInputFile)") }
            if !manualTunnel { lines.append("    tunnel: false") }
        } else {
            lines.append("    model: \(model)")
        }
        if !dependsOn.isEmpty {
            lines.append("    depends_on: [\(dependsOn.joined(separator: ", "))]")
        }
        if !isManual {
            lines.append("    prompt_file: steps/\(stepId).md")
        }
        if timeout != 1200 { lines.append("    timeout: \(timeout)") }
        if !isManual {
            if inactivityTimeout != 300 { lines.append("    inactivity_timeout: \(inactivityTimeout)") }
            if retry > 0 { lines.append("    retry: \(retry)") }
            if outputType != "file" { lines.append("    output: \(outputType)") }
            if !outputFile.isEmpty { lines.append("    output_file: \(outputFile)") }
        } else {
            if !outputFile.isEmpty { lines.append("    output_file: \(outputFile)") }
        }
        // Only serialise when opting OUT — default (true) stays implicit so
        // existing pipelines don't get a noisy new field on every save.
        if !skipOnNoReply { lines.append("    skip_on_no_reply: false") }
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
