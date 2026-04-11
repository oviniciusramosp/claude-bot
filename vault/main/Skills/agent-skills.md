---
title: Skills
description: Skills belonging to the main agent.
type: index
created: 2026-04-11
updated: 2026-04-11
tags: [index, skills]
---

# Skills (main)

<!-- vault-query:start filter="type=skill" scope="main/Skills" sort="title" format="- [[{link}|{stem}]] — {description}" -->
- [[main/Skills/audit-insecure-defaults|audit-insecure-defaults]] — Detect fail-open insecure defaults (hardcoded secrets, fallback tokens, weak auth, permissive config) in the bot codebase. Use when auditing .env handling, reviewing new config paths, or hardening for distribution.
- [[main/Skills/create-agent|create-agent]] — Consultative skill for creating specialized agents or reviewing existing ones. Helps decide whether a case requires a dedicated agent or if the Main Agent is sufficient. Generates the 3 files (agent.md, CLAUDE.md, {id}.md) + Journal.
- [[main/Skills/create-pipeline|create-pipeline]] — Skill for creating or reviewing pipelines with multiple parallel steps. Proactively analyzes parallelism opportunities and anti-patterns in existing pipelines.
- [[main/Skills/create-routine|create-routine]] — Skill for creating scheduled routines or reviewing existing ones. Proactively analyzes whether the user's use case would work better as a parallel pipeline.
- [[main/Skills/extract-knowledge|extract-knowledge]] — Extracts durable concepts from pipeline outputs or conversations and creates/updates notes in Notes/. Automates knowledge base population.
- [[main/Skills/fetch-web|fetch-web]] — Standard procedure for fetching and parsing web content. Covers tool selection (PinchTab vs curl), RSS parsing, HTML extraction, retries, and rate limiting.
- [[main/Skills/generate-image|generate-image]] — Standard procedure for generating images for publications. Covers Gemini nano-banana, local scripts, hosting via catbox.moe, and dimension conventions per use case.
- [[main/Skills/import-agent|import-agent]] — Skill to import agents from external systems (e.g. OpenClaw) into the claude-bot vault, or to review previously imported agents to verify whether the CLAUDE.md synthesis was adequate. Reads instruction files, config and metadata and generates the vault/Agents/{id}/ structure with agent.md + CLAUDE.md + Journal/.
- [[main/Skills/publish-notion|publish-notion]] — Standard procedure for publishing content to a Notion database. Handles authentication, block conversion, 100-block batching, cover images, and error recovery.
- [[main/Skills/publish-threads|publish-threads]] — Standard procedure for posting to Threads (Meta) via PinchTab. Handles single posts, carousels of images, and character limits.
- [[main/Skills/publish-x|publish-x]] — Standard procedure for posting to X via PinchTab (preferred) or cookie-based API. Handles threads, media, character limits, and rate limiting.
- [[main/Skills/review-calendar|review-calendar]] — Standard procedure for checking upcoming relevant dates and events (economic calendar, sports fixtures, macro events) to enrich routine context with time-sensitive information.
- [[main/Skills/systematic-debugging|systematic-debugging]] — Four-phase root cause methodology for any bug, test failure, or unexpected behavior. Enforces investigation before fixes. Use when debugging the bot, a routine, or a pipeline step.
- [[main/Skills/test-driven-development|test-driven-development]] — Red-Green-Refactor cycle for any feature or bugfix that touches bot code. Write the test first, watch it fail, then write minimal code to pass. Enforces the project's test contracts.
- [[main/Skills/verify-before-completion|verify-before-completion]] — Gate function that requires fresh verification evidence before claiming any work is done. No success claims without having just run the verification command in the current context.
<!-- vault-query:end -->
