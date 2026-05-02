---
title: Migrate Pipeline to v2
description: Step-by-step migration of an existing v1 pipeline to Pipeline v2 (typed steps, validators between LLMs, publish-only side effects, accepts_overrides schema). Use when converting a daily-flaky v1 pipeline to the new architecture, with the crypto-ta-analise pipeline as the running example. Pipeline must already exist as v1 before applying this skill.
type: skill
created: 2026-05-02
updated: 2026-05-02
tags: [skill, pipeline, infrastructure, migration, v2]
---

## When to use this skill

Use when:
- A v1 pipeline keeps producing inconsistent results that need daily manual fixes
- You're about to add features to a pipeline and want to upgrade architecture first
- The user explicitly asks to "migrate <pipeline> to v2"

This skill builds on `vault/Skills/create-pipeline.md` (which describes
the v2 model from scratch). Read that first if v2 concepts are unfamiliar.

## Pre-flight checklist

Before migrating, gather:
- [ ] The full pipeline file: `vault/<agent>/Routines/<name>.md`
- [ ] All step prompt files: `vault/<agent>/Routines/<name>/steps/*.md`
- [ ] Recent execution history: `vault/<agent>/Routines/<name>/.history/` (or `~/.claude-bot/routines-state/`)
- [ ] The user's pain points — which steps need manual fixes most often?

## Migration procedure (8 steps)

### 1. Enable the feature flag in the user's environment

```bash
# In ~/claude-bot/.env (NOT vault/.env — bot config)
PIPELINE_V2_ENABLED=true
```

This is required globally. v2 pipelines silently fall back to v1 path
when the flag is unset (a safety guarantee — see spec § 11). The user
must restart the bot after editing `.env` for the flag to take effect.

### 2. Inventory the existing steps and classify them

For each step in the v1 YAML, decide its v2 type using this decision tree:

| If the step's prompt mostly… | Type |
|---|---|
| Calls an HTTP API (Binance, CoinGecko, Notion, RSS) and parses the response | `script` |
| Runs a deterministic transformation (regex, file conversion, schema validation) | `script` |
| Writes a markdown post / does narrative analysis / picks a creative title | `llm` |
| Checks output against a fixed ruleset (forbidden tokens, paragraph counts, schema) | `validate` |
| Sends to Telegram, Notion, Slack, file write to a permanent location | `publish` |
| Manually waits for human review | `gate` (existing field, no migration) |

**TA pipeline reference classification:**

| v1 step | v2 type | Rationale |
|---|---|---|
| `collect-binance` | `script` | Pure API call → JSON → markdown. Deterministic. |
| `collect-sentiment` | `script` | Same. |
| `collect-macro` | `script` | Same. |
| `collect-github` | `script` | Same. |
| `collect-headlines` | `script` (with optional `llm` filter) | API call + light scoring. |
| `analyst` | `llm` | Genuine analytical reasoning. |
| `cover` | `llm` | Creative cover image prompt + DALL-E call. |
| `writer` | `llm` | Narrative writing. |
| `reviewer` (Opus 900s) | **split** → `validate` (mechanical regex) + small `llm` (semantic check) | Currently does both. Separate them — most checks are mechanical. |
| `publisher` (monolithic) | **split** → `llm` (build payload) + `validate` (schema) + `publish` (Notion) + `publish` (Telegram) | Today does payload + Notion API + Telegram from inside an LLM prompt. The biggest source of flakiness. |

The reviewer + publisher split is where you'll see the biggest quality
improvement. The collect-* migration is where you'll see the biggest
SPEED improvement.

### 3. Add `pipeline_version: 2` to the frontmatter

```yaml
---
title: "Análise Técnica Diária"
type: pipeline
pipeline_version: 2  # ← NEW: opt into v2 dispatcher
schedule:
  ...
```

This is the per-pipeline opt-in. Without it, the executor uses the v1
code path even when `PIPELINE_V2_ENABLED=true`.

