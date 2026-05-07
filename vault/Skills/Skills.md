---
title: Shared Infrastructure Skills
description: Meta/infra skills shared across all agents - pipeline authoring, routine authoring, system-level helpers. Strict carve-out from the isolamento total rule (see CLAUDE.md).
type: index
created: 2026-05-02
updated: 2026-05-02
tags: [index, skills, infrastructure, shared]
---

[[README]]

# Shared Infrastructure Skills

This index lists **shared infrastructure skills** available to every agent in the vault. Unlike per-agent skills (`<agent>/Skills/`), the files listed here are not domain knowledge — they are mechanical, system-level instructions that every agent invokes identically: how to author a pipeline, how to scaffold a routine, how to validate frontmatter, how to regenerate indexes.

This directory is a **strict carve-out** from the isolamento total rule. See `CLAUDE.md` → "Exceção: shared infrastructure skills" for the full criterion. Domain skills (writing voice, publishing format, agent personality) MUST stay under `<agent>/Skills/` — only meta/infra goes here.

Reference these skills as `[[Skills/<name>]]` (path-qualified from vault root) to disambiguate from each agent's own `<agent>/Skills/` namespace.

<!-- vault-query:start filter="type=skill" scope="Skills" sort="title" format="- [[{link}|{stem}]] — {description}" -->
- [[Skills/create-pipeline|create-pipeline]] — Author a new pipeline (DAG of typed steps) with explicit I/O contracts, validators between LLM steps, and side-effects isolated to publish steps. Use whenever creating or substantially modifying any vault/<agent>/Routines/*.md pipeline file.
- [[Skills/create-routine|create-routine]] — Author a new single-prompt scheduled task (vault/<agent>/Routines/*.md with type=routine). Use whenever creating or modifying a routine. For multi-step DAG workflows, use create-pipeline instead.
- [[Skills/migrate-pipeline-v2|migrate-pipeline-v2]] — Step-by-step migration of an existing v1 pipeline to Pipeline v2 (typed steps, validators between LLMs, publish-only side effects, accepts_overrides schema). Use when converting a daily-flaky v1 pipeline to the new architecture, with the crypto-ta-analise pipeline as the running example. Pipeline must already exist as v1 before applying this skill.
- [[Skills/pipeline-router|pipeline-router]] — Translate a user's natural-language request to trigger a pipeline into the structured form the executor expects (pipeline name + per-step overrides JSON). Use when the user asks any agent to "run pipeline X" with optional adjustments like "with focus on ETH" or "but use depth=deep". Outputs the exact `/run --overrides` invocation or the equivalent shell command.
<!-- vault-query:end -->
