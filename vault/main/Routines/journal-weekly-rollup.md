---
title: "journal-weekly-rollup"
description: "Monday morning: produce a compact bullet-style summary of last week's journal for every agent — global routine that iterates iter_agent_ids() automatically. New agents are picked up with zero config per contract C7."
type: routine
schedule:
  times: ["05:00"]
  days: [1]
model: sonnet
context: minimal
enabled: true
tags: [routine, vault, journal, summary]
created: 2026-04-14
updated: 2026-04-14
---

Global routine — iterates every discovered agent via `iter_agent_ids()` (contract C1 / C7, mirroring `journal-audit`). For each agent that has at least one journal entry in the past 7 days, spawns a Sonnet subprocess scoped to that agent's folder and writes `vault/<agent>/Journal/weekly/YYYY-Www.md`. The driver also upserts the new rollup into the FTS index inline so the summary is searchable from the next session.

Runs Mondays at 05:00 so the summary covers the week that just finished and the output is ready before the user starts their day.

```bash
python3 scripts/journal-weekly-rollup.py
```

If stdout ends in `done — N agents, K files written, 0 errors`, respond with `NO_REPLY`. Otherwise, surface the stderr tail verbatim so the failure hits Telegram per the zero-silent-errors rule.