### 4. Convert each `script` step

For each step you classified as `script`:

a. Create the script file under `vault/<agent>/Routines/<pipeline>/scripts/<step-id>.py`
   (per Q4 — per-pipeline scripts/ folder).

b. The script must follow this contract:
   - Read inputs from env vars (`PIPELINE_DATA_DIR`, `STEP_OVERRIDE_*`, etc — see spec § 4)
   - Write its output to the path in `PIPELINE_STEP_OUTPUT_FILE` env var
   - Print a JSON status report on the LAST line of stdout:
     `{"status": "ready"}` (success) or `{"status": "skipped", "reason": "..."}` (no-op) or `{"status": "failed", "reason": "..."}` (error)
   - All other stdout lines are logged; NONE reach Telegram (script-side leak prevention)
   - DO NOT import from `claude-fallback-bot.py` (Q5 — isolation by subprocess boundary)

c. Update the YAML step to type=script + command:

```yaml
- id: collect-binance
  type: script
  name: "Binance Collection (spot + futures)"
  command: python3 vault/crypto-bro/Routines/crypto-ta-analise/scripts/collect_binance.py
  timeout: 300
  retry: 1
  output_file: collect-binance.md  # what the script writes via PIPELINE_STEP_OUTPUT_FILE
```

d. Move the step's old prompt file (`steps/collect-binance.md`) to
   `steps/.archived/collect-binance.md` for reference. The script
   replaces the prompt; the LLM no longer runs for this step.

### 5. Convert the `reviewer` step into validate + small llm

Today's reviewer is one Opus invocation that does mechanical checks AND
semantic review. Split:

