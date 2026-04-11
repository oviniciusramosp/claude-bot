---
title: "Vault Indexes Update"
description: "Auto-regenerates vault index marker blocks (Routines.md, Skills.md, Agents.md, etc.) from frontmatter via scripts/vault_indexes.py. Stays silent unless something changed."
type: routine
created: 2026-04-11
updated: 2026-04-11
tags: [routine, maintenance, vault]
schedule:
  times: ["04:13"]
  days: ["*"]
model: haiku
enabled: true
context: minimal
---

[[Routines]]

Run the vault index regenerator and report only when files actually changed.

1. Execute the regenerator from the project root:

```bash
cd /Users/viniciusramos/claude-bot
python3 scripts/vault_indexes.py
```

2. Read the output:

   - If it ends with `All N marker files already up to date.` → respond with exactly `NO_REPLY` and nothing else.
   - If it lists `Updated N of M marker file(s):` followed by file names → respond with a compact summary like:

     ```
     📚 Vault indexes updated
     - Routines/Routines.md
     - Skills/Skills.md
     ```

3. Do not perform any other actions. Do not lint, do not commit. Index regeneration is the entire job.
