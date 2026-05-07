---
title: OSS Watchlist
description: External PRs and commits flagged by OSS Radar for monitoring. Daily oss-radar routine checks state changes and surfaces updates when watched items merge, close, or gain major activity.
type: note
created: 2026-04-23
updated: 2026-04-23
tags: [oss, radar, watchlist, monitoring]
---

[[main/Notes/agent-notes|Notes]]
## Active watches

- **hermes-agent PR #2044** — `fix(agent): prevent silent context loss when mid-turn compression`
  - Repo: NousResearch/hermes-agent
  - Why we care: directly relevant to our auto-compact logic (claude-fallback-bot.py `_auto_compact`, `AUTO_COMPACT_INTERVAL = 20`). If their fix for silent context loss generalizes, we may hit the same issue.
  - When to act: when it merges, re-read the final diff and assess whether our flow has an analogous failure mode.
  - First seen: 2026-04-22 OSS Radar report.

## How this list is used

`vault/main/Routines/oss-radar-v2/steps/analyze.md` reads this file during the daily pipeline. For each active watch, the analyze step checks the collected GitHub data for state changes (merged / closed / major update) and surfaces them under a `⚠️ Watchlist update` header in the Telegram report.

## Resolving a watch

When a watched item resolves (merged + investigated, or no longer relevant), move its entry from `Active watches` to `Resolved watches` below with a one-line note on the outcome.

## Resolved watches

_(none yet)_
