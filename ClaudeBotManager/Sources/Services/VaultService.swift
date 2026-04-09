import Foundation

actor VaultService {
    private let vaultURL: URL
    private let fm = FileManager.default

    init(vaultPath: String) {
        self.vaultURL = URL(fileURLWithPath: vaultPath, isDirectory: true)
    }

    // MARK: - Agents

    func loadAgents() throws -> [Agent] {
        let agentsURL = vaultURL.appending(component: "Agents", directoryHint: .isDirectory)
        guard fm.fileExists(atPath: agentsURL.path) else { return [] }

        let entries = try fm.contentsOfDirectory(atPath: agentsURL.path)
        var agents: [Agent] = []

        for entry in entries {
            let agentURL = agentsURL.appending(component: entry, directoryHint: .isDirectory)
            var isDir: ObjCBool = false
            guard fm.fileExists(atPath: agentURL.path, isDirectory: &isDir), isDir.boolValue else { continue }
            guard entry != ".obsidian" else { continue }

            let agentMdURL = agentURL.appending(component: "agent.md")
            let claudeMdURL = agentURL.appending(component: "CLAUDE.md")
            guard fm.fileExists(atPath: agentMdURL.path) else { continue }

            let content = try String(contentsOf: agentMdURL, encoding: .utf8)
            let (fm_data, _) = FrontmatterParser.parse(content)
            let instructions = (try? String(contentsOf: claudeMdURL, encoding: .utf8)) ?? ""

            let agent = Agent(
                id: entry,
                name: fm_data["name"] as? String ?? fm_data["title"] as? String ?? entry,
                icon: fm_data["icon"] as? String ?? "🤖",
                description: fm_data["description"] as? String ?? "",
                personality: fm_data["personality"] as? String ?? "",
                model: fm_data["model"] as? String ?? "sonnet",
                tags: fm_data["tags"] as? [String] ?? [],
                isDefault: fm_data["default"] as? Bool ?? false,
                source: fm_data["source"] as? String,
                sourceId: fm_data["source_id"] as? String,
                instructions: instructions,
                created: fm_data["created"] as? String ?? today(),
                updated: fm_data["updated"] as? String ?? today()
            )
            agents.append(agent)
        }
        return agents.sorted { $0.name < $1.name }
    }

    func saveAgent(_ agent: Agent) throws {
        let agentURL = agentDirURL(for: agent.id)
        try fm.createDirectory(at: agentURL, withIntermediateDirectories: true)
        let journalURL = agentURL.appending(component: "Journal", directoryHint: .isDirectory)
        if !fm.fileExists(atPath: journalURL.path) {
            try fm.createDirectory(at: journalURL, withIntermediateDirectories: true)
        }

        var frontmatter: [String: Any] = [
            "title": agent.name,
            "description": agent.description,
            "type": "agent",
            "created": agent.created,
            "updated": today(),
            "tags": agent.tags.isEmpty ? ["agent"] : agent.tags,
            "name": agent.name,
            "personality": agent.personality,
            "model": agent.model,
            "icon": agent.icon,
            "default": agent.isDefault
        ]
        if let src = agent.source { frontmatter["source"] = src }
        if let sid = agent.sourceId { frontmatter["source_id"] = sid }

        let orderedKeys = ["title", "description", "type", "created", "updated", "tags",
                           "name", "personality", "model", "icon", "default"]
        let agentMdContent = FrontmatterParser.serialize(frontmatter, orderedKeys: orderedKeys, body: "\n[[Agents]]\n")
        try agentMdContent.write(to: agentURL.appending(component: "agent.md"), atomically: true, encoding: .utf8)

        // CLAUDE.md — no frontmatter
        try agent.instructions.write(to: agentURL.appending(component: "CLAUDE.md"), atomically: true, encoding: .utf8)

        // {id}.md hub
        let hubContent = "[[\(agent.id)/CLAUDE|CLAUDE]]\n[[agent]]\n[[\(agent.id)/Journal|Journal]]\n"
        try hubContent.write(to: agentURL.appending(component: "\(agent.id).md"), atomically: true, encoding: .utf8)

        try updateAgentsIndex(agent)
    }

    func deleteAgent(id: String) throws {
        let agentURL = agentDirURL(for: id)
        guard fm.fileExists(atPath: agentURL.path) else { return }
        try fm.trashItem(at: agentURL, resultingItemURL: nil)
        try removeFromAgentsIndex(id: id)
    }

    // MARK: - Routines

    func loadRoutines() throws -> [Routine] {
        let routinesURL = vaultURL.appending(component: "Routines", directoryHint: .isDirectory)
        guard fm.fileExists(atPath: routinesURL.path) else { return [] }

        let entries = try fm.contentsOfDirectory(atPath: routinesURL.path)
        var routines: [Routine] = []

        for entry in entries {
            guard entry.hasSuffix(".md") && entry != "Routines.md" else { continue }
            let fileURL = routinesURL.appending(component: entry)
            let content = try String(contentsOf: fileURL, encoding: .utf8)
            let (fm_data, body) = FrontmatterParser.parse(content)

            let name = String(entry.dropLast(3))
            let scheduleDict = fm_data["schedule"] as? [String: Any] ?? [:]
            let schedule = Routine.Schedule(
                times: scheduleDict["times"] as? [String] ?? [],
                days: scheduleDict["days"] as? [String] ?? ["*"],
                until: scheduleDict["until"] as? String
            )

            let promptBody = body
                .replacingOccurrences(of: "[[Routines]]\n", with: "")
                .replacingOccurrences(of: "[[Routines]]", with: "")
                .trimmingCharacters(in: .whitespacesAndNewlines)

            // Detect pipeline type and count steps
            let routineType = fm_data["type"] as? String ?? "routine"
            var stepCount = 0
            if routineType == "pipeline" {
                // Count "- id:" occurrences in ```pipeline block
                stepCount = promptBody.components(separatedBy: "\n")
                    .filter { $0.trimmingCharacters(in: .whitespaces).hasPrefix("- id:") }
                    .count
            }

            let routine = Routine(
                id: name,
                title: fm_data["title"] as? String ?? name,
                description: fm_data["description"] as? String ?? "",
                schedule: schedule,
                model: fm_data["model"] as? String ?? "sonnet",
                agentId: fm_data["agent"] as? String,
                enabled: fm_data["enabled"] as? Bool ?? true,
                promptBody: promptBody,
                created: fm_data["created"] as? String ?? today(),
                updated: fm_data["updated"] as? String ?? today(),
                tags: fm_data["tags"] as? [String] ?? ["routine"],
                routineType: routineType,
                stepCount: stepCount,
                minimalContext: (fm_data["context"] as? String) == "minimal"
            )
            routines.append(routine)
        }
        return routines.sorted { $0.title < $1.title }
    }

    func saveRoutine(_ routine: Routine) throws {
        let routinesURL = vaultURL.appending(component: "Routines", directoryHint: .isDirectory)
        try fm.createDirectory(at: routinesURL, withIntermediateDirectories: true)

        let isPipeline = routine.routineType == "pipeline"

        var frontmatter: [String: Any] = [
            "title": routine.title,
            "description": routine.description,
            "type": routine.routineType,
            "created": routine.created,
            "updated": today(),
            "tags": routine.tags.isEmpty ? [routine.routineType] : routine.tags,
            "schedule": [
                "times": routine.schedule.times,
                "days": routine.schedule.days
            ] as [String: Any],
            "model": routine.model,
            "enabled": routine.enabled
        ]
        if let agent = routine.agentId { frontmatter["agent"] = agent }
        if isPipeline { frontmatter["notify"] = routine.notify }
        if routine.minimalContext { frontmatter["context"] = "minimal" }
        if let until = routine.schedule.until {
            var sched = frontmatter["schedule"] as! [String: Any]
            sched["until"] = until
            frontmatter["schedule"] = sched
        }

        let orderedKeys = ["title", "description", "type", "created", "updated", "tags", "schedule", "model", "enabled"]

        let body: String
        if isPipeline && !routine.pipelineStepDefs.isEmpty {
            let pipelineBlock = PipelineStepDef.buildPipelineBody(routine.pipelineStepDefs)
            body = "\n[[Routines]]\n\n\(pipelineBlock)\n"
        } else {
            body = "\n[[Routines]]\n\n\(routine.promptBody)\n"
        }

        let content = FrontmatterParser.serialize(frontmatter, orderedKeys: orderedKeys, body: body)
        let fileURL = routinesURL.appending(component: "\(routine.id).md")
        try content.write(to: fileURL, atomically: true, encoding: .utf8)
        try updateRoutinesIndex(routine)

        // Save pipeline step prompt files
        if isPipeline && !routine.pipelineStepDefs.isEmpty {
            try savePipelineStepFiles(routineId: routine.id, steps: routine.pipelineStepDefs)
        }
    }

    func savePipelineStepFiles(routineId: String, steps: [PipelineStepDef]) throws {
        let stepsDir = vaultURL
            .appending(component: "Routines", directoryHint: .isDirectory)
            .appending(component: routineId, directoryHint: .isDirectory)
            .appending(component: "steps", directoryHint: .isDirectory)
        try fm.createDirectory(at: stepsDir, withIntermediateDirectories: true)

        // Write each step file (auto-append vault wikilink for Obsidian graph)
        for step in steps where !step.stepId.isEmpty {
            let fileURL = stepsDir.appending(component: "\(step.stepId).md")
            let content = step.prompt.trimmingCharacters(in: .whitespacesAndNewlines)
                + "\n\nrotina: [[\(routineId)]]\n"
            try content.write(to: fileURL, atomically: true, encoding: .utf8)
        }

        // Remove orphan step files
        if let existing = try? fm.contentsOfDirectory(atPath: stepsDir.path) {
            let validIds = Set(steps.map { "\($0.stepId).md" })
            for file in existing where file.hasSuffix(".md") && !validIds.contains(file) {
                try? fm.removeItem(at: stepsDir.appending(component: file))
            }
        }
    }

    func loadPipelineStepDefs(routineId: String, promptBody: String) -> [PipelineStepDef] {
        // Parse step ids/names/config from the ```pipeline block
        var steps: [PipelineStepDef] = []
        var inBlock = false
        var current: [String: String] = [:]

        for line in promptBody.components(separatedBy: "\n") {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.hasPrefix("```pipeline") { inBlock = true; continue }
            if inBlock && trimmed == "```" { break }
            if !inBlock { continue }
            if trimmed == "steps:" { continue }

            if trimmed.hasPrefix("- ") {
                if !current.isEmpty { steps.append(stepDefFromDict(current)) }
                current = [:]
                let rest = String(trimmed.dropFirst(2)).trimmingCharacters(in: .whitespaces)
                if let colonIdx = rest.firstIndex(of: ":") {
                    current[String(rest[..<colonIdx]).trimmingCharacters(in: .whitespaces)] =
                        String(rest[rest.index(after: colonIdx)...]).trimmingCharacters(in: .whitespaces)
                }
            } else if trimmed.contains(":") {
                if let colonIdx = trimmed.firstIndex(of: ":") {
                    current[String(trimmed[..<colonIdx]).trimmingCharacters(in: .whitespaces)] =
                        String(trimmed[trimmed.index(after: colonIdx)...]).trimmingCharacters(in: .whitespaces)
                }
            }
        }
        if !current.isEmpty { steps.append(stepDefFromDict(current)) }

        // Load prompt text from files
        let stepsDir = vaultURL
            .appending(component: "Routines", directoryHint: .isDirectory)
            .appending(component: routineId, directoryHint: .isDirectory)
            .appending(component: "steps", directoryHint: .isDirectory)

        for i in steps.indices {
            let fileURL = stepsDir.appending(component: "\(steps[i].stepId).md")
            var text = (try? String(contentsOf: fileURL, encoding: .utf8)) ?? ""
            // Strip trailing vault wikilink (auto-managed Obsidian graph metadata)
            let lines = text.components(separatedBy: "\n")
            if let last = lines.last(where: { !$0.trimmingCharacters(in: .whitespaces).isEmpty }),
               last.contains("[[") && last.contains("]]") {
                text = lines.reversed().drop(while: {
                    let t = $0.trimmingCharacters(in: .whitespaces)
                    return t.isEmpty || (t.contains("[[") && t.contains("]]"))
                }).reversed().joined(separator: "\n")
            }
            steps[i].prompt = text.trimmingCharacters(in: .whitespacesAndNewlines)
        }

        return steps
    }

    private func stepDefFromDict(_ dict: [String: String]) -> PipelineStepDef {
        let name = dict["name"]?.trimmingCharacters(in: CharacterSet(charactersIn: "\"")) ?? ""
        var depsStr = dict["depends_on"] ?? ""
        // Parse [a, b, c] flow list
        if depsStr.hasPrefix("[") && depsStr.hasSuffix("]") {
            depsStr = String(depsStr.dropFirst().dropLast())
        }
        let deps = depsStr.isEmpty ? [] : depsStr.components(separatedBy: ",").map {
            $0.trimmingCharacters(in: .whitespaces).trimmingCharacters(in: CharacterSet(charactersIn: "\""))
        }
        return PipelineStepDef(
            stepId: dict["id"] ?? "",
            name: name,
            model: dict["model"] ?? "sonnet",
            dependsOn: deps,
            prompt: "",
            timeout: Int(dict["timeout"] ?? "1200") ?? 1200,
            inactivityTimeout: Int(dict["inactivity_timeout"] ?? "300") ?? 300,
            retry: Int(dict["retry"] ?? "0") ?? 0,
            outputToTelegram: dict["output"]?.lowercased() == "telegram",
            outputType: {
                let raw = dict["output"]?.trimmingCharacters(in: .whitespaces) ?? ""
                if raw.isEmpty { return "file" }
                let lower = raw.lowercased()
                if lower == "telegram" || lower == "none" { return lower }
                return raw  // vault path
            }(),
            outputFile: dict["output_file"]?.trimmingCharacters(in: .whitespaces) ?? ""
        )
    }

    func deleteRoutine(id: String) throws {
        let routinesURL = vaultURL.appending(component: "Routines", directoryHint: .isDirectory)
        let fileURL = routinesURL.appending(component: "\(id).md")
        guard fm.fileExists(atPath: fileURL.path) else { return }
        try fm.trashItem(at: fileURL, resultingItemURL: nil)
        // Also trash pipeline step directory if it exists
        let pipelineDir = routinesURL.appending(component: id, directoryHint: .isDirectory)
        if fm.fileExists(atPath: pipelineDir.path) {
            try fm.trashItem(at: pipelineDir, resultingItemURL: nil)
        }
        try removeFromRoutinesIndex(id: id)
    }

    // MARK: - Skills

    func loadSkills() throws -> [Skill] {
        let skillsURL = vaultURL.appending(component: "Skills", directoryHint: .isDirectory)
        guard fm.fileExists(atPath: skillsURL.path) else { return [] }

        let entries = try fm.contentsOfDirectory(atPath: skillsURL.path)
        var skills: [Skill] = []

        for entry in entries {
            guard entry.hasSuffix(".md") && entry != "Skills.md" else { continue }
            let fileURL = skillsURL.appending(component: entry)
            let content = try String(contentsOf: fileURL, encoding: .utf8)
            let (fm_data, body) = FrontmatterParser.parse(content)

            let name = String(entry.dropLast(3))
            let cleanBody = body
                .replacingOccurrences(of: "[[Skills]]\n", with: "")
                .replacingOccurrences(of: "[[Skills]]", with: "")
                .trimmingCharacters(in: .whitespacesAndNewlines)

            let skill = Skill(
                id: name,
                title: fm_data["title"] as? String ?? name,
                description: fm_data["description"] as? String ?? "",
                trigger: fm_data["trigger"] as? String ?? "",
                tags: fm_data["tags"] as? [String] ?? ["skill"],
                created: fm_data["created"] as? String ?? today(),
                updated: fm_data["updated"] as? String ?? today(),
                body: cleanBody
            )
            skills.append(skill)
        }
        return skills.sorted { $0.title < $1.title }
    }

    func saveSkill(_ skill: Skill) throws {
        let skillsURL = vaultURL.appending(component: "Skills", directoryHint: .isDirectory)
        try fm.createDirectory(at: skillsURL, withIntermediateDirectories: true)

        let yamlLines = [
            "title: \"\(skill.title)\"",
            "description: \"\(skill.description)\"",
            "trigger: \"\(skill.trigger)\"",
            "tags: [\(skill.tags.map { "\"\($0)\"" }.joined(separator: ", "))]",
            "created: \"\(skill.created.isEmpty ? today() : skill.created)\"",
            "updated: \"\(today())\""
        ]

        let content = "---\n\(yamlLines.joined(separator: "\n"))\n---\n\n\(skill.body)"
        let fileURL = skillsURL.appending(component: "\(skill.id).md")
        try content.write(to: fileURL, atomically: true, encoding: .utf8)
        try updateSkillsIndex(skill)
    }

    private func updateSkillsIndex(_ skill: Skill) throws {
        let indexURL = vaultURL.appending(component: "Skills").appending(component: "Skills.md")
        var content = (try? String(contentsOf: indexURL, encoding: .utf8)) ?? ""
        if !content.contains("[[\(skill.id)]]") {
            content += "\n- [[\(skill.id)]] — \(skill.description)"
            try content.write(to: indexURL, atomically: true, encoding: .utf8)
        }
    }

    func deleteSkill(id: String) throws {
        guard !Skill.builtInIds.contains(id) else { return }
        let skillsURL = vaultURL.appending(component: "Skills", directoryHint: .isDirectory)
        let fileURL = skillsURL.appending(component: "\(id).md")
        guard fm.fileExists(atPath: fileURL.path) else { return }
        try fm.trashItem(at: fileURL, resultingItemURL: nil)
        try removeFromSkillsIndex(id: id)
    }

    // MARK: - Index helpers

    private func updateAgentsIndex(_ agent: Agent) throws {
        let indexURL = vaultURL.appending(component: "Agents").appending(component: "Agents.md")
        var content = (try? String(contentsOf: indexURL, encoding: .utf8)) ?? ""
        let link = "- [[\(agent.id)/\(agent.id)|\(agent.name)]] — \(agent.description)"
        if !content.contains("[[\(agent.id)/") {
            content += "\n\(link)"
            try content.write(to: indexURL, atomically: true, encoding: .utf8)
        }
    }

    private func removeFromAgentsIndex(id: String) throws {
        let indexURL = vaultURL.appending(component: "Agents").appending(component: "Agents.md")
        guard var content = try? String(contentsOf: indexURL, encoding: .utf8) else { return }
        let lines = content.components(separatedBy: "\n").filter { !$0.contains("[[\(id)/") }
        content = lines.joined(separator: "\n")
        try content.write(to: indexURL, atomically: true, encoding: .utf8)
    }

    private func updateRoutinesIndex(_ routine: Routine) throws {
        let indexURL = vaultURL.appending(component: "Routines").appending(component: "Routines.md")
        var content = (try? String(contentsOf: indexURL, encoding: .utf8)) ?? ""
        let link = "- [[\(routine.id)]] — \(routine.description)"
        if !content.contains("[[\(routine.id)]]") {
            content += "\n\(link)"
            try content.write(to: indexURL, atomically: true, encoding: .utf8)
        }
    }

    private func removeFromRoutinesIndex(id: String) throws {
        let indexURL = vaultURL.appending(component: "Routines").appending(component: "Routines.md")
        guard var content = try? String(contentsOf: indexURL, encoding: .utf8) else { return }
        let lines = content.components(separatedBy: "\n").filter { !$0.contains("[[\(id)]]") }
        content = lines.joined(separator: "\n")
        try content.write(to: indexURL, atomically: true, encoding: .utf8)
    }

    private func removeFromSkillsIndex(id: String) throws {
        let indexURL = vaultURL.appending(component: "Skills").appending(component: "Skills.md")
        guard var content = try? String(contentsOf: indexURL, encoding: .utf8) else { return }
        let lines = content.components(separatedBy: "\n").filter { !$0.contains("[[\(id)]]") }
        content = lines.joined(separator: "\n")
        try content.write(to: indexURL, atomically: true, encoding: .utf8)
    }

    // MARK: - Main Agent (project CLAUDE.md)

    private var projectCLAUDEURL: URL {
        vaultURL.deletingLastPathComponent().appendingPathComponent("CLAUDE.md")
    }

    func loadMainAgent() -> Agent {
        let instructions = (try? String(contentsOf: projectCLAUDEURL, encoding: .utf8)) ?? ""
        return Agent(
            id: "main",
            name: "Main",
            icon: "🤖",
            description: "Bot padrão — nenhum agente específico ativo",
            personality: "",
            model: "sonnet",
            tags: [],
            isDefault: true,
            source: nil,
            sourceId: nil,
            instructions: instructions,
            created: "",
            updated: ""
        )
    }

    func saveMainAgent(instructions: String) throws {
        try instructions.write(to: projectCLAUDEURL, atomically: true, encoding: .utf8)
    }

    // MARK: - Helpers

    private func agentDirURL(for id: String) -> URL {
        vaultURL.appending(component: "Agents", directoryHint: .isDirectory)
            .appending(component: id, directoryHint: .isDirectory)
    }

    private func today() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }
}
