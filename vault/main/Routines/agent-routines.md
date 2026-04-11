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
_(no matches)_
<!-- vault-query:end -->

## Routines

<!-- vault-query:start filter="type=routine" scope="main/Routines" sort="title" format="- [[{link}|{stem}]] — {description}" -->
- [[main/Routines/journal-audit|journal-audit]] — Nightly audit that checks all agents' journals for completeness, fixes frontmatter issues, and fills gaps from the activity log.
- [[main/Routines/update-check|update-check]] — Checks daily for updates to the Claude Code CLI or the claude-bot repo. Notifies only when there is something to update.
- [[main/Routines/vault-graph-update|vault-graph-update]] — Regenerates the vault's lightweight knowledge graph from frontmatter and wikilinks. No LLM cost.
- [[main/Routines/vault-indexes-update|vault-indexes-update]] — Auto-regenerates vault index marker blocks (Routines.md, Skills.md, Agents.md, etc.) from frontmatter via scripts/vault_indexes.py. Stays silent unless something changed.
- [[main/Routines/vault-lint|vault-lint]] — Daily vault hygiene check. Runs scripts/vault_lint.py and notifies on Telegram only when issues are found. Otherwise stays silent (NO_REPLY).
<!-- vault-query:end -->
