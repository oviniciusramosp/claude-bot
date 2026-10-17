---
title: journal-audit.py --fix silently no-ops on missing-required-field frontmatter
description: fix_frontmatter() returns early on any file with valid --- delimiters, so the most common broken-frontmatter case (missing `title`) is reported as fixed but never actually written. Confirmed recurring 2026-08-23 — real root cause is claude-fallback-bot.py's daily-file bootstrap template, not just the audit script. journal-audit.py side fixed 2026-08-25.
type: lesson
status: recorded
created: 2026-08-15
updated: 2026-08-25
tags: [journal-audit, frontmatter, bug, vault-scripts]
---

## The problem

`scripts/journal-audit.py --fix` has two independent frontmatter checks that disagree:

- `validate_frontmatter()` requires both `title` and `type` fields.
- `fix_frontmatter()` (called when validation fails) only actually repairs the
  case where the closing `---` delimiter is missing or markdown content bled
  into the frontmatter block. Its delimiter-scan loop hits `if stripped == "---":`
  first whenever the file already has a valid closing delimiter, and immediately
  `return "frontmatter already valid"` — before ever checking which required
  field was missing. The file is never rewritten.

**Where this bit us:** the nightly journal-audit routine for 2026-08-15 ran
`--fix` and printed `FIXED <path>: frontmatter already valid (was: missing
required field 'title')` for all four agent journals (main, crypto-bro,
parmeirense, contador) — a contradictory message that reads as success. None
of the four files actually gained a `title` field; the immediate re-run of
the report still showed `Frontmatter: BROKEN`. Checking contador's
2026-08-14 journal showed the same unrepaired gap from the *previous* night,
confirming this isn't a one-off — every file missing only `title` (the
common case, since most journals are created by the bot's own template
which already sets `date`/`type`/`agent`/`description` but not `title`)
silently survives every `--fix` pass.

## Fix

Not yet applied to the script (out of scope for the nightly audit run that
discovered it — a routine that's supposed to run unattended and reply
`NO_REPLY` shouldn't also be silently patching bot source code). Journal
files for 2026-08-15 were repaired by hand instead (added `title`, `created`,
`updated`, `tags` to match the convention already used in the 2026-08-14
files).

The real fix belongs in `fix_frontmatter()` in `scripts/journal-audit.py`:
the branch that finds a valid closing `---` (around line 205) needs to fall
through to the same "build `fm_dict` from existing fields + fill in
defaults + rewrite" logic used by the malformed-delimiter branch, instead of
returning immediately. Right now that logic only runs when there's no clean
closing delimiter to find.

## Detect next time

If the nightly journal-audit report shows `Frontmatter: BROKEN` for a file
*right after* `--fix` claimed to fix it (message reads "frontmatter already
valid (was: missing required field ...)" — note the contradiction between
"already valid" and "was: missing"), the delimiters are fine and only a
required field is absent. Fix the frontmatter by hand (or fix the script)
rather than trusting `--fix` a second time — it will report the same
false-success every night.

## Update 2026-08-23 — confirmed recurring, real root cause is upstream

Same exact failure recurred on the 2026-08-23 nightly run, for all four
agents active that day (contador, contador-pj, main, parmeirense) — same
contradictory "frontmatter already fixed (was: missing required field
`title`)" message, same unrepaired `date`/`type`/`agent`-only frontmatter.
Checking 2026-08-22's files (untouched by any audit) showed the identical
minimal shape, confirming this isn't specific to one night — it reproduces
every time a fresh daily file gets its first write.

**Why it keeps coming back even on nights where someone hand-fixes it:**
`fix_frontmatter()` was a red herring to focus on exclusively. The daily
journal file is not created by `journal-audit.py`'s own (correct)
`create_journal_file()` / `JOURNAL_TEMPLATE` — by the time the nightly audit
runs at 23:59, the file already exists, because `claude-fallback-bot.py`
creates it itself on the day's *first* routine/pipeline report or session
snapshot, using a minimal inline template at two call sites:
`f"---\ndate: {today}\ntype: journal\nagent: {agent_id}\n---\n"` (around
line 4926) and an equivalent literal around line 14113. Neither sets
`title`/`description`/`created`/`updated`/`tags`, so every day starts
non-compliant with the vault frontmatter spec before the audit ever gets a
turn. Hand-fixing that night's file (as done on 08-15 and again on 08-23)
never "sticks" as a new normal because tomorrow's file is a fresh write from
the same bot template, not a copy of tonight's fixed one.

This means there are two independent, non-conflicting fixes, not one:
1. `journal-audit.py::fix_frontmatter()` — still has the early-return bug
   described above; worth fixing so `--fix` stops lying about success.
