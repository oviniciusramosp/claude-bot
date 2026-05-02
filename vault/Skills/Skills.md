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
<!-- vault-query:end -->
