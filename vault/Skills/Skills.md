---
title: Skills
description: Index of all vault skills. Hub connecting skills to the main graph.
type: index
created: 2026-04-07
updated: 2026-04-11
tags: [index, skills]
---

# Skills

Recurring and structured tasks, executable by Claude Code.

## Creation skills

Interactive skills for creating vault artifacts.

- [[create-routine]] — Create or review scheduled routines (suggests pipeline when it makes sense)
- [[create-pipeline]] — Create or review multi-agent pipelines (parallelism consulting)
- [[create-agent]] — Create new specialized agents
- [[import-agent]] — Import existing agents from OpenClaw
- [[extract-knowledge]] — Extract durable concepts from pipelines/conversations into Notes/

## Operational skills

Reusable procedures invoked by routines and pipeline steps. Encapsulate common operations so each step doesn't reinvent the logic.

- [[publish-notion]] — Publish content to a Notion database (authentication, blocks, batching, covers)
- [[publish-x]] — Post to X/Twitter via PinchTab or cookie-based API (threads, media, rate limiting)
- [[publish-threads]] — Post to Threads via PinchTab (single posts, carousels, threading)
- [[generate-image]] — Generate images via Gemini nano-banana, host on catbox.moe (dimensions, prompts, fallbacks)
- [[fetch-web]] — Fetch web content with standardized tool selection (PinchTab vs curl), RSS/HTML parsing, retries
- [[review-calendar]] — Check upcoming economic events, sports fixtures, and date-sensitive context for routines

## Engineering discipline

General-purpose engineering skills that enforce the project's quality rules (zero silent errors, test contracts, verification before completion).

- [[systematic-debugging]] — Four-phase root cause methodology for any bug, test failure, or unexpected behavior
- [[test-driven-development]] — Red-Green-Refactor cycle enforcing the project's test contracts before shipping code
- [[verify-before-completion]] — Gate function requiring fresh verification evidence before claiming work done
- [[audit-insecure-defaults]] — Detect fail-open insecure defaults and hardcoded secrets in bot code and config

