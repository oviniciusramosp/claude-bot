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
            let rawClaude = (try? String(contentsOf: claudeMdURL, encoding: .utf8)) ?? ""
            let sections = Agent.parseCLAUDEmd(rawClaude)

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
        if !agent.chatId.isEmpty { frontmatter["chat_id"] = agent.chatId }
        if !agent.threadId.isEmpty { frontmatter["thread_id"] = Int(agent.threadId) ?? agent.threadId as Any }

        let orderedKeys = ["title", "description", "type", "created", "updated", "tags",
                           "name", "personality", "model", "icon", "default", "chat_id", "thread_id"]
        let agentMdContent = FrontmatterParser.serialize(frontmatter, orderedKeys: orderedKeys, body: "\n[[Agents]]\n")
        try agentMdContent.write(to: agentURL.appending(component: "agent.md"), atomically: true, encoding: .utf8)

        // CLAUDE.md — structured sections, no frontmatter
        try agent.toCLAUDEmd().write(to: agentURL.appending(component: "CLAUDE.md"), atomically: true, encoding: .utf8)

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

    func loadReactions() throws -> [Reaction] {
        let dir = vaultURL.appending(component: "Reactions", directoryHint: .isDirectory)
        guard fm.fileExists(atPath: dir.path) else { return [] }

        let entries = try fm.contentsOfDirectory(atPath: dir.path)
        let secrets = loadReactionSecrets()
        let stats = loadReactionStats()
        let iso = ISO8601DateFormatter()
        iso.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let isoNoFrac = ISO8601DateFormatter()
        isoNoFrac.formatOptions = [.withInternetDateTime]
        var reactions: [Reaction] = []

        for entry in entries {
            guard entry.hasSuffix(".md") && entry != "Reactions.md" else { continue }
            let fileURL = dir.appending(component: entry)
            let content = try String(contentsOf: fileURL, encoding: .utf8)
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

            let reaction = Reaction(
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
            reactions.append(reaction)
        }
        return reactions.sorted { $0.title < $1.title }
    }

    func saveReaction(_ reaction: Reaction) throws {
        let dir = vaultURL.appending(component: "Reactions", directoryHint: .isDirectory)
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
        let body = "\n[[Reactions]]\n\n\(reaction.body)\n"
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
        try updateReactionsIndex(reaction)
    }

    func deleteReaction(id: String) throws {
        let dir = vaultURL.appending(component: "Reactions", directoryHint: .isDirectory)
        let fileURL = dir.appending(component: "\(id).md")
        if fm.fileExists(atPath: fileURL.path) {
            try fm.trashItem(at: fileURL, resultingItemURL: nil)
        }
        var secrets = loadReactionSecrets()
        if secrets.removeValue(forKey: id) != nil {
            try saveReactionSecrets(secrets)
        }
        try removeFromReactionsIndex(id: id)
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

    private func updateReactionsIndex(_ reaction: Reaction) throws {
        let indexURL = vaultURL.appending(component: "Reactions").appending(component: "Reactions.md")
        var content = (try? String(contentsOf: indexURL, encoding: .utf8)) ?? ""
        if !content.contains("[[\(reaction.id)]]") {
            content += "\n- [[\(reaction.id)]] — \(reaction.description)"
            try content.write(to: indexURL, atomically: true, encoding: .utf8)
        }
    }

    private func removeFromReactionsIndex(id: String) throws {
        let indexURL = vaultURL.appending(component: "Reactions").appending(component: "Reactions.md")
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
        let raw = (try? String(contentsOf: projectCLAUDEURL, encoding: .utf8)) ?? ""
        return Agent(
            id: "main",
            name: "Main",
            icon: "🤖",
            description: "Default bot — no specific agent active",
            personality: "",
            model: "sonnet",
            tags: [],
            isDefault: true,
            source: nil,
            sourceId: nil,
            created: "",
            updated: "",
            otherInstructions: raw  // Main uses raw CLAUDE.md, not structured sections
        )
    }

    func saveMainAgent(rawContent: String) throws {
        try rawContent.write(to: projectCLAUDEURL, atomically: true, encoding: .utf8)
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
