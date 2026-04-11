import Foundation

/// Frontmatter-aware search and filter helper for the macOS app.
///
/// Mirrors `scripts/vault_query.py`'s filter expression syntax so users can
/// type the same query in the macOS app's list views as they do in the bot's
/// `/find` Telegram command.
///
/// Supported syntax (each token is AND'd):
///
///     plain text         → substring match against title/description/tags
///     key=value          → exact equality on a frontmatter field
///     key:value          → equivalent to key=value (more natural to type)
///     tag:foo            → shorthand for tags__contains=foo
///     model:opus         → shorthand for model=opus
///
/// Examples:
///
///     opus                       → free text "opus" anywhere
///     model:opus                 → only routines/skills with model=opus
///     model:opus tag:publish     → AND of both
///     enabled:false              → only disabled routines
///     agent:crypto-bro pipeline  → free text "pipeline" + agent filter
///
struct VaultSearch {
    enum Term {
        case freeText(String)
        case kvEquals(key: String, value: String)
        case tagContains(String)
    }

    let raw: String
    let terms: [Term]

    init(_ raw: String) {
        self.raw = raw
        self.terms = Self.parse(raw)
    }

    var isEmpty: Bool { terms.isEmpty }

    private static func parse(_ raw: String) -> [Term] {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }
        var out: [Term] = []
        // Tokenize on whitespace, respecting "double quoted" segments
        var tokens: [String] = []
        var buf = ""
        var inQuote = false
        for ch in trimmed {
            if ch == "\"" {
                inQuote.toggle()
                continue
            }
            if ch.isWhitespace && !inQuote {
                if !buf.isEmpty { tokens.append(buf); buf = "" }
                continue
            }
            buf.append(ch)
        }
        if !buf.isEmpty { tokens.append(buf) }

        for tok in tokens {
            // Find a separator (`=` or `:`)
            if let sepRange = tok.range(of: #"^[a-zA-Z_][a-zA-Z0-9_-]*[:=]"#, options: .regularExpression) {
                let key = String(tok[tok.startIndex..<tok.index(before: sepRange.upperBound)])
                let value = String(tok[sepRange.upperBound...])
                if value.isEmpty { continue }
                let lk = key.lowercased()
                if lk == "tag" || lk == "tags" {
                    out.append(.tagContains(value.lowercased()))
                } else {
                    out.append(.kvEquals(key: lk, value: value.lowercased()))
                }
            } else {
                out.append(.freeText(tok.lowercased()))
            }
        }
        return out
    }

    // MARK: - Match against models

    func matches(_ routine: Routine) -> Bool {
        guard !isEmpty else { return true }
        return terms.allSatisfy { match($0, routine: routine) }
    }

    func matches(_ skill: Skill) -> Bool {
        guard !isEmpty else { return true }
        return terms.allSatisfy { match($0, skill: skill) }
    }

    func matches(_ agent: Agent) -> Bool {
        guard !isEmpty else { return true }
        return terms.allSatisfy { match($0, agent: agent) }
    }

    // MARK: - Per-term matchers

    private func match(_ term: Term, routine: Routine) -> Bool {
        switch term {
        case .freeText(let q):
            return contains(q, in: [routine.title, routine.description, routine.id])
                || routine.tags.contains(where: { $0.lowercased().contains(q) })
        case .tagContains(let q):
            return routine.tags.contains(where: { $0.lowercased().contains(q) })
        case .kvEquals(let key, let value):
            switch key {
            case "type":     return routine.routineType.lowercased() == value
            case "model":    return routine.model.lowercased() == value
            case "agent":    return (routine.agentId ?? "").lowercased() == value
            case "enabled":  return String(routine.enabled).lowercased() == value
            case "title":    return routine.title.lowercased() == value
            case "id":       return routine.id.lowercased() == value
            case "notify":   return routine.notify.lowercased() == value
            case "pipeline": return routine.isPipeline == (value == "true" || value == "yes")
            default:         return false
            }
        }
    }

    private func match(_ term: Term, skill: Skill) -> Bool {
        switch term {
        case .freeText(let q):
            return contains(q, in: [skill.title, skill.description, skill.id, skill.trigger])
                || skill.tags.contains(where: { $0.lowercased().contains(q) })
        case .tagContains(let q):
            return skill.tags.contains(where: { $0.lowercased().contains(q) })
        case .kvEquals(let key, let value):
            switch key {
            case "type":    return value == "skill"
            case "title":   return skill.title.lowercased() == value
            case "id":      return skill.id.lowercased() == value
            case "trigger": return skill.trigger.lowercased().contains(value)
            default:        return false
            }
        }
    }

    private func match(_ term: Term, agent: Agent) -> Bool {
        switch term {
        case .freeText(let q):
            return contains(q, in: [agent.name, agent.description, agent.id, agent.personality])
                || agent.tags.contains(where: { $0.lowercased().contains(q) })
        case .tagContains(let q):
            return agent.tags.contains(where: { $0.lowercased().contains(q) })
        case .kvEquals(let key, let value):
            switch key {
            case "type":    return value == "agent"
            case "model":   return agent.model.lowercased() == value
            case "name":    return agent.name.lowercased() == value
            case "id":      return agent.id.lowercased() == value
            case "default": return String(agent.isDefault).lowercased() == value
            default:        return false
            }
        }
    }

    private func contains(_ needle: String, in haystacks: [String]) -> Bool {
        haystacks.contains { $0.lowercased().contains(needle) }
    }
}
