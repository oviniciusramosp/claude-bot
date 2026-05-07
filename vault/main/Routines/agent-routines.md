---
title: Routines
description: Routines and pipelines belonging to the main agent.
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index, routines]
---

# Routines (main)

## Pipelines

<!-- vault-query:start filter="type=pipeline" scope="main/Routines" sort="title" format="- [[{link}|{stem}]] — {description}" -->
- [[main/Routines/oss-radar-v2|oss-radar-v2]] — Pipeline v2 -- typed steps; one Python collector + opus LLM analyzer + Telegram publish sink. Daily scan of OpenClaw + Hermes Agent for new commits, PRs, and releases. Replaces oss-radar.md (v1 disabled).
<!-- vault-query:end -->

## Routines

<!-- vault-query:start filter="type=routine" scope="main/Routines" sort="title" format="- [[{link}|{stem}]] — {description}" -->
- [[main/Routines/journal-audit|journal-audit]] — Nightly audit that checks all agents' journals for completeness, fixes frontmatter issues, and fills gaps from the activity log.
- [[main/Routines/journal-weekly-rollup|journal-weekly-rollup]] — Monday morning: produce a compact bullet-style summary of last week's journal for every agent — global routine that iterates iter_agent_ids() automatically. New agents are picked up with zero config per contract C7.
- [[main/Routines/skill-audit|skill-audit]] — Monthly audit of all vault skills across agents — checks trigger clarity, description accuracy, staleness, and overlap. Reports issues or NO_REPLY if everything is healthy.
- [[main/Routines/update-check|update-check]] — Checks daily for updates to Claude Code CLI and claude-bot repo/macOS app. Summarizes changes, recommends urgency, offers install button.
- [[main/Routines/vault-health|vault-health]] — Daily vault health check: broken wikilinks, missing frontmatter, orphan files, stale routines. Notifies only when issues are found.
- [[main/Routines/vault-rebuild|vault-rebuild]] — Nightly rebuild: knowledge graph, FTS full-text index, and MOC index files. Silent on success.
<!-- vault-query:end -->
