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

You are running the nightly Journal sweep. Your task is to ensure that all sessions from today have a record in the Journal.

## Steps

1. Read `~/.claude-bot/sessions.json` to get all sessions.

2. Determine today's date in `YYYY-MM-DD` format.

3. Filter sessions where:
   - `name` starts with today's date (e.g., `2026-04-09-`)
   - `message_count > 0`
   - `session_id` is not null

4. For each filtered session, parse its name directly — the format is `YYYY-MM-DD-HH-MM-{agent}-{n}`:
   - **Date** → first 10 characters (`YYYY-MM-DD`)
   - **Time** → characters 11–15 (`HH:MM`, replacing the `-` separator: `HH-MM` → `HH:MM`)
   - **Agent** → the segment between position 16 and the last `-{n}` (e.g., `main`, `researcher`)

5. For each session:
   - If agent is `main` → journal path: `vault/Journal/YYYY-MM-DD.md`
   - Otherwise → journal path: `vault/Agents/{agent}/Journal/YYYY-MM-DD.md`
   - Check whether the journal already contains an entry for this session (search for the session name in the file content)
   - If there is NO entry yet:
     - Run: `claude --print --session-id <session_id> -p "Briefly summarize this conversation in 3-5 bullets: topics discussed, decisions made, actions taken. Be concise."`
     - Append to the correct journal using the time parsed from the session name:

```markdown
## HH:MM — {session-name}

- bullet 1
- bullet 2
- ...

---
```

6. If the journal file does not exist, create it with YAML frontmatter before appending:

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

7. At the end, record a sweep entry in the main journal (`vault/Journal/YYYY-MM-DD.md`):

```markdown
## 23:45 — Journal Sweep

- Sessions checked: N
- Sessions consolidated: N (list names)
- Sessions already recorded: N

---
```

Respond NO_REPLY when done.
