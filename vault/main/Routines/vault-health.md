---
title: "Vault Health"
description: "Daily vault health check: broken wikilinks, missing frontmatter, orphan files, stale routines. Notifies only when issues are found."
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
effort: low
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

5. **Auto-fix broken wikilinks** (before reporting): for each broken wikilink issue, attempt to fix it automatically using the rules below. Then re-run the linter to get the final count for the report.

### Auto-fix rules for broken wikilinks

These are safe, mechanical fixes — apply them without asking:

| Broken link | Correct link | Condition |
|---|---|---|
| `[[Routines]]` | `[[agent-routines]]` | file is inside any `*/Routines/` folder |
| `[[Notes]]` | `[[agent-notes]]` | file is inside any `*/Notes/` folder |
| `[[Skills]]` | `[[agent-skills]]` | file is inside any `*/Skills/` folder |
| `[[Journal]]` | `[[agent-journal]]` | file is inside any `*/Journal/` folder |
| `[[Lessons]]` | `[[agent-lessons]]` | file is inside any `*/Lessons/` folder |

For each broken-wikilink issue returned by the linter:
1. Check if the broken link matches one of the patterns above and the file is in the expected folder.
2. If yes: read the file, replace the broken wikilink with the correct one, write back. Do NOT change any other content.
3. If no: leave it for the report — it's a non-trivial broken link that needs manual review.

After fixing, re-run the linter:

```bash
cd /Users/viniciusramos/claude-bot
python3 scripts/vault_lint.py --json
```

Use the fresh output for the final report. If all issues were auto-fixed and the new count is 0, respond `NO_REPLY`.

If fixes were applied, prepend a brief line to the Telegram message: `🔧 Auto-fixed N wikilink(s).`