**5a. The mechanical check** (validate step, ~50ms vs Opus's 900s):

```yaml
- id: reviewer-validate
  type: validate
  name: "Mechanical review (lint)"
  validates: writer
  command: python3 vault/crypto-bro/Routines/crypto-ta-analise/scripts/lint_post.py
  on_failure: feedback  # rerun writer with the validator's feedback once
  timeout: 30
```

The `lint_post.py` script:
- Reads `PIPELINE_VALIDATION_TARGET` (the writer's output)
- Runs regex/AST checks (no tilde, no `US$`, BTC→Bitcoin in prose, max 3
  paragraphs per section, chart label empty, etc — pull from the OLD
  reviewer prompt's bulletted rules)
- On any violation, prints `{"status": "failed", "reason": "X violations: ...", "feedback": "Fix the following: ..."}` and exits 1
- On clean, prints `{"status": "ready"}` and exits 0

When `on_failure: feedback`, a single failure reruns the upstream
`writer` with the feedback text appended to its prompt. Capped at 1
retry by spec § 2.3 — second failure fails the pipeline.

**5b. The semantic check** (smaller llm step, e.g. Sonnet):

```yaml
- id: reviewer-semantic
  type: llm
  name: "Semantic review (narrative quality)"
  model: sonnet  # not Opus — semantic is small
  depends_on: [reviewer-validate]
  prompt_file: steps/reviewer-semantic.md
  timeout: 300
```

The new `steps/reviewer-semantic.md` contains ONLY the narrative-quality
checks from the old reviewer (Section 1 storytelling, scenario
consistency, accessibility). Drop everything mechanical — that lives in
the validate step now.

### 6. Convert the `publisher` step into llm + validate + publish + publish

The biggest leverage. Today's publisher does FOUR things in one LLM
invocation: builds Notion payload, calls Notion API, optionally posts a
comment, sends Telegram. Split:

```yaml
- id: build-notion-payload
  type: llm
  name: "Build Notion payload"
  depends_on: [reviewer-semantic]
  prompt_file: steps/build-notion-payload.md
  output_file: notion-payload.json
  timeout: 180

- id: notion-payload-check
  type: validate
  name: "Schema-check Notion payload"
  validates: build-notion-payload
  command: python3 scripts/validate_notion_payload.py
  on_failure: feedback
  timeout: 30

- id: publish-notion
  type: publish
  name: "Publish to Notion"
  depends_on: [notion-payload-check]
  publishes: build-notion-payload
  sink: notion
  sink_config:
    script: scripts/notion_blocks.py
  timeout: 120

- id: notify-telegram
  type: publish
  name: "Notify on Telegram"
  depends_on: [publish-notion]
  publishes: reviewer-semantic
  sink: telegram
  sink_config:
    silent: false
  timeout: 30
```

The new `steps/build-notion-payload.md` writes a JSON file describing
the page (title, blocks, properties). The validate step schema-checks
it. The publish-notion step shells out to `scripts/notion_blocks.py`
(deterministic API call). The notify-telegram step sends the post
content via the bot's Telegram sink.

ZERO API calls inside an LLM prompt. Each side-effect is its own
typed step.

### 7. Add `accepts_overrides` to relevant steps

For each step that has a meaningful runtime knob, declare it:

```yaml
- id: analyst
  type: llm
  ...
  accepts_overrides:
    focus_asset:
      type: string
      enum: [BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK]
      default: BTC
      description: "Asset to spotlight in this run's analysis"
    depth:
      type: string
      enum: [quick, normal, deep]
      default: normal
      description: "How deep the analysis goes"
```

Don't expose every internal knob — overrides are user-facing levers.
Pick attributes the user (or an agent acting on user instructions)
would meaningfully want to change between runs.

### 8. Run the v2 pipeline in parallel with v1 for a day or two

Two safe ways:
- Save the v2 file as a SEPARATE name (e.g. `crypto-ta-analise-v2.md`)
  and run it alongside the v1 file at a different `schedule.times`
- Or: keep `pipeline_version: 1` in the v1 file, copy it to a new file
  with `pipeline_version: 2`, run both manually with `/run` and compare
  outputs

After a few clean runs, replace v1 with v2 (rename the file, archive
the old prompts, delete the v1 schedule entries).

## What NOT to migrate

Some pipelines don't benefit from v2:
- Simple single-step routines (use `type: routine` instead — no DAG)
- Pipelines that already only have 1-2 steps with no validators or sinks
- Highly experimental / unstable pipelines (migrate AFTER stabilizing)

If unsure, ask the user.

## Checklist before declaring migration complete

- [ ] `pipeline_version: 2` in frontmatter
- [ ] Every step has explicit `type:` (no defaults)
- [ ] All API/data-fetch steps moved to `script` type
- [ ] Mechanical review rules moved to `validate` step + Python lint script
- [ ] All side-effects (Notion, Telegram, file writes to permanent locations) are `publish` steps
- [ ] No HTTP API calls remain inside any LLM prompt
- [ ] No regex/schema checks remain inline in LLM prompts (they're in validate scripts)
- [ ] Rules that previously appeared in 3 places (step prompt + reviewer + skill) now appear in 1 (the validate script)
- [ ] Overrides declared for the user-facing knobs
- [ ] v2 ran cleanly at least 3 times in parallel with v1

## Common mistakes (from the v2 spec § 12 + Phase 1 implementation)

1. Forgetting to set `PIPELINE_V2_ENABLED=true` in `.env` and restart the bot
2. Putting `pipeline_version: 2` at step level (it goes at frontmatter / pipeline level)
3. Confusing `step.engine` (claude/codex runner) with `pipeline_version` (v1/v2)
4. Importing from `claude-fallback-bot.py` in script steps (forbidden by Q5)
5. Sending Telegram from inside an LLM step (the 3-condition gate would block it but the prompt itself is wrong — use a `publish` step)
6. Per-step isolation: assuming `focus_asset` set on `analyst` propagates to `writer`. It doesn't — declare it on both, or declare it once and pass via shared file
