---
title: OSS Radar (v2)
description: Pipeline v2 -- typed steps; one Python collector + opus LLM analyzer + Telegram publish sink. Daily scan of OpenClaw + Hermes Agent for new commits, PRs, and releases. Replaces oss-radar.md (v1 disabled).
type: pipeline
pipeline_version: 2
created: 2026-05-03
updated: 2026-05-03
tags: [pipeline, oss, openclaw, hermes, competitive-intel, daily, v2]
schedule:
  days: ["*"]
  times: ["07:00"]
model: opus
enabled: true
notify: final
context: minimal
---

[[main/Routines/agent-routines|Routines]]

```pipeline
steps:
  - id: collect-github
    type: script
    name: "GitHub activity collection (OpenClaw + Hermes Agent)"
    command: python3 /Users/viniciusramos/claude-bot/vault/main/Routines/oss-radar/scripts/collect_github_v2.py
    output_file: collect-github.md
    timeout: 180
    retry: 1

  - id: analyze
    type: llm
    name: "Relevance analysis and report"
    model: opus
    depends_on: [collect-github]
    prompt_file: steps/analyze.md
    output_file: analyze.md
    timeout: 600
    inactivity_timeout: 240

  - id: notify-telegram
    type: publish
    name: "Send report to Telegram (cascade-skip on NO_REPLY)"
    depends_on: [analyze]
    publishes: analyze
    sink: telegram
    sink_config:
      silent: false
```

## Steps

- [[main/Routines/oss-radar-v2/steps/analyze|analyze]]

## Scripts (in `oss-radar/scripts/`)

- `collect_github_v2.py` -- single deterministic collector. Lists `openclaw` org repos sorted by `pushed_at`, fetches recent commits + releases for each one pushed in the last 48h, then fetches commits/releases/open PRs for `NousResearch/hermes-agent`. Writes structured markdown to `data/oss-radar-v2/collect-github.md` (sections `## collection_status`, `## openclaw_repos_overview`, and one `## <repo>_activity` per active repo). Auth chain: `gh` CLI (host auth) -> `GITHUB_TOKEN` env var -> anonymous (60 req/h public). Best-effort: per-source try/except, partial failures recorded inline; only emits `status: failed` if every fetch fails.

## Migration notes

v1 was a 2-step LLM pipeline (`collect` + `analyze`) where the collector spawned haiku to call `curl` 6+ times against the GitHub REST API and then re-format the responses by hand. v2 keeps the analyzer (opus, judgement work) but replaces the collector with a deterministic Python script:

- Mechanical work (REST API fan-out, response parsing, lookback filtering) leaves the LLM critical path entirely; runs in ~5-10s vs the 30-60s a haiku step took for the same calls.
- The script honours `GITHUB_TOKEN` (or piggy-backs on `gh` CLI auth) so private repos are reachable when needed; anonymous still works for public OpenClaw + Hermes.
- Telegram delivery is now a structural `publish` step (sink: telegram) instead of v1's `output: telegram` convention -- aligns with the v2 leak-prevention gate.
- v1 file at `oss-radar.md` flipped to `enabled: false`; its `oss-radar/steps/collect.md` prompt is intentionally left in place as a safety net while v2 stabilizes.
