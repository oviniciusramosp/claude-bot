---
title: Claude Bot Vault
description: Root of the per-agent vault. Single bridge that connects every agent through path-qualified wikilinks.
type: index
created: 2026-04-07
updated: 2026-04-11
tags: [index, vault, root]
---

# Claude Bot Vault

Persistent knowledge graph for the bot. Powered by Claude Code, navigable in Obsidian.

The vault is organized as **one tree per agent**, with this README as the single bridge between agent groups. Each agent owns its own Skills, Routines, Journal, Reactions, Lessons, and Notes — isolamento total, no inheritance.

## Shared

- [[CLAUDE]] — Universal vault rules (frontmatter, graph, linking)
- [[Tooling]] — Tool preferences shared across all agents
- [[Skills/Skills|Shared Skills]] — Meta/infra skills available to every agent (pipeline/routine/agent authoring, frontmatter validators, index helpers)

## Agents

<!-- vault-query:start filter="type=agent" sort="name" format="- [[{stem}]]" -->
- [[agent-contador]]
- [[agent-crypto-bro]]
- [[agent-digests]]
- [[agent-main]]
- [[agent-mexc-bot]]
- [[agent-parmeirense]]
<!-- vault-query:end -->

## Credentials

`.env` at the vault root holds shared API keys (gitignored).
