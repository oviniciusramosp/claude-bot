---
title: "Vault Rebuild"
description: "Nightly rebuild: knowledge graph, FTS full-text index, and MOC index files. Silent on success."
type: routine
schedule:
  times: ["04:00"]
  days: ["*"]
model: haiku
enabled: true
context: minimal
effort: low
tags: [routine, vault, maintenance]
created: 2026-04-14
updated: 2026-04-14
---

Three sequential maintenance steps. Run each in order:

**1 — Knowledge graph** (frontmatter + wikilinks → `vault/.graphs/graph.json`)

```bash
python3 ../../scripts/vault-graph-builder.py
```

**2 — FTS full-text index** (Journal, Lessons, Notes, weekly rollups → `~/.claude-bot/vault-index.sqlite`)

```bash
python3 ../../scripts/vault-index-update.py
```

**3 — MOC index files** (`Routines.md`, `Skills.md`, `Agents.md` marker blocks)

```bash
python3 ../../scripts/vault_indexes.py
```

If all three exit successfully, respond with exactly `NO_REPLY`. If any script exits non-zero, surface its stderr verbatim so the failure reaches Telegram.
