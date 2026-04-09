---
title: Journal Sweep
description: Nightly sweep that consolidates the day's sessions that were not recorded in the Journal.
type: routine
created: 2026-04-08
updated: 2026-04-09
tags: [routine, journal, maintenance, daily]
schedule:
  days: ["*"]
  times: [23:45]
model: sonnet
enabled: true
---

[[Routines]]

You are running the nightly Journal sweep. Your task is to ensure that all sessions from the day have a record in the Journal.

## Steps

1. Read the file `~/.claude-bot/sessions.json` to see all sessions
2. Identify sessions with `message_count > 0` and `session_id` != null (sessions that had activity)
3. For each identified session:
   - Determine the correct Journal: if the session has an `agent` field, use `vault/Agents/{agent}/Journal/YYYY-MM-DD.md`; otherwise, use `vault/Journal/YYYY-MM-DD.md`
   - Check whether the day's Journal already exists and already has an entry for that session (search for the session name in the content)
   - If there is NO entry, use the bash command: `claude --print --session-id <session_id> -p "Briefly summarize this conversation in 3-5 bullets: topics discussed, decisions made, actions taken. Be concise."` to obtain a summary
   - Append the summary to the correct Journal using the standard format:

```markdown
## HH:MM — Automatic consolidation: {session-name}

- bullet 1
- bullet 2
- ...

---
```

4. If the day's Journal file does not exist, create it with YAML frontmatter:

```yaml
---
title: "Journal YYYY-MM-DD"
description: Daily log for YYYY-MM-DD.
type: journal
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [journal]
---

[[Journal]]
```

For agent journals, use `[[{agent-id}/Journal|Journal]]` instead of `[[Journal]]` and add the agent's tag.

5. At the end, record a sweep entry in the main Journal (vault/Journal/YYYY-MM-DD.md):

```markdown
## 23:45 — Journal Sweep

- Sessions checked: N
- Sessions consolidated: N (list names)
- Sessions already recorded: N

---
```

Respond NO_REPLY when done.