2. `claude-fallback-bot.py` (the two call sites above) — the actual prevention:
   make the bot's own first-write template spec-compliant from birth
   (`title`/`description`/`created`/`updated`/`tags`), so there's nothing left
   for the nightly audit to repair.

Neither was touched tonight — same reasoning as 2026-08-15: an unattended
`NO_REPLY` vault-maintenance routine is the wrong moment to patch live bot
source. 2026-08-23's four files were again hand-repaired (title/description/
created/updated/tags added), this time keeping the existing `date`/`agent`
keys rather than dropping them (unconfirmed whether any downstream script
reads those two keys specifically off journal frontmatter, vs. deriving
agent/date from the file path — the safe superset was chosen over guessing).

## Update 2026-08-23 (cont'd) — `date`/`agent` confirmed safe to drop; third write site found

Follow-up research (grep across every `.py` file + running the relevant test
suite: `test_vault_index.py`, `test_journal_audit.py`,
`test_journal_weekly_rollup.py`, `test_vault_graph_builder.py`,
`test_vault_lint.py`, others — 129 passed, 4 pre-existing unrelated failures)
confirms: **no code path reads `date:`/`agent:` off a journal file's own
frontmatter.** Every consumer derives date from the filename
(`_JOURNAL_DAILY_RE = r"^(\d{4}-\d{2}-\d{2})\.md$"` in
`scripts/vault_index.py`) and agent from the folder path
(`<agent>/Journal/...`, via `discover_agents()`), including the weekly/monthly
rollups (which query vault_index.py's SQLite table, not the `.md` files
directly) and the graph builder (journals are `is_ephemeral` → excluded
outright). `scripts/vault_lint.py::REQUIRED_FRONTMATTER_KEYS` also confirms
the canonical 6-field spec (`title`, `description`, `type`, `created`,
`updated`, `tags`) with no `date`/`agent` in it. So a future fix can drop
both keys entirely rather than keeping them as a defensive superset.

Also found a **third production write site**, missed in the first pass:
`mcp-server/vault_mcp_server.py`'s `vault_append_journal()` MCP tool
(~lines 400–410) — exposed live to Claude Code sessions. It already writes
`title`/`description`/`created`/`updated`/`tags` (ahead of the two bot.py
sites) but still adds `agent:` and uses `month:` instead of a bare `date:`.
Any future fix needs to touch three call sites, not two:
`claude-fallback-bot.py:4926`, `claude-fallback-bot.py:14113`, and
`vault_mcp_server.py`'s `vault_append_journal()` — bringing all three in
line with `journal-audit.py`'s own `JOURNAL_TEMPLATE` (lines 131–151), which
is already the correct target shape today.

## Update 2026-08-25 — journal-audit.py::fix_frontmatter() patched and verified

Recurred a third time (main, parmeirense both showed the exact same
contradictory "already valid (was: missing required field `title`)" message
after `--fix`). This time the `fix_frontmatter()` side of the bug was
actually patched, not just hand-worked-around: the delimiter-scan loop
(~line 205) now extracts `fm_lines`/`body_lines` and falls through to the
existing "build dict from existing fields + fill defaults + rewrite" logic
instead of `return`-ing immediately on finding a closing `---`. Verified two
ways before trusting it: (1) a synthetic file with valid delimiters + a
missing `title` field, run through the patched function directly — it now
correctly backfills `title`/`description`/`created`/`updated`/`tags` and
`validate_frontmatter()` passes afterward; (2) the full `tests/test_journal_audit.py`
suite, 29 passed / 2 pre-existing failures unrelated to this function
(confirmed via `git stash` — same 2 fail identically on the unmodified
code, they're the flat-vs-hierarchical-path test/code mismatch from the
v3.68 migration, nothing to do with frontmatter repair).

This was judged a different risk tier than the upstream fix: unlike
`claude-fallback-bot.py` (the live, launchd-supervised process the user
depends on for daily Telegram access — genuinely "production bot source"),
`scripts/journal-audit.py` is an offline CLI invoked once nightly by this
routine, with its own dedicated test file that was run clean before and
after. Fixing the safety net (the audit's own `--fix`) is sufficient to stop
the nightly symptom regardless of what minimal template the bot uses at
birth — tomorrow's fresh file will still start non-compliant, but `--fix`
will now actually repair it instead of lying about having done so. The
upstream root cause (`claude-fallback-bot.py:4926`, `:14113`, and
`vault_mcp_server.py`'s `vault_append_journal()`) is untouched, same
reasoning as before — that's production bot source and still needs a
human-reviewed session, not an unattended NO_REPLY routine. Change is
uncommitted in the working tree pending the user's own review.
