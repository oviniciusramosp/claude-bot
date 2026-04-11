import Foundation

actor VaultService {
    private let vaultURL: URL
    private let fm = FileManager.default

    init(vaultPath: String) {
        self.vaultURL = URL(fileURLWithPath: vaultPath, isDirectory: true)
    }

    /// v3.3 sub-index naming. Each agent's per-folder index file uses the
    /// `agent-<folder>` prefix so the LLM treats them as graph hubs and skips
    /// them when scanning. The bot's loaders filter these names out so the
    /// indexes never get mistaken for individual items.
    private static let subIndexFilenames: Set<String> = [
        "agent-skills.md",
        "agent-routines.md",
        "agent-journal.md",
        "agent-reactions.md",
        "agent-lessons.md",
        "agent-notes.md",
    ]

    // MARK: - Agents

    /// v3.4: every agent lives directly under ``vault/<id>/``. An agent is any
    /// top-level directory containing ``agent-<id>.md`` (the hub file with
    /// metadata in frontmatter and parent → child wikilinks in the body).
    func loadAgents() throws -> [Agent] {
        var agents: [Agent] = []
        for agentId in iterAgentIds() {
            let agentURL = agentDirURL(for: agentId)
            let infoURL = agentURL.appending(component: "agent-\(agentId).md")
            let claudeMdURL = agentURL.appending(component: "CLAUDE.md")

            let content = (try? String(contentsOf: infoURL, encoding: .utf8)) ?? ""
            let (fm_data, _) = FrontmatterParser.parse(content)
            let rawClaude = (try? String(contentsOf: claudeMdURL, encoding: .utf8)) ?? ""
            let sections = Agent.parseCLAUDEmd(rawClaude)

            let agent = Agent(
                id: agentId,
                name: fm_data["name"] as? String ?? fm_data["title"] as? String ?? agentId,
                icon: fm_data["icon"] as? String ?? "🤖",
                description: fm_data["description"] as? String ?? "",
                personality: fm_data["personality"] as? String ?? "",
                model: fm_data["model"] as? String ?? "sonnet",
                color: fm_data["color"] as? String ?? "grey",
                tags: fm_data["tags"] as? [String] ?? [],
                isDefault: fm_data["default"] as? Bool ?? false,
                source: fm_data["source"] as? String,
                sourceId: fm_data["source_id"] as? String,
                created: fm_data["created"] as? String ?? today(),
                updated: fm_data["updated"] as? String ?? today(),
                personalityAndTone: sections.personality,
                instructions: sections.instructions,
                specializations: sections.specializations,
                otherInstructions: sections.other,
                chatId: fm_data["chat_id"].map { "\($0)" } ?? "",
                threadId: fm_data["thread_id"].map { "\($0)" } ?? ""
            )
            agents.append(agent)
        }
        return agents.sorted { $0.name < $1.name }
    }

    func saveAgent(_ agent: Agent) throws {
        let agentURL = agentDirURL(for: agent.id)
        try fm.createDirectory(at: agentURL, withIntermediateDirectories: true)

        // v3.1 flat per-agent vault layout: every agent owns its own copy of
        // Skills/, Routines/, Reactions/, Lessons/, Notes/, .workspace/, and
        // Journal/ (with a .activity/ subdir). Isolamento total.
        //
        // v3.5: .workspace/ is dot-prefixed so Obsidian's dotfile filter hides
        // pipeline runtime data from the graph view automatically — no
        // userIgnoreFilters regex needed.
        let subdirs = [
            "Skills", "Routines", "Reactions", "Lessons",
            "Notes", ".workspace", "Journal", "Journal/.activity",
        ]
        for sub in subdirs {
            let url = agentURL.appending(path: sub, directoryHint: .isDirectory)
            if !fm.fileExists(atPath: url.path) {
                try fm.createDirectory(at: url, withIntermediateDirectories: true)
            }
        }

        // agent-<id>.md — frontmatter carries metadata, body carries the
        // hub wikilinks that make the agent's subtree reachable from the
        // Obsidian graph.
        var frontmatter: [String: Any] = [
            "title": agent.name,
            "description": agent.description,
            "type": "agent",
            "created": agent.created,
            "updated": today(),
            "tags": agent.tags.isEmpty ? ["agent", "hub"] : agent.tags,
            "name": agent.name,
            "model": agent.model,
            "icon": agent.icon,
            "color": agent.color.isEmpty ? "grey" : agent.color,
            "default": agent.isDefault,
            "personality": agent.personality
        ]
        if let src = agent.source { frontmatter["source"] = src }
        if let sid = agent.sourceId { frontmatter["source_id"] = sid }
        if !agent.chatId.isEmpty { frontmatter["chat_id"] = agent.chatId }
        if !agent.threadId.isEmpty { frontmatter["thread_id"] = Int(agent.threadId) ?? agent.threadId as Any }

        let orderedKeys = ["title", "description", "type", "created", "updated", "tags",
                           "name", "model", "icon", "color", "default", "personality",
                           "chat_id", "thread_id", "source", "source_id"]
        // v3.3: agent-info points DOWN to its sub-indexes via path-qualified
        // wikilinks. Each link uses the full vault-relative path so Obsidian's
        // resolver always picks files from THIS agent (not another agent's
        // file with the same basename).
        let hubBody = """

        - [[\(agent.id)/Skills/agent-skills|Skills]]
        - [[\(agent.id)/Routines/agent-routines|Routines]]
        - [[\(agent.id)/Journal/agent-journal|Journal]]
        - [[\(agent.id)/Reactions/agent-reactions|Reactions]]
        - [[\(agent.id)/Lessons/agent-lessons|Lessons]]
        - [[\(agent.id)/Notes/agent-notes|Notes]]
        - [[\(agent.id)/CLAUDE|CLAUDE]]

        """
        let infoContent = FrontmatterParser.serialize(frontmatter, orderedKeys: orderedKeys, body: hubBody)
        try infoContent.write(
            to: agentURL.appending(component: "agent-\(agent.id).md"),
            atomically: true,
            encoding: .utf8
        )
        // Drop any legacy v3.1/v3.2 hub file from the same dir.
        let legacyHub = agentURL.appending(component: "agent-info.md")
        if fm.fileExists(atPath: legacyHub.path) {
            try? fm.removeItem(at: legacyHub)
        }

        // CLAUDE.md — structured personality/instructions, no frontmatter.
        try agent.toCLAUDEmd().write(to: agentURL.appending(component: "CLAUDE.md"), atomically: true, encoding: .utf8)

        // Clean up legacy files left behind by a v3.0 bundle, if any.
        for legacy in ["agent.md", "\(agent.id).md"] {
            let url = agentURL.appending(component: legacy)
            if fm.fileExists(atPath: url.path) {
                try? fm.removeItem(at: url)
            }
        }
    }

    func deleteAgent(id: String) throws {
        let agentURL = agentDirURL(for: id)
        guard fm.fileExists(atPath: agentURL.path) else { return }
        try fm.trashItem(at: agentURL, resultingItemURL: nil)
    }

    // MARK: - Routines

    /// v3.1: routines live under `<agent>/Routines/`. We walk every agent
    /// directly under the vault root and return the union, tagging each
    /// routine with its owning agent id.
    func loadRoutines() throws -> [Routine] {
        var routines: [Routine] = []

        for agentId in iterAgentIds() {
            let agentDir = agentDirURL(for: agentId)
            let routinesURL = agentDir.appending(component: "Routines", directoryHint: .isDirectory)
            guard fm.fileExists(atPath: routinesURL.path) else { continue }

            let entries = (try? fm.contentsOfDirectory(atPath: routinesURL.path)) ?? []
            for entry in entries {
                guard entry.hasSuffix(".md") && !Self.subIndexFilenames.contains(entry) else { continue }
                let fileURL = routinesURL.appending(component: entry)
                guard let content = try? String(contentsOf: fileURL, encoding: .utf8) else { continue }
                let (fm_data, body) = FrontmatterParser.parse(content)

                let name = String(entry.dropLast(3))
                let scheduleDict = fm_data["schedule"] as? [String: Any] ?? [:]
                let rawMonthdays = scheduleDict["monthdays"] as? [Any] ?? []
                let parsedMonthdays = rawMonthdays.compactMap { v -> Int? in
                    if let i = v as? Int { return i }
                    if let s = v as? String { return Int(s) }
                    return nil
                }
                let schedule = Routine.Schedule(
                    times: scheduleDict["times"] as? [String] ?? [],
                    days: scheduleDict["days"] as? [String] ?? ["*"],
                    until: scheduleDict["until"] as? String,
                    interval: scheduleDict["interval"] as? String,
                    monthdays: parsedMonthdays
                )

                let promptBody = body
                    .replacingOccurrences(of: "[[Routines]]\n", with: "")
                    .replacingOccurrences(of: "[[Routines]]", with: "")
                    .trimmingCharacters(in: .whitespacesAndNewlines)

                // Detect pipeline type and count steps
                let routineType = fm_data["type"] as? String ?? "routine"
                var stepCount = 0
                if routineType == "pipeline" {
                    stepCount = promptBody.components(separatedBy: "\n")
                        .filter { $0.trimmingCharacters(in: .whitespaces).hasPrefix("- id:") }
                        .count
                }

                // owner derives from the file path; frontmatter `agent:` is kept
                // for the legacy execution-routing field (Routine.agentId).
                var routine = Routine(
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
                routine.ownerAgentId = agentId
                routines.append(routine)
            }
        }
        return routines.sorted { $0.title < $1.title }
    }

    func saveRoutine(_ routine: Routine) throws {
        let owner = routine.ownerAgentId.isEmpty ? "main" : routine.ownerAgentId
        let routinesURL = agentDirURL(for: owner)
            .appending(component: "Routines", directoryHint: .isDirectory)
        try fm.createDirectory(at: routinesURL, withIntermediateDirectories: true)

        let isPipeline = routine.routineType == "pipeline"

        var frontmatter: [String: Any] = [
            "title": routine.title,
            "description": routine.description,
            "type": routine.routineType,
            "created": routine.created,
            "updated": today(),
            "tags": routine.tags.isEmpty ? [routine.routineType] : routine.tags,
            "schedule": {
                var s: [String: Any] = ["days": routine.schedule.days]
                if let iv = routine.schedule.interval, !iv.isEmpty {
                    s["interval"] = iv
                } else {
                    s["times"] = routine.schedule.times
                }
                if !routine.schedule.monthdays.isEmpty {
                    s["monthdays"] = routine.schedule.monthdays
                }
                return s
            }(),
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
            // Auto-generated `## Steps` section: parent owns the parent->step edges
            // in the Obsidian graph. Step files MUST NOT contain wikilinks.
            // Use vault-root absolute paths so Obsidian's resolver always picks
            // the right file regardless of basename collisions across pipelines.
            let stepLinks = routine.pipelineStepDefs
                .filter { !$0.stepId.isEmpty }
                .map { "- [[\(owner)/Routines/\(routine.id)/steps/\($0.stepId)|\($0.stepId)]]" }
                .joined(separator: "\n")
            let stepsSection = stepLinks.isEmpty ? "" : "\n\n## Steps\n\n\(stepLinks)\n"
            // v3.3 parent → child convention: leaf files (routines, pipelines)
            // do NOT carry a `[[Routines]]` parent wikilink — agent-routines.md
            // points DOWN to them via its marker block.
            body = "\n\(pipelineBlock)\(stepsSection)"
        } else {
            body = "\n\(routine.promptBody)\n"
        }

        let content = FrontmatterParser.serialize(frontmatter, orderedKeys: orderedKeys, body: body)
        let fileURL = routinesURL.appending(component: "\(routine.id).md")
        try content.write(to: fileURL, atomically: true, encoding: .utf8)
        try updateRoutinesIndex(routine, ownerAgentId: owner)

        // Save pipeline step prompt files
        if isPipeline && !routine.pipelineStepDefs.isEmpty {
            try savePipelineStepFiles(
                ownerAgentId: owner,
                routineId: routine.id,
                steps: routine.pipelineStepDefs
            )
        }
    }

    func savePipelineStepFiles(ownerAgentId: String, routineId: String, steps: [PipelineStepDef]) throws {
        let stepsDir = agentDirURL(for: ownerAgentId)
            .appending(component: "Routines", directoryHint: .isDirectory)
            .appending(component: routineId, directoryHint: .isDirectory)
            .appending(component: "steps", directoryHint: .isDirectory)
        try fm.createDirectory(at: stepsDir, withIntermediateDirectories: true)

        // Write each step file as a clean prompt — NO wikilinks, NO frontmatter.
        // The parent->step edge is owned by the parent pipeline file's
        // `## Steps` section. See vault/CLAUDE.md "Pipeline graph".
        for step in steps where !step.stepId.isEmpty {
            let fileURL = stepsDir.appending(component: "\(step.stepId).md")
            let content = step.prompt.trimmingCharacters(in: .whitespacesAndNewlines) + "\n"
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

    func loadPipelineStepDefs(routineId: String, promptBody: String, ownerAgentId: String = "main") -> [PipelineStepDef] {
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

        // Load prompt text from files (v3.0: under owning agent's Routines dir)
        let stepsDir = agentDirURL(for: ownerAgentId.isEmpty ? "main" : ownerAgentId)
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

    func deleteRoutine(id: String, ownerAgentId: String = "main") throws {
        let owner = ownerAgentId.isEmpty ? "main" : ownerAgentId
        let routinesURL = agentDirURL(for: owner)
            .appending(component: "Routines", directoryHint: .isDirectory)
        let fileURL = routinesURL.appending(component: "\(id).md")
        guard fm.fileExists(atPath: fileURL.path) else { return }
        try fm.trashItem(at: fileURL, resultingItemURL: nil)
        // Also trash pipeline step directory if it exists
        let pipelineDir = routinesURL.appending(component: id, directoryHint: .isDirectory)
        if fm.fileExists(atPath: pipelineDir.path) {
            try fm.trashItem(at: pipelineDir, resultingItemURL: nil)
        }
        try removeFromRoutinesIndex(id: id, ownerAgentId: owner)
    }

    // MARK: - Skills

    /// v3.1: skills live under `<agent>/Skills/`. Walk every agent folder.
    func loadSkills() throws -> [Skill] {
        var skills: [Skill] = []

        for agentId in iterAgentIds() {
            let agentDir = agentDirURL(for: agentId)
            let skillsURL = agentDir.appending(component: "Skills", directoryHint: .isDirectory)
            guard fm.fileExists(atPath: skillsURL.path) else { continue }

            let entries = (try? fm.contentsOfDirectory(atPath: skillsURL.path)) ?? []
            for entry in entries {
                guard entry.hasSuffix(".md") && !Self.subIndexFilenames.contains(entry) else { continue }
                let fileURL = skillsURL.appending(component: entry)
                guard let content = try? String(contentsOf: fileURL, encoding: .utf8) else { continue }
                let (fm_data, body) = FrontmatterParser.parse(content)

                let name = String(entry.dropLast(3))
                let cleanBody = body
                    .replacingOccurrences(of: "[[Skills]]\n", with: "")
                    .replacingOccurrences(of: "[[Skills]]", with: "")
                    .trimmingCharacters(in: .whitespacesAndNewlines)

                var skill = Skill(
                    id: name,
                    title: fm_data["title"] as? String ?? name,
                    description: fm_data["description"] as? String ?? "",
                    trigger: fm_data["trigger"] as? String ?? "",
                    tags: fm_data["tags"] as? [String] ?? ["skill"],
                    created: fm_data["created"] as? String ?? today(),
                    updated: fm_data["updated"] as? String ?? today(),
                    body: cleanBody
                )
                skill.ownerAgentId = agentId
                skills.append(skill)
            }
        }
        return skills.sorted { $0.title < $1.title }
    }

    func saveSkill(_ skill: Skill) throws {
        let owner = skill.ownerAgentId.isEmpty ? "main" : skill.ownerAgentId
        let skillsURL = agentDirURL(for: owner)
            .appending(component: "Skills", directoryHint: .isDirectory)
        try fm.createDirectory(at: skillsURL, withIntermediateDirectories: true)

        let yamlLines = [
            "title: \"\(skill.title)\"",
            "description: \"\(skill.description)\"",
            "trigger: \"\(skill.trigger)\"",
            "tags: [\(skill.tags.map { "\"\($0)\"" }.joined(separator: ", "))]",
            "agent: \"\(owner)\"",
            "created: \"\(skill.created.isEmpty ? today() : skill.created)\"",
            "updated: \"\(today())\""
        ]

        let content = "---\n\(yamlLines.joined(separator: "\n"))\n---\n\n\(skill.body)"
        let fileURL = skillsURL.appending(component: "\(skill.id).md")
        try content.write(to: fileURL, atomically: true, encoding: .utf8)
        try updateSkillsIndex(skill, ownerAgentId: owner)
    }

    private func updateSkillsIndex(_ skill: Skill, ownerAgentId: String) throws {
        // v3.3: per-agent index file is `<agent>/Skills/agent-skills.md`.
        // The marker block in this file is auto-regenerated by
        // `scripts/vault_indexes.py`, so the manual append we used to do here
        // is now best-effort: if the marker block is present, the next /indexes
        // run will repopulate it from frontmatter, so we don't append anything.
        let indexURL = agentDirURL(for: ownerAgentId)
            .appending(component: "Skills")
            .appending(component: "agent-skills.md")
        guard fm.fileExists(atPath: indexURL.path) else { return }
        let content = (try? String(contentsOf: indexURL, encoding: .utf8)) ?? ""
        if content.contains("vault-query:start") {
            return  // marker block — Python regenerates on /indexes
        }
        if !content.contains("[[\(skill.id)]]") {
            let updated = content + "\n- [[\(skill.id)]] — \(skill.description)"
            try updated.write(to: indexURL, atomically: true, encoding: .utf8)
        }
    }

    func deleteSkill(id: String, ownerAgentId: String = "main") throws {
        guard !Skill.builtInIds.contains(id) else { return }
        let owner = ownerAgentId.isEmpty ? "main" : ownerAgentId
        let skillsURL = agentDirURL(for: owner)
            .appending(component: "Skills", directoryHint: .isDirectory)
        let fileURL = skillsURL.appending(component: "\(id).md")
        guard fm.fileExists(atPath: fileURL.path) else { return }
        try fm.trashItem(at: fileURL, resultingItemURL: nil)
        try removeFromSkillsIndex(id: id, ownerAgentId: owner)
    }

    // MARK: - Index helpers
    //
    // v3.1: there is no top-level ``Agents/Agents.md`` anymore — the vault's
    // shared ``CLAUDE.md`` holds agent wikilinks directly. Per-agent indexes
    // (Routines.md / Skills.md / …) are still auto-regenerated via marker
    // blocks handled by ``scripts/vault_indexes.py`` on the Python side.

    private func updateRoutinesIndex(_ routine: Routine, ownerAgentId: String) throws {
        // v3.3: index file is `<agent>/Routines/agent-routines.md`.
        // Marker blocks are auto-regenerated by `scripts/vault_indexes.py`.
        let indexURL = agentDirURL(for: ownerAgentId)
            .appending(component: "Routines")
            .appending(component: "agent-routines.md")
        guard fm.fileExists(atPath: indexURL.path) else { return }
        let content = (try? String(contentsOf: indexURL, encoding: .utf8)) ?? ""
        if content.contains("vault-query:start") { return }
        let link = "- [[\(routine.id)]] — \(routine.description)"
        if !content.contains("[[\(routine.id)]]") {
            let updated = content + "\n\(link)"
            try updated.write(to: indexURL, atomically: true, encoding: .utf8)
        }
    }

    private func removeFromRoutinesIndex(id: String, ownerAgentId: String) throws {
        let indexURL = agentDirURL(for: ownerAgentId)
            .appending(component: "Routines")
            .appending(component: "agent-routines.md")
        guard var content = try? String(contentsOf: indexURL, encoding: .utf8) else { return }
        if content.contains("vault-query:start") { return }
        let lines = content.components(separatedBy: "\n").filter { !$0.contains("[[\(id)]]") }
        content = lines.joined(separator: "\n")
        try content.write(to: indexURL, atomically: true, encoding: .utf8)
    }

    private func removeFromSkillsIndex(id: String, ownerAgentId: String) throws {
        let indexURL = agentDirURL(for: ownerAgentId)
            .appending(component: "Skills")
            .appending(component: "agent-skills.md")
        guard var content = try? String(contentsOf: indexURL, encoding: .utf8) else { return }
        if content.contains("vault-query:start") { return }
        let lines = content.components(separatedBy: "\n").filter { !$0.contains("[[\(id)]]") }
        content = lines.joined(separator: "\n")
        try content.write(to: indexURL, atomically: true, encoding: .utf8)
    }

    // MARK: - Reactions

    /// Path to the reaction secrets file (~/.claude-bot/reaction-secrets.json).
    /// Lives outside the vault so vault/ can be committed/synced safely.
    private var reactionSecretsURL: URL {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home.appending(component: ".claude-bot").appending(component: "reaction-secrets.json")
    }

    private var reactionStatsURL: URL {
        let home = FileManager.default.homeDirectoryForCurrentUser
        return home.appending(component: ".claude-bot").appending(component: "reaction-stats.json")
    }

    private func loadReactionStats() -> [String: [String: Any]] {
        guard let data = try? Data(contentsOf: reactionStatsURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return [:]
        }
        var result: [String: [String: Any]] = [:]
        for (key, value) in json {
            if let dict = value as? [String: Any] {
                result[key] = dict
            }
        }
        return result
    }

    private func loadReactionSecrets() -> [String: [String: String]] {
        guard let data = try? Data(contentsOf: reactionSecretsURL),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return [:]
        }
        var result: [String: [String: String]] = [:]
        for (key, value) in json {
            if let dict = value as? [String: Any] {
                var entry: [String: String] = [:]
                for (k, v) in dict {
                    if let s = v as? String { entry[k] = s }
                }
                result[key] = entry
            }
        }
        return result
    }

    private func saveReactionSecrets(_ secrets: [String: [String: String]]) throws {
        let dir = reactionSecretsURL.deletingLastPathComponent()
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)
        // Filter empty entries so we don't write {"id":{}}
        let cleaned = secrets.mapValues { entry -> [String: String] in
            entry.filter { !$0.value.isEmpty }
        }.filter { !$0.value.isEmpty }
        let data = try JSONSerialization.data(withJSONObject: cleaned, options: [.prettyPrinted, .sortedKeys])
        try data.write(to: reactionSecretsURL, options: .atomic)
        // Restrict permissions to 600
        try? fm.setAttributes([.posixPermissions: 0o600], ofItemAtPath: reactionSecretsURL.path)
    }

    /// v3.1: reactions live under `<agent>/Reactions/`. Walk every agent folder.
    func loadReactions() throws -> [Reaction] {
        let secrets = loadReactionSecrets()
        let stats = loadReactionStats()
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let isoNoFrac = ISO8601DateFormatter()
        isoNoFrac.formatOptions = [.withInternetDateTime]
        var reactions: [Reaction] = []

        for agentId in iterAgentIds() {
            let agentDir = agentDirURL(for: agentId)
            let dir = agentDir.appending(component: "Reactions", directoryHint: .isDirectory)
            guard fm.fileExists(atPath: dir.path) else { continue }

            let entries = (try? fm.contentsOfDirectory(atPath: dir.path)) ?? []
            for entry in entries {
                guard entry.hasSuffix(".md") && !Self.subIndexFilenames.contains(entry) else { continue }
                let fileURL = dir.appending(component: entry)
                guard let content = try? String(contentsOf: fileURL, encoding: .utf8) else { continue }
                let (fm_data, body) = FrontmatterParser.parse(content)

                // Only load files that are actually reactions (guard against stray md files)
                guard (fm_data["type"] as? String) == "reaction" else { continue }

                let name = String(entry.dropLast(3))
                let authDict = fm_data["auth"] as? [String: Any] ?? [:]
                let actionDict = fm_data["action"] as? [String: Any] ?? [:]
                let modeStr = (authDict["mode"] as? String) ?? "token"
                let mode = Reaction.AuthMode(rawValue: modeStr) ?? .token
                let mySecrets = secrets[name] ?? [:]
                let myStats = stats[name] ?? [:]

                // Parse last_fired_at — tolerate both with and without fractional seconds
                var lastFired: Date? = nil
                if let s = myStats["last_fired_at"] as? String {
                    lastFired = iso.date(from: s) ?? isoNoFrac.date(from: s)
                }

                let cleanBody = body
                    .replacingOccurrences(of: "[[Reactions]]\n", with: "")
                    .replacingOccurrences(of: "[[Reactions]]", with: "")
                    .trimmingCharacters(in: .whitespacesAndNewlines)

                var reaction = Reaction(
                    id: name,
                    title: fm_data["title"] as? String ?? name,
                    description: fm_data["description"] as? String ?? "",
                    enabled: fm_data["enabled"] as? Bool ?? true,
                    created: fm_data["created"] as? String ?? today(),
                    updated: fm_data["updated"] as? String ?? today(),
                    tags: fm_data["tags"] as? [String] ?? ["reaction"],
                    authMode: mode,
                    hmacHeader: (authDict["hmac_header"] as? String) ?? "X-Signature",
                    hmacAlgo: (authDict["hmac_algo"] as? String) ?? "sha256",
                    routineName: (actionDict["routine"] as? String).flatMap { $0.isEmpty ? nil : $0 },
                    forward: actionDict["forward"] as? Bool ?? false,
                    forwardTemplate: (actionDict["forward_template"] as? String) ?? "{{raw}}",
                    agentId: (actionDict["agent"] as? String).flatMap { $0.isEmpty ? nil : $0 },
                    body: cleanBody,
                    token: mySecrets["token"],
                    hmacSecret: mySecrets["hmac_secret"],
                    lastFiredAt: lastFired,
                    fireCount: (myStats["fire_count"] as? Int) ?? 0,
                    lastStatus: myStats["last_status"] as? String,
                    lastForwarded: (myStats["last_forwarded"] as? Bool) ?? false,
                    lastRoutineEnqueued: (myStats["last_routine_enqueued"] as? Bool) ?? false
                )
                reaction.ownerAgentId = agentId
                reactions.append(reaction)
            }
        }
        return reactions.sorted { $0.title < $1.title }
    }

    func saveReaction(_ reaction: Reaction) throws {
        let owner = reaction.ownerAgentId.isEmpty ? "main" : reaction.ownerAgentId
        let dir = agentDirURL(for: owner)
            .appending(component: "Reactions", directoryHint: .isDirectory)
        try fm.createDirectory(at: dir, withIntermediateDirectories: true)

        var authDict: [String: Any] = ["mode": reaction.authMode.rawValue]
        if reaction.authMode == .hmac {
            authDict["hmac_header"] = reaction.hmacHeader
            authDict["hmac_algo"] = reaction.hmacAlgo
        }

        var actionDict: [String: Any] = ["forward": reaction.forward]
        if let r = reaction.routineName, !r.isEmpty { actionDict["routine"] = r }
        if reaction.forward { actionDict["forward_template"] = reaction.forwardTemplate }
        if let a = reaction.agentId, !a.isEmpty { actionDict["agent"] = a }

        let frontmatter: [String: Any] = [
            "title": reaction.title,
            "description": reaction.description,
            "type": "reaction",
            "created": reaction.created,
            "updated": today(),
            "tags": reaction.tags.isEmpty ? ["reaction"] : reaction.tags,
            "enabled": reaction.enabled,
            "auth": authDict,
            "action": actionDict
        ]
        let orderedKeys = ["title", "description", "type", "created", "updated", "tags", "enabled", "auth", "action"]
        // v3.3 parent → child convention: leaf files (reactions) do NOT carry
        // a `[[Reactions]]` parent wikilink — agent-reactions.md points DOWN
        // to them via its marker block.
        let body = "\n\(reaction.body)\n"
        let content = FrontmatterParser.serialize(frontmatter, orderedKeys: orderedKeys, body: body)
        let fileURL = dir.appending(component: "\(reaction.id).md")
        try content.write(to: fileURL, atomically: true, encoding: .utf8)

        // Save secrets separately (only token/hmac_secret that are non-empty)
        var secrets = loadReactionSecrets()
        var entry: [String: String] = [:]
        if let t = reaction.token, !t.isEmpty { entry["token"] = t }
        if let h = reaction.hmacSecret, !h.isEmpty { entry["hmac_secret"] = h }
        if entry.isEmpty {
            secrets.removeValue(forKey: reaction.id)
        } else {
            secrets[reaction.id] = entry
        }
        try saveReactionSecrets(secrets)

        // Update index
        try updateReactionsIndex(reaction, ownerAgentId: owner)
    }

    func deleteReaction(id: String, ownerAgentId: String = "main") throws {
        let owner = ownerAgentId.isEmpty ? "main" : ownerAgentId
        let dir = agentDirURL(for: owner)
            .appending(component: "Reactions", directoryHint: .isDirectory)
        let fileURL = dir.appending(component: "\(id).md")
        if fm.fileExists(atPath: fileURL.path) {
            try fm.trashItem(at: fileURL, resultingItemURL: nil)
        }
        var secrets = loadReactionSecrets()
        if secrets.removeValue(forKey: id) != nil {
            try saveReactionSecrets(secrets)
        }
        try removeFromReactionsIndex(id: id, ownerAgentId: owner)
    }

    /// Generate a fresh random token for a reaction. Prefix `rxn_` + 32 hex chars.
    nonisolated func generateReactionToken() -> String {
        var bytes = [UInt8](repeating: 0, count: 16)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        let hex = bytes.map { String(format: "%02x", $0) }.joined()
        return "rxn_\(hex)"
    }

    /// Generate a fresh HMAC secret (256-bit hex string).
    nonisolated func generateHmacSecret() -> String {
        var bytes = [UInt8](repeating: 0, count: 32)
        _ = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        return bytes.map { String(format: "%02x", $0) }.joined()
    }

    private func updateReactionsIndex(_ reaction: Reaction, ownerAgentId: String) throws {
        let indexURL = agentDirURL(for: ownerAgentId)
            .appending(component: "Reactions")
            .appending(component: "agent-reactions.md")
        guard fm.fileExists(atPath: indexURL.path) else { return }
        let content = (try? String(contentsOf: indexURL, encoding: .utf8)) ?? ""
        if content.contains("vault-query:start") { return }
        if !content.contains("[[\(reaction.id)]]") {
            let updated = content + "\n- [[\(reaction.id)]] — \(reaction.description)"
            try updated.write(to: indexURL, atomically: true, encoding: .utf8)
        }
    }

    private func removeFromReactionsIndex(id: String, ownerAgentId: String) throws {
        let indexURL = agentDirURL(for: ownerAgentId)
            .appending(component: "Reactions")
            .appending(component: "agent-reactions.md")
        guard var content = try? String(contentsOf: indexURL, encoding: .utf8) else { return }
        if content.contains("vault-query:start") { return }
        let lines = content.components(separatedBy: "\n").filter { !$0.contains("[[\(id)]]") }
        content = lines.joined(separator: "\n")
        try content.write(to: indexURL, atomically: true, encoding: .utf8)
    }

    // MARK: - Helpers
    //
    // Note (v3.5): the Main agent is no longer a synthetic placeholder loaded
    // from the project-root `CLAUDE.md`. It is a first-class agent that lives
    // at `vault/main/` with its own `agent-main.md` hub file and `CLAUDE.md`
    // personality file, and is loaded by `loadAgents()` like every other
    // agent. The top-level `vault/CLAUDE.md` holds universal vault rules
    // (frontmatter, graph, linking) and is NOT specific to any agent.

    /// v3.1 flat per-agent layout: every agent lives directly under the vault root.
    /// ``vault/<id>/`` — no more ``Agents/`` wrapper.
    private func agentDirURL(for id: String) -> URL {
        vaultURL.appending(component: id, directoryHint: .isDirectory)
    }

    /// Names at the vault root that are NEVER agents. Any other top-level
    /// directory that contains ``agent-<dirname>.md`` is treated as an agent.
    private static let reservedVaultNames: Set<String> = [
        "README.md", "CLAUDE.md", "Tooling.md", ".env",
        ".graphs", ".obsidian", ".claude", "Images", "__pycache__",
        "Agents",  // legacy wrapper — treat as reserved during mid-migration
    ]

    /// Iterate every agent directory under the vault root. An agent is any
    /// top-level directory whose hub file ``agent-<dirname>.md`` exists.
    private func iterAgentIds() -> [String] {
        guard let entries = try? fm.contentsOfDirectory(atPath: vaultURL.path) else { return [] }
        var ids: [String] = []
        for entry in entries.sorted() {
            if entry.hasPrefix(".") { continue }
            if Self.reservedVaultNames.contains(entry) { continue }
            let entryURL = vaultURL.appending(component: entry, directoryHint: .isDirectory)
            var isDir: ObjCBool = false
            guard fm.fileExists(atPath: entryURL.path, isDirectory: &isDir), isDir.boolValue else { continue }
            let hub = entryURL.appending(component: "agent-\(entry).md")
            let legacyHub = entryURL.appending(component: "agent-info.md")
            if fm.fileExists(atPath: hub.path) || fm.fileExists(atPath: legacyHub.path) {
                ids.append(entry)
            }
        }
        return ids
    }

    private func today() -> String {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: Date())
    }
}
