---
title: "vault-index-update"
description: "Rebuild the FTS5 full-text index at ~/.claude-bot/vault-index.sqlite so Active Memory v2 and SessionStart auto-recall can query journals, lessons, notes and weekly rollups by body content."
type: routine
schedule:
  times: ["04:05"]
model: sonnet
context: minimal
enabled: true
tags: [routine, vault, index]
created: 2026-04-14
updated: 2026-04-14
---

Run the stdlib rebuild driver. It walks every agent discovered via `iter_agent_ids()` (contract C1 — no hardcoded list), indexes Journal sections, Lessons, Notes and weekly rollups, and also ingests legacy `vault/Journal/*.md` under `agent=main`. The script fails loud (non-zero exit + stderr trace) so any error surfaces on Telegram per the zero-silent-errors rule.

Scheduled 5 minutes after `vault-graph-update` (04:00) so the two full-vault walkers never race for disk.

```bash
python3 scripts/vault-index-update.py
```

If the output line is `vault-index-update: N rows, K agents (...), Tms`, respond with `NO_REPLY` so the routine stays silent on success. If the script exited non-zero, surface the stderr tail verbatim so we notice.
