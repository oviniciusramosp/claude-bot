import Foundation

actor RoutineStateService {
    private let dataDir: String

    init(dataDir: String) {
        self.dataDir = dataDir
    }

    func loadTodayState() -> [String: [String: RoutineExecution]] {
        let today = dateString(Date())
        return loadState(for: today)
    }

    func loadSlot(routineId: String, timeSlot: String) -> RoutineExecution? {
        let today = dateString(Date())
        return loadState(for: today)[routineId]?[timeSlot]
    }

    func pollUntilDone(routineId: String, timeSlot: String, timeout: TimeInterval = 180) async -> RoutineExecution? {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            if let exec = loadSlot(routineId: routineId, timeSlot: timeSlot),
               exec.status != .running {
                return exec
            }
        }
        return nil
    }

    func loadAllHistory(days: Int = 30) -> [RoutineExecution] {
        let stateDir = (dataDir as NSString).appendingPathComponent("routines-state")
        guard let files = try? FileManager.default.contentsOfDirectory(atPath: stateDir) else { return [] }

        var all: [RoutineExecution] = []
        let sortedFiles = files.filter { $0.hasSuffix(".json") }.sorted().suffix(days)
        for file in sortedFiles {
            let date = String(file.dropLast(5)) // remove .json
            let path = (stateDir as NSString).appendingPathComponent(file)
            guard let data = FileManager.default.contents(atPath: path),
                  let json = try? JSONSerialization.jsonObject(with: data) as? [String: [String: [String: Any]]] else { continue }

            for (routineName, slots) in json {
                for (timeSlot, slotData) in slots {
                    let exec = parseExecution(routineName: routineName, timeSlot: timeSlot, date: date, data: slotData)
                    all.append(exec)
                }
            }
        }
        return all.sorted { ($0.startedAt ?? .distantPast) > ($1.startedAt ?? .distantPast) }
    }

    func loadHistory(for routineId: String, days: Int = 30) -> [RoutineExecution] {
        loadAllHistory(days: days).filter { $0.routineName == routineId }
    }

    private func loadState(for date: String) -> [String: [String: RoutineExecution]] {
        let stateDir = (dataDir as NSString).appendingPathComponent("routines-state")
        let path = (stateDir as NSString).appendingPathComponent("\(date).json")
        guard let data = FileManager.default.contents(atPath: path),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: [String: [String: Any]]] else {
            return [:]
        }

        var result: [String: [String: RoutineExecution]] = [:]
        for (routineName, slots) in json {
            var slotMap: [String: RoutineExecution] = [:]
            for (timeSlot, slotData) in slots {
                slotMap[timeSlot] = parseExecution(routineName: routineName, timeSlot: timeSlot, date: date, data: slotData)
            }
            result[routineName] = slotMap
        }
        return result
    }

    private func parseExecution(routineName: String, timeSlot: String, date: String, data: [String: Any]) -> RoutineExecution {
        let statusStr = data["status"] as? String ?? "pending"
        let status = parseStatus(statusStr)

        let startedAt = parseDate(data["started_at"] as? String)
        let finishedAt = parseDate(data["finished_at"] as? String)

        let isPipeline = (data["type"] as? String) == "pipeline"
        var pipelineSteps: [StepExecution] = []
        if isPipeline, let stepsDict = data["steps"] as? [String: [String: Any]] {
            for (stepId, stepData) in stepsDict {
                let stepStatus = parseStatus(stepData["status"] as? String ?? "pending")
                pipelineSteps.append(StepExecution(
                    id: stepId,
                    status: stepStatus,
                    startedAt: parseDate(stepData["started_at"] as? String),
                    finishedAt: parseDate(stepData["finished_at"] as? String),
                    error: stepData["error"] as? String,
                    attempt: stepData["attempt"] as? Int ?? 0,
                    outputType: stepData["output_type"] as? String
                ))
            }
            // Sort by started_at (pending steps last)
            pipelineSteps.sort { a, b in
                (a.startedAt ?? .distantFuture) < (b.startedAt ?? .distantFuture)
            }
        }

        return RoutineExecution(
            routineName: routineName,
            timeSlot: timeSlot,
            date: date,
            status: status,
            startedAt: startedAt,
            finishedAt: finishedAt,
            error: data["error"] as? String,
            isPipeline: isPipeline,
            pipelineSteps: pipelineSteps,
            workspace: data["workspace"] as? String
        )
    }

    /// Load live pipeline activity from sidecar file (pipeline-activity.json).
    /// Returns [pipelineName: [stepId: StepActivity]].
    func loadPipelineActivity() -> [String: [String: StepActivity]] {
        let path = (dataDir as NSString).appendingPathComponent("pipeline-activity.json")
        guard let data = FileManager.default.contents(atPath: path),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: [String: [String: Any]]]
        else { return [:] }

        var result: [String: [String: StepActivity]] = [:]
        for (pipelineName, steps) in json {
            var stepMap: [String: StepActivity] = [:]
            for (stepId, stepData) in steps {
                let activityType = stepData["activity_type"] as? String ?? "thinking"
                let detail = stepData["detail"] as? String ?? ""
                let tools = stepData["tools"] as? [String] ?? []
                stepMap[stepId] = StepActivity(activityType: activityType, detail: detail, tools: tools)
            }
            result[pipelineName] = stepMap
        }
        return result
    }

    private func parseStatus(_ str: String) -> RoutineExecution.Status {
        switch str {
        case "running": return .running
        case "completed": return .completed
        case "failed": return .failed
        case "skipped": return .skipped
        default: return .pending
        }
    }

    private func parseDate(_ str: String?) -> Date? {
        guard let str else { return nil }
        // Try ISO8601 first, then fallback to custom format
        let iso = ISO8601DateFormatter()
        if let d = iso.date(from: str) { return d }
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.date(from: str)
    }

    private func dateString(_ date: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: date)
    }
}
