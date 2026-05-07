---
title: journal-monthly-rollup
description: "First-of-month: produce a rich monthly summary (themes, highlights, decisions, lessons, carry-forward) for every agent — frontmatter description is the primary signal LLMs use when scanning agent-journal.md to pick which months to open. Iterates iter_agent_ids() automatically per contract C7."
type: routine
created: 2026-05-07
updated: 2026-05-07
tags: [routine, vault, journal, summary, monthly]
schedule:
  monthdays: [1]
  times: [05:30]
model: sonnet
enabled: true
context: minimal
---

Global routine — iterates every discovered agent via `iter_agent_ids()` (contract C1 / C7, mirroring `journal-audit` and `journal-weekly-rollup`). For each agent that had at least one journal entry in the previous month, spawns a Sonnet subprocess and writes `vault/<agent>/Journal/<YYYY-MM>/<YYYY-MM>.md`. The driver also upserts the new rollup into the FTS index inline so the summary is searchable from the next session.

Runs on the 1st of each month at 05:30 — staggered 30 min after `journal-weekly-rollup`'s Monday slot to avoid disk contention. The rollup covers the **previous** month, so the file lands once it's complete.

The monthly file is the **top of the in-month memory hierarchy** (`agent-journal.md → YYYY-MM.md → YYYY-Www.md → YYYY-MM-DD.md`). Its frontmatter `description` is the keyword-rich signal an LLM uses when scanning the hub to decide which months are worth opening — keep it dense, specific, and concrete.

```bash
python3 scripts/journal-monthly-rollup.py
```

If stdout ends in `done — N agents, K files written, 0 errors`, respond with `NO_REPLY`. Otherwise, surface the stderr tail verbatim so the failure hits Telegram per the zero-silent-errors rule.
