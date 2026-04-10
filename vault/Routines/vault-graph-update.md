---
title: Vault Graph Update
description: Regenerates the vault's lightweight knowledge graph from frontmatter and wikilinks. No LLM cost.
type: routine
created: 2026-04-09
updated: 2026-04-09
tags: [routine, vault, graph, maintenance]
schedule:
  times: ["04:00"]
  days: ["*"]
model: haiku
enabled: true
context: minimal
---

[[Routines]]

Regenerate the vault knowledge graph by running the Python script below. This script extracts relationships from YAML frontmatter and wikilinks — no LLM, zero cost.

```bash
python3 ../scripts/vault-graph-builder.py
```

Runs relative to the vault directory (the bot's default cwd). The script auto-detects the vault path and writes `.graphs/graph.json`.

After execution:
1. Check whether `vault/.graphs/graph.json` was generated/updated
2. If there are errors, report the specific error
3. If successful, respond with `NO_REPLY`
