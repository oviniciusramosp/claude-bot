---
title: "Vault Lint"
description: "Daily vault hygiene check. Runs scripts/vault_lint.py and notifies on Telegram only when issues are found. Otherwise stays silent (NO_REPLY)."
type: routine
created: 2026-04-11
updated: 2026-04-11
tags: [routine, maintenance, vault]
schedule:
  times: ["06:07"]
  days: ["*"]
model: haiku
enabled: true
context: minimal
---

Run the vault hygiene linter and report results.

1. Execute the linter from the project root:

```bash
cd /Users/viniciusramos/claude-bot
python3 scripts/vault_lint.py --json
```

2. Parse the JSON output. It has the shape:

```
{
  "files_scanned": <int>,
  "issues_count": <int>,
  "by_category": {"1": N, "2": N, ...},
  "issues": [{"category": int, "severity": "error|warning", "file": str, "message": str}, ...]
}
```

3. **If `issues_count == 0`, respond with exactly the string `NO_REPLY` and nothing else.** This tells the bot to skip the Telegram notification entirely.

4. **If `issues_count > 0`**, respond with a compact summary suitable for Telegram:

   - First line: `⚠️ Vault lint: N issue(s) across M file(s)`
   - For each category present, a section header with the category name and count
   - Inside each section, list issues as `❌` (error) or `⚠️` (warning) followed by `file: message`
   - Cap the total response to ~20 issues — if more, list the first 20 and add `…and N more` at the end

Category names:

- 1: Missing frontmatter
- 2: Broken wikilinks
- 3: Orphan files
- 4: Broken prompt_file
- 5: Stale routines
- 6: Step-file leakage
- 7: Index drift
- 8: Schedule sanity

Do not perform any fixes — only report. Fixing vault drift is a manual decision.
