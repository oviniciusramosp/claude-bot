---
title: Routines that end in NO_REPLY never write an .activity/*.jsonl entry
description: _finalize_response() returns before the activity-log block when a routine's final text is exactly NO_REPLY, so journal-audit.py's agent-discovery (100% keyed off .activity/*.jsonl) silently never sees that agent, even though its journal Report block was written correctly.
type: lesson
status: recorded
created: 2026-08-15
updated: 2026-08-15
tags: [journal-audit, activity-log, routines, no-reply, vault-scripts, claude-fallback-bot]
---

## The problem

Two independent code paths record a routine's execution in `claude-fallback-bot.py`, and they are not gated by the same condition:

1. `_append_execution_report()` (line 4849) writes the `## Routine Report —
   <name> (HH:MM)` block into the agent's journal file. Called
   unconditionally from `_execute_routine_task()` on every completed/failed
   routine (call sites at lines 17810, 17837, 17849) — independent of what
   Claude's final response text was.
2. `_log_activity()` (line 4527) appends the `{"type": "routine", ...}`
   JSONL line to `Journal/.activity/YYYY-MM-DD.jsonl`. For routines this
   only happens inside `_finalize_response()` (block at lines 17650-17659,
   reached via the `elif routine_mode:` branch). But `_finalize_response()`
   **returns early at lines 17596-17598** whenever the final text is exactly
   `"NO_REPLY"` — before it ever reaches that activity-log block.

Net effect: any routine whose prompt tells Claude to respond `NO_REPLY` on
success (a pattern the vault itself encourages for silent/backend routines —
this very journal-audit routine's own instructions end with "Respond
NO_REPLY when done") gets its journal Report block written correctly, but
is invisible to `.activity/*.jsonl`.

`scripts/journal-audit.py`'s `discover_agents()` builds its entire per-agent
report loop from `.activity/*.jsonl` (`load_activity_log()` →
`discover_agents()`). An agent whose only activity on a given day is a
NO_REPLY-ending routine therefore never appears in the nightly audit report
at all — not flagged "journal missing," not flagged "broken frontmatter,"
just silently absent — so its frontmatter/description problems are never
surfaced.

Pipelines don't have this problem: `_notify_success`/`_notify_failure`
(pipeline harness) call `_log_activity` unconditionally (lines 10300, 10352),
with no dependency on final response text.

**Where this bit us:** `contador-pj` has a daily routine
`alertas-boletos-diario`. It has a daily journal file for every day from
2026-08-01 through 2026-08-15, but a matching `Journal/.activity/*.jsonl`
file for only 5 of those 15 days (08-01, 08-06, 08-07, 08-11, 08-13). Its
2026-08-15 journal contains a correctly-written `## Routine Report —
alertas-boletos-diario (09:00)` block despite no `.activity/2026-08-15.jsonl`
existing at all — so `contador-pj` never appeared anywhere in tonight's
`journal-audit.py` report, and its frontmatter (missing `title`/
`description`, and on 2026-08-14 missing the frontmatter block entirely) had
never been caught or fixed by any previous nightly run. The same gap shows
up inside `main`'s own 2026-08-15 journal: `meta-skill-improver` and
`vault-rebuild` (both NO_REPLY-ending routines) wrote Report blocks but are
absent from the audit's "Routine activity" list, unlike `vault-health` and
`update-check` (which produce non-NO_REPLY final text and log correctly).

## Fix

Not applied yet — out of scope for an unattended nightly routine to patch
its own bot source unreviewed. The real fix belongs in
`_finalize_response()`: move the routine activity-log block (17650-17659)
ahead of the NO_REPLY early-return at line 17597, or call `_log_activity`
directly from `_execute_routine_task`'s success/failure handlers alongside
`_append_execution_report` (17810/17837/17849) so routine logging is
unconditional, matching how the pipeline path already works.

Until that's fixed, `journal-audit.py`'s report cannot be trusted as a
complete list of agents needing attention for a given day. Cross-check with
something that doesn't depend on the activity log, e.g.:

```bash
for d in vault/*/; do
  a=$(basename "$d")
  f="$d/Journal/$(date +%Y-%m)/$(date +%Y-%m-%d).md"
  [ -f "$f" ] && echo "$a: has journal file for today"
done
```

Any agent listed here but missing from `journal-audit.py`'s report is a
blind spot — go check its frontmatter by hand.

## Detect next time

- Agent's journal has a `## Routine Report —` block for today, but the
  agent doesn't appear anywhere in `journal-audit.py`'s output → this is why.
- `diff <(ls vault/<agent>/Journal/<month>/*.md 2>/dev/null) <(ls vault/<agent>/Journal/.activity/*.jsonl 2>/dev/null | xargs -n1 basename -s .jsonl)` — daily files with no matching `.activity` date are the blind spot.
- Any routine whose prompt instructs a `NO_REPLY` reply on success is a
  candidate for this gap.
