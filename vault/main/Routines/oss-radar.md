---
title: OSS Radar
description: Daily scan of OpenClaw and Hermes Agent repos for new commits, PRs, and releases. Opus analyzes relevance to claude-bot product and reports actionable insights.
type: pipeline
created: 2026-04-14
updated: 2026-04-17
tags: [pipeline, oss, openclaw, hermes, competitive-intel, daily]
schedule:
  days: [*]
  times: ["07:00"]
model: glm-5.1
enabled: true
notify: final
context: minimal
---

```pipeline
steps:
  - id: collect
    name: "GitHub activity collection"
    model: haiku
    prompt_file: steps/collect.md
    timeout: 360
    inactivity_timeout: 180
    retry: 1

  - id: analyze
    name: "Relevance analysis and report"
    model: opus
    depends_on: [collect]
    prompt_file: steps/analyze.md
    timeout: 600
    retry: 1
    output: telegram

```

## Steps

- [[main/Routines/oss-radar/steps/collect|collect]]
- [[main/Routines/oss-radar/steps/analyze|analyze]]
