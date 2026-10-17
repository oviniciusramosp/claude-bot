---
title: Auto-compact session snapshots can land in the wrong agent's journal
description: _snapshot_session_to_journal() resolves its write path via self._get_journal_path() → self._get_session(), ignoring the session object already passed in as a parameter — so background auto-compacts for other agents' sessions get appended to whichever session self._get_session() falls back to.
type: lesson
status: recorded
created: 2026-08-21
updated: 2026-10-14
tags: [journal-audit, isolamento-total, bug, claude-fallback-bot, session-management]
---

## The problem

`_snapshot_session_to_journal(self, session: Session)` (claude-fallback-bot.py
~13432) is called from the auto-compact background thread to write a `##
Session Snapshot` block before `/compact` runs. It receives the correct
`session` object — proven by the fact the block's own header text,
`_Agent: {session.agent or 'main'} | Session: {session.name} | Turns: ...`,
is always accurate. But the *file path* it writes to comes from:

```python
journal_path = Path(self._get_journal_path())   # line 13440 — no args!
```

`_get_journal_path()` (line 14082) doesn't take a session parameter at all —
it re-derives "the current session" itself via `self._get_session()`, which
resolves `self._ctx.session_name` if a live request context is set, and
otherwise falls back to `self.sessions.active_session`, a single **bot-wide**
pointer. Auto-compact runs from a background thread after the triggering
request's context may already be gone, so for any session that isn't
whatever `active_session` currently points to, the snapshot's *content* is
correctly labeled for session X but gets appended to session Y's (or
whichever agent `active_session` was pinned to) journal file instead.

Contrast with `_append_journal_entry(self, agent: Optional[str], ...)` (line
14090), which takes `agent` explicitly and uses it directly for
`get_agent_journal_dir(agent, ...)` / `journal_daily_path(agent, today)` —
the correct pattern, already present elsewhere in the same file.

**Where this bit us:** `contador-pj/Journal/2026-08/2026-08-21.md` contains
correctly-written Session Snapshot blocks tagged `_Agent: crypto-bro`,
`_Agent: parmeirense`, and `_Agent: contador` alongside contador-pj's own.
Each of those three also has its own correctly-placed, correctly-formatted
entry in *its own* agent's journal for the same underlying session (verified
for crypto-bro's defiverso-daily-scout-v2 disable, parmeirense's
vertical-cover-image fix, and contador's Vivo Internet bill) — so no data
was lost, but every one of those sessions' auto-compact snapshot got
**duplicated** into contador-pj's file, violating isolamento total. Scanning
`_Agent:` tags across all 9 agents' journals for 2026-08-10 through
2026-08-21 turned up this pattern *only* in contador-pj (present on at least
08-11, 08-12, 08-13, 08-14, 08-17, 08-18, 08-21) — every other agent's
journal only ever shows its own name. `self.sessions.active_session` was
apparently pinned to contador-pj on every occasion this fired.

## Fix

Not applied — out of scope for an unattended nightly routine to patch bot
source unreviewed (same reasoning as
[[main/Lessons/review-2026-08-15-journal-audit-fix-frontmatter-noop]]).

The real fix: `_snapshot_session_to_journal` already has `session.agent` in
hand — it should compute the journal path the same way
`_append_journal_entry` does (`get_agent_journal_dir(session.agent, ...)` +
`journal_daily_path(session.agent, today)`) instead of calling
`self._get_journal_path()`, which silently re-resolves "current session"
from bot-wide/request-scoped state that may not match the session actually
being snapshotted.

## Detect next time

- `grep -c '^_Agent:' <agent>/Journal/<month>/<day>.md` compared against a
  grep for lines *not* matching `_Agent: <agent>` — any hit means foreign
  snapshots landed there. contador-pj is the one confirmed to be the
  fallback sink so far; worth spot-checking if `active_session` behavior
  changes.

## Update 2026-08-25 — contador (not just contador-pj) now also a sink

2026-08-25's nightly audit found the same pattern spread to a *second*
agent: `contador/Journal/2026-08/2026-08-25.md` carries three `## Session
Snapshot` blocks tagged `_Agent: contador-pj`, `_Agent: levain`, and
`_Agent: mexc-bot` — none for `contador` itself. `contador-pj`'s own
2026-08-25 file shows the pattern too (its own snapshot, correctly tagged,
plus one foreign `_Agent: levain` block). So `active_session` was pinned to
`contador` for some auto-compacts today and to `contador-pj` for others —
confirming this isn't a single fixed fallback sink, it tracks whatever the
bot-wide `active_session` pointer happened to be at each auto-compact
moment, consistent with the original diagnosis. No data lost (each foreign
session also has its own correctly-placed entry in its own agent's
journal), still just duplication. Not fixed tonight — same reasoning as
2026-08-21, this is `claude-fallback-bot.py` production source and needs a
human-reviewed session, not an unattended NO_REPLY routine.
- General shape to watch for across this codebase: a function that receives
  an explicit target object (session, agent, etc.) for *labeling* but calls
  a different helper that re-derives "the current" version of that same
  concept from ambient state for the *side effect* (file path, write
  target). Same root shape as
  [[main/Lessons/review-2026-08-15-routine-noreply-skips-activity-log]] —
  two code paths that should agree on "which session/agent" but don't.

## Update 2026-10-14 — recurrence confirmed, still unfixed

Nightly audit found the pattern again: `contador-pj/Journal/2026-10/2026-10-14.md`
carries two `## Session Snapshot` blocks tagged `_Agent: mexc-bot`, none for
`contador-pj` itself beyond its own `alertas-boletos-diario` routine report.
`grep -c '^_Agent:'` across `contador-pj/Journal/2026-10/*.md` shows the sink
pattern on nearly every day this month (10-01 through 10-14) — continuous,
not intermittent, since at least 2026-08-21. No data lost: the foreign
content (SL-restored/`executeCycle` fix) is also correctly and more
thoroughly recorded in `mexc-bot/Journal/2026-10/2026-10-13.md`. Still not
fixed tonight, same reasoning as 2026-08-21/2026-08-25 — this is
`claude-fallback-bot.py` production source and needs a human-reviewed
session, not an unattended NO_REPLY routine. Flagging again since
`contador-pj` has now been the fallback sink for at least two months
straight — worth prioritizing the actual code fix described above.
