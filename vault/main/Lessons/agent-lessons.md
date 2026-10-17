---
title: Lessons
description: Lessons belonging to the main agent.
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index, lessons]
---

# Lessons (main)

<!-- vault-query:start filter="type=lesson" scope="main/Lessons" sort="title" format="- [[{link}|{stem}]] — {description}" -->
- [[main/Lessons/review-2026-08-21-session-snapshot-wrong-agent-journal|review-2026-08-21-session-snapshot-wrong-agent-journal]] — _snapshot_session_to_journal() resolves its write path via self._get_journal_path() → self._get_session(), ignoring the session object already passed in as a parameter — so background auto-compacts for other agents' sessions get appended to whichever session self._get_session() falls back to.
- [[main/Lessons/draft-2026-06-10-meta-skill-improver|draft-2026-06-10-meta-skill-improver]] — Auto-draft from routine failure; needs user to fill Fix and Detect sections.
- [[main/Lessons/draft-2026-06-16-update-check|draft-2026-06-16-update-check]] — Auto-draft from routine failure; needs user to fill Fix and Detect sections.
- [[main/Lessons/draft-2026-06-17-update-check|draft-2026-06-17-update-check]] — Auto-draft from routine failure; needs user to fill Fix and Detect sections.
- [[main/Lessons/draft-2026-06-18-update-check|draft-2026-06-18-update-check]] — Auto-draft from routine failure; needs user to fill Fix and Detect sections.
- [[main/Lessons/draft-2026-06-20-update-check|draft-2026-06-20-update-check]] — Auto-draft from routine failure; needs user to fill Fix and Detect sections.
- [[main/Lessons/draft-2026-06-20-vault-health|draft-2026-06-20-vault-health]] — Auto-draft from routine failure; needs user to fill Fix and Detect sections.
- [[main/Lessons/draft-2026-06-10-vault-rebuild|draft-2026-06-10-vault-rebuild]] — Auto-draft from routine failure; needs user to fill Fix and Detect sections.
- [[main/Lessons/review-2026-08-15-journal-audit-fix-frontmatter-noop|review-2026-08-15-journal-audit-fix-frontmatter-noop]] — fix_frontmatter() returns early on any file with valid --- delimiters, so the most common broken-frontmatter case (missing `title`) is reported as fixed but never actually written. Confirmed recurring 2026-08-23 — real root cause is claude-fallback-bot.py's daily-file bootstrap template, not just the audit script. journal-audit.py side fixed 2026-08-25.
- [[main/Lessons/review-2026-07-20-macos-tmp-cleanup-daemon-dirs|review-2026-07-20-macos-tmp-cleanup-daemon-dirs]] — macOS periodically cleans /tmp of empty/inactive directories. Daemons must create temp dirs at write-time (mkdir exist_ok=True), not assume they persist from startup. Bit claude-bot file downloads.
- [[main/Lessons/review-2026-06-15-0108-pinchtab-launchd-display-timing|review-2026-06-15-0108-pinchtab-launchd-display-timing]] — Display session unavailable when launchd starts Chrome CDP; requires delay or wrapper script
- [[main/Lessons/review-2026-08-15-routine-noreply-skips-activity-log|review-2026-08-15-routine-noreply-skips-activity-log]] — _finalize_response() returns before the activity-log block when a routine's final text is exactly NO_REPLY, so journal-audit.py's agent-discovery (100% keyed off .activity/*.jsonl) silently never sees that agent, even though its journal Report block was written correctly.
<!-- vault-query:end -->
