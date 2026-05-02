---
title: Create Pipeline
description: Author a new pipeline (DAG of typed steps) with explicit I/O contracts, validators between LLM steps, and side-effects isolated to publish steps. Use whenever creating or substantially modifying any vault/<agent>/Routines/*.md pipeline file.
type: skill
created: 2026-05-02
updated: 2026-05-02
tags: [skill, pipeline, infrastructure, authoring]
---

# Create Pipeline

A pipeline is a DAG of **typed steps** that the bot harness executes against an agent's vault. Each step has a single, narrow job — and the type of that job determines how the step is wired, what its prompt should contain, and which outputs are downstream of it. This skill teaches you to author pipelines that don't drift, don't reimplement mechanical work as LLM calls, and don't hide side-effects inside reasoning prompts.

**Read this whole file before you write the YAML.** The most common cause of flaky pipelines is starting from a shape ("collect → analyze → publish") and only later realizing some of those steps shouldn't have been LLM calls at all.

---

## 1. When to use this skill

Trigger this skill whenever you are:

- Creating a new pipeline file at `vault/<agent>/Routines/<pipeline-name>.md`
- Adding, removing, or renaming a step in an existing pipeline
- Promoting a routine to a pipeline because it grew multi-step
- Refactoring a pipeline that needs daily fixes (a strong signal that the steps are mistyped or rules are duplicated)
- Reviewing a pipeline someone else wrote for production-readiness

**Do not** use this skill for single-prompt routines (`type: routine`). For those, see the agent-local `create-routine` skill — the triage there decides whether the user's idea grew into pipeline territory.

---

## 2. The step type — classify before you write a single line of prompt

Every step has a `type:` field. **You must classify each step before writing its prompt.** Skipping this is the root cause of every monolithic, flaky pipeline in the vault today.

| Type | When to use | Output owned by |
|---|---|---|
| `llm` | Creative or judgment work: writing prose, narrative analysis, title generation, prompt routing, deciding which scenarios matter | the model |
| `script` | Deterministic transformation: API calls (Binance, Notion, Telegram), data parsing, file conversions, regex/AST work, anything where same input must give same output | a Python/bash script |
| `validate` | Schema/linter checks on a previous step's output; returns structured pass/fail and feedback on failure | a script invoked by the harness |
| `publish` | Sending output to an external sink (Telegram message, Notion page, file write outside the workspace, third-party API) | a sink adapter, never an LLM |
| `gate` | Manual human review or an explicit pause point | the human |

### 2.1 The decision tree (use this every time)

Before writing a step's prompt, ask in this order:

1. **Am I waiting for a human to look at something?** → `gate`. Stop.
2. **Am I sending output to an external sink (Telegram chat, Notion DB, S3, file outside the workspace)?** → `publish`. Stop.
3. **Am I checking the previous step's output against a schema, regex, length budget, or rule set, and returning pass/fail?** → `validate`. Stop.
4. **Is the work mechanical — same input always produces the same output (HTTP call, JSON parse, markdown→blocks conversion, file rename)?** → `script`. Stop.
5. **Is the work creative or judgment-heavy — picking what matters, writing narrative prose, deciding tone, synthesizing scattered signals?** → `llm`.

### 2.2 The reclassification check

After classifying as `llm`, re-read the prompt you intend to write. If most sentences look like:

- *"If X, do Y."*
- *"Never use Z."*
- *"Format the output as W."*
- *"Replace tildes with hyphens."*

…you have a **mistyped step**. Rule-following is not creative work. Re-classify it as `validate` (if it's checking an upstream output) or `script` (if it's transforming data). LLMs forget rules; validators don't.

A useful sanity test: *"If I gave this prompt to ten different models, would they all produce identical output?"* If yes → it's a `script` or `validate` step.

---

## 3. The step contract

Every step — regardless of type — declares its inputs and outputs explicitly. The executor and downstream steps rely on this contract; "the LLM will figure it out by reading the workspace" is exactly the failure mode this skill exists to prevent.

### 3.1 Mandatory fields

```yaml
- id: writer                    # kebab-case, unique within the pipeline
  type: llm                     # one of: llm, script, validate, publish, gate
  name: "Draft the report"      # human-readable
  depends_on: [analyst]         # explicit upstream — never implicit
  input:                        # what this step reads
    - data/analyst.md
    - data/collect-headlines.md
  output_file: data/writer.md   # canonical output location
  timeout: 900                  # seconds, hard total
  retry: 0                      # external calls should set retry: 1
```

### 3.2 LLM-step extras

```yaml
  prompt_file: steps/writer.md
  model: opus                   # haiku/sonnet/opus/glm-*/gpt-*
  output_schema:                # OPTIONAL but strongly recommended
    schema_file: schemas/writer-output.json
    description: "Markdown with [heading_2]/[paragraph]/[divider] tokens; max 6 headings"
```

### 3.3 Script-step extras

```yaml
  type: script
  command: "python3 scripts/notion_blocks.py {{prev.writer.output_file}} > {{output_file}}"
  env:
    NOTION_API_KEY: "{{vault_env.NOTION_API_KEY}}"
```

Scripts run in the pipeline workspace cwd, inherit `AGENT_ID`/`TELEGRAM_NOTIFY` env vars, and write their result to `output_file`. No prompt file.

### 3.4 Validate-step extras

```yaml
  type: validate
  validates: writer             # the step whose output we're checking
  schema_file: schemas/writer-output.json
  rules_file: schemas/writer-rules.yaml   # optional regex/length rules
  on_fail: retry-writer         # retry-{step}, fail-pipeline, ignore-warning
  max_retries: 1
```

Validators report a pass/fail status the harness understands. On `retry-{step}`, the upstream LLM step re-runs with the validator's failure message appended to the original prompt — so the model sees concretely what was wrong.

### 3.5 Publish-step extras

```yaml
  type: publish
  sink: notion                  # registered sink: telegram, notion, file, http
  payload_file: data/build-payload.md
  config:
    database_id: "{{vault_env.NOTION_POSTS_DB_ID}}"
    api_key: "{{vault_env.NOTION_API_KEY}}"
  emits:                        # publish steps can emit values for downstream
    notion_url: "{{response.url}}"
    page_id: "{{response.id}}"
```

Publish steps are the **only** place external API calls happen. No exceptions.

### 3.6 Status report

When a step finishes, the executor logs its status (`completed`, `skipped`, `failed`, `retrying`) and any structured emits. Downstream steps consume these via the `{{prev.<step-id>.<field>}}` substitution — they do **not** reparse the workspace to "guess what happened."

---

## 4. Composition patterns — common shapes

These are the canonical shapes. Pick the one closest to your goal and adapt.

### 4.1 Collect → analyze → write → review → publish

The classic content pipeline. Sources are collected in parallel by `script` steps, an `llm` analyst synthesizes, an `llm` writer drafts, a `validate` step checks the draft, an `llm` reviewer suggests edits, and one or two `publish` steps deliver.

```
collect-source-a (script) ─┐
collect-source-b (script) ─┼─► analyst (llm) ─► writer (llm) ─► writer-check (validate)
collect-source-c (script) ─┘                                       │
                                                                   ├─► publish-notion (publish)
                                                                   └─► notify-telegram (publish)
```

### 4.2 Trigger → fetch → transform → publish

A reactive shape — something happened (webhook, schedule), fetch the relevant data, mechanically transform it, send it. Often zero `llm` steps.

```
fetch (script) ─► transform (script) ─► validate-payload (validate) ─► publish (publish)
```

### 4.3 Screening gate → expensive work

A cheap `script` or `llm` haiku decides whether the rest of the pipeline should run. Use the `NO_REPLY` early-exit convention so downstream steps cascade-skip when there's nothing to do.

```
scout (llm, haiku) ─► (NO_REPLY?) ─► fetch (script) ─► analyst (llm, opus) ─► publisher (publish)
```

### 4.4 Loop-until-done refinement

For iterative shaping (a writer/reviewer pair that converges), use the `loop_until` field on the LLM step. Bound it with `loop_max_iterations` and pair it with a `validate` step so the loop has a concrete stop signal beyond a fuzzy marker.

---

## 5. Always intercalate `validate` between LLM steps producing structured data

This is the single most important reliability rule in the skill. **If an `llm` step's output is consumed structurally by a downstream step — parsed, formatted, transformed, published — insert a `validate` step between them.**

```yaml
- id: writer
  type: llm
  prompt_file: steps/writer.md
  output_file: data/writer.md

- id: writer-check
  type: validate
  validates: writer
  schema_file: schemas/writer-output.json
  rules_file: schemas/writer-rules.yaml
  on_fail: retry-writer
  max_retries: 1

- id: build-payload
  type: llm
  depends_on: [writer-check]
  prompt_file: steps/build-payload.md
  output_file: data/build-payload.md
```

What the validator typically checks:

- **Structural rules** — required headers present, max paragraph count, no forbidden token markers
- **Mechanical rules** — no `~` (tilde), no `US$`, no emojis, no banned words; usually a regex list
- **Length budgets** — Notion 100-block batches, Telegram 4096 chars, etc.
- **Reference integrity** — every `[[wikilink]]` resolves, every URL is reachable (cheap HEAD)
- **Numerical sanity** — claimed price within ±X% of fetched data

**Why this matters.** LLMs drift. A reviewer step that says *"check that no `~` appears"* may catch it 90% of the time, which means it ships ten broken posts a year. A regex that says `if "~" in body: fail` catches it 100% of the time and runs in 50 ms.

**On-fail policies.** Pick one consciously:

- `retry-{step}` — re-run the upstream step with the validator's failure message appended. Use when the LLM can plausibly fix the issue itself.
- `fail-pipeline` — abort. Use when the failure means human review is required (e.g., factual contradiction with source data).
- `ignore-warning` — log but proceed. Use sparingly, only for soft signals like *"prefer 'Bitcoin' over 'BTC' in prose"*.

---

## 6. Side-effects isolation — `publish` only

External API calls and writes outside the pipeline workspace happen **only** in `publish` steps. Not in `llm` prompts. Not in `script` steps that "happen to call an API." Not in inline Python embedded in a step prompt.

### 6.1 Anti-pattern (real, taken from `crypto-bro/Routines/crypto-ta-analise/steps/publisher.md`)

```python
# Inside an LLM step prompt, the model is told to:

import urllib.request, json
NOTION_API_KEY = "READ_VALUE"
PAGE_ID = "CAPTURED_VALUE"
comment_body = json.dumps({...}).encode("utf-8")
req = urllib.request.Request(
    "https://api.notion.com/v1/comments",
    data=comment_body,
    headers={"Authorization": f"Bearer {NOTION_API_KEY}", ...},
    method="POST"
)
with urllib.request.urlopen(req) as r:
    r.read()
```

This is broken on multiple axes:

- An LLM is doing mechanical HTTP work — slow, expensive, non-deterministic.
- Credentials live in the prompt context, increasing leak surface.
- Idempotency must be hand-rolled (see the "already_published_url" guard) because the harness has no idea a write happened.
- Retry logic is ad-hoc; the harness can't help.
- The reviewer cannot test the publish path without spending real Anthropic dollars.

### 6.2 Correct pattern

```yaml
- id: build-payload
  type: llm
  prompt_file: steps/build-payload.md
  output_file: data/build-payload.md

- id: payload-check
  type: validate
  validates: build-payload
  schema_file: schemas/notion-payload.json
  on_fail: retry-build-payload

- id: publish-notion
  type: publish
  sink: notion
  depends_on: [payload-check]
  payload_file: data/build-payload.md
  config:
    database_id: "{{vault_env.NOTION_POSTS_DB_ID}}"
    api_key: "{{vault_env.NOTION_API_KEY}}"
  emits:
    notion_url: "{{response.url}}"

- id: post-comment
  type: publish
  sink: notion-comment
  depends_on: [publish-notion]
  config:
    page_id: "{{prev.publish-notion.page_id}}"
    body_file: data/reviewer-notes.md

- id: notify-telegram
  type: publish
  sink: telegram
  depends_on: [publish-notion]
  template: "Pipeline TA pronta - {{prev.publish-notion.notion_url}}"
```

The LLM produces text. The validator gatekeeps the text. The publisher sends the text. Each component does one job.

---

## 7. Single-source-of-truth for rules

Every rule that governs the pipeline's output should live in **exactly one place**. Duplication is how skills, prompts, and reviewers drift apart.

### 7.1 The smell test

If a rule like *"never write `BTC` in prose, always `Bitcoin`"* appears in:

1. The writer's step prompt
2. A skill referenced by the writer
3. The reviewer's step prompt

…that's a smell. The day you change one, the others fall out of sync, and the pipeline produces inconsistent output for weeks before someone notices.

### 7.2 Where each rule type belongs

| Rule type | Single home | Why |
|---|---|---|
| Mechanical / lexical / structural ("no tilde", "max 6 headings", "title is `Análise DD Mês`") | A `validate` step's schema file or rules file | Regex / JSON Schema is deterministic and untouched by the LLM |
| Style / narrative / voice ("explain like a beginner", "two-scenario rule") | A single skill file, referenced from one step prompt | Style is judgment, but the judgment criteria live in one document |
| Domain ("BTC dominance > 60% triggers a section") | Per-agent skill in `<agent>/Skills/` | Domain rules don't generalize, they belong to the agent that owns them |

### 7.3 The author's job during creation

While writing a pipeline, **search every step prompt for any rule**. If the same rule appears twice, consolidate before shipping. Either:

- Move the rule into a `validate` step (preferred for mechanical rules)
- Move the rule into a single skill file and reference it from the relevant step (for style rules)

Do not "just remove it from one place" — the LLM may have been depending on it. Replace with a reference.

---

## 8. Override design — when to add `accepts_overrides`

Pipelines support runtime overrides: the agent (or the user via Telegram) can pass per-run parameters that change a step's behavior without editing the pipeline file.

```yaml
- id: analyst
  type: llm
  accepts_overrides:
    focus_asset:
      type: string
      enum: [BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK]
      description: "Asset to spotlight in this run's analysis"
      default: BTC
```

When the pipeline is triggered with `{analyst: {focus_asset: "ETH"}}`, the harness:

- For `llm` steps: appends a `## Overrides for this run` section to the prompt with the resolved values
- For `script` steps: sets env vars (`STEP_OVERRIDE_FOCUS_ASSET=ETH`) before invocation
- For `publish` steps: substitutes into the `template` / `config` via `{{override.<key>}}`

### 8.1 What to expose

Add an override **only when** all of these are true:

- The attribute meaningfully changes step behavior (different output, different target, different tone)
- It is something a user or upstream agent would plausibly want to vary across runs
- The set of valid values is small or constrainable (`enum`, `range`, `regex`)

### 8.2 What NOT to expose

Do not expose internal knobs that are really config decisions:

- Model choice (`opus` vs `sonnet`) — that's a config concern, edit the pipeline
- Timeout / retry — same
- Prompt phrasing tweaks — fix the prompt
- Anything mechanical (the validator's regex list)

Overrides are **user-facing levers**, not a spillover for under-designed steps.

---

## 9. Telegram-safe stdout

The executor captures every step's stdout. By default, **only `publish` steps with declared sinks reach the user**. `llm` step stdout is logged for debugging and never auto-sent.

This means:

- Don't `print(...)` the report content from inside an LLM step prompt expecting the user to see it.
- Don't have an LLM step emit a Telegram message via `subprocess.run(["python3", os.environ["TELEGRAM_NOTIFY"], ...])` directly — replace that with a `publish` step whose sink is `telegram`.
- Status updates ("Wave 2 complete") are the harness's job, not yours. Use `notify: summary` or `notify: all` in the pipeline frontmatter if you want progress visibility.

The single exception: the `gate` step type may emit a Telegram message via `--silent` to explain *why* the pipeline is awaiting input. Even then, prefer wiring it through a publish step.

---

## 10. Example — a small well-formed pipeline

```yaml
---
title: "Daily Headlines Brief"
description: "Fetch tech headlines from 3 sources, distill the 5 most relevant into a Notion entry and a Telegram digest, every weekday at 07:30."
type: pipeline
created: 2026-05-02
updated: 2026-05-02
tags: [pipeline, news, daily]
schedule:
  days: [mon, tue, wed, thu, fri]
  times: ["07:30"]
model: sonnet
enabled: true
notify: summary
---

```pipeline
steps:
  - id: fetch-hn
    type: script
    name: "Fetch Hacker News top 30"
    command: "python3 scripts/fetch_hn.py --top 30 > {{output_file}}"
    output_file: data/fetch-hn.md
    timeout: 60
    retry: 1

  - id: fetch-techcrunch
    type: script
    name: "Fetch TechCrunch RSS"
    command: "python3 scripts/fetch_rss.py https://techcrunch.com/feed/ > {{output_file}}"
    output_file: data/fetch-techcrunch.md
    timeout: 60
    retry: 1

  - id: fetch-arstechnica
    type: script
    name: "Fetch Ars Technica RSS"
    command: "python3 scripts/fetch_rss.py https://arstechnica.com/feed/ > {{output_file}}"
    output_file: data/fetch-arstechnica.md
    timeout: 60
    retry: 1

  - id: distill
    type: llm
    name: "Distill 5 most relevant items"
    model: sonnet
    depends_on: [fetch-hn, fetch-techcrunch, fetch-arstechnica]
    prompt_file: steps/distill.md
    input:
      - data/fetch-hn.md
      - data/fetch-techcrunch.md
      - data/fetch-arstechnica.md
    output_file: data/distill.md
    output_schema:
      schema_file: schemas/distill-output.json
      description: "Markdown with exactly 5 H2 sections; each contains a 1-2 sentence body and a 'Source: <URL>' line"
    timeout: 300
    accepts_overrides:
      focus_topic:
        type: string
        description: "Optional theme to bias selection (e.g. 'AI', 'security')"

  - id: distill-check
    type: validate
    validates: distill
    schema_file: schemas/distill-output.json
    rules_file: schemas/distill-rules.yaml
    on_fail: retry-distill
    max_retries: 1

  - id: build-notion-payload
    type: script
    name: "Convert distilled markdown to Notion blocks"
    depends_on: [distill-check]
    command: "python3 scripts/notion_blocks.py {{prev.distill.output_file}} > {{output_file}}"
    output_file: data/build-notion-payload.json
    timeout: 30

  - id: publish-notion
    type: publish
    name: "Create Notion entry"
    depends_on: [build-notion-payload]
    sink: notion
    payload_file: data/build-notion-payload.json
    config:
      database_id: "{{vault_env.NOTION_HEADLINES_DB_ID}}"
      title_template: "Headlines {{today.iso_date}}"
    emits:
      notion_url: "{{response.url}}"

  - id: notify-telegram
    type: publish
    name: "Send Telegram digest"
    depends_on: [publish-notion]
    sink: telegram
    payload_file: data/distill.md
    template: |
      *Daily Headlines* - {{today.iso_date}}
      {{payload}}
      [Read on Notion]({{prev.publish-notion.notion_url}})
```

## Steps

- [[daily-headlines/steps/distill|distill]]
- [[daily-headlines/steps/distill-rules|distill-rules]]
```

Notes on this example:

- Three fetchers are `script` (deterministic HTTP) — not three LLM calls.
- Only one `llm` step (`distill`) — and its output is gated by a `validate` before anything mechanical consumes it.
- Notion conversion is a `script`, not an LLM, because `markdown → blocks` is mechanical.
- Both publishers are `publish` steps with declared sinks. No HTTP code in any prompt.
- `accepts_overrides` is exposed only on the one knob that genuinely changes per-run behavior (focus topic).

---

## 11. Refactoring example — break a monolithic LLM step

This is the canonical anti-pattern in `vault/crypto-bro/Routines/crypto-ta-analise/steps/publisher.md`. The single `publisher` step does:

- Reads three workspace files (idempotency, cover data, reviewer output)
- Computes a title in Portuguese from the system clock
- Computes a `PublishedAt` ISO timestamp in BRT
- Calls a Python script to convert markdown to Notion blocks
- Builds and posts a Notion page (HTTP)
- Posts a Notion comment with reviewer notes (HTTP)
- Extracts predictions and appends them to a registry (file write)
- Sends a Telegram message (subprocess)
- Writes an idempotency checkpoint file

…all inside one `llm` step prompt running on `haiku` for 450s. Predictably, this step is the #1 source of pipeline incidents: idempotency bugs, missing `PublishedAt` properties, duplicate Telegram messages, comment failures swallowed silently.

### 11.1 Before (one LLM step doing everything)

```yaml
- id: publisher
  type: llm  # MISTYPED — almost nothing here is creative
  model: haiku
  prompt_file: steps/publisher.md
  timeout: 450
  retry: 1
```

### 11.2 After (typed steps, validated, publish-isolated)

```yaml
- id: build-title
  type: script
  name: "Compute title and published_at from system clock"
  command: "python3 scripts/build_title_and_date.py > {{output_file}}"
  output_file: data/build-title.json
  # JSON: {"title": "Análise 02 Maio", "published_at_iso": "..."}

- id: build-cover-meta
  type: script
  name: "Parse cover step output into normalized JSON"
  depends_on: [cover]
  command: "python3 scripts/parse_cover_meta.py {{prev.cover.output_file}} > {{output_file}}"
  output_file: data/build-cover-meta.json

- id: convert-blocks
  type: script
  name: "Convert reviewer markdown to Notion blocks"
  depends_on: [reviewer]
  command: "python3 scripts/notion_blocks.py {{prev.reviewer.output_file}} > {{output_file}}"
  output_file: data/convert-blocks.json

- id: payload-check
  type: validate
  validates: convert-blocks
  schema_file: schemas/notion-payload.json
  on_fail: fail-pipeline

- id: publish-notion-page
  type: publish
  sink: notion
  depends_on: [payload-check, build-title, build-cover-meta]
  payload_file: data/convert-blocks.json
  config:
    database_id: "{{vault_env.NOTION_POSTS_DB_ID}}"
    title: "{{prev.build-title.title}}"
    properties_template: schemas/ta-properties.json
    cover_meta: "{{prev.build-cover-meta}}"
    published_at: "{{prev.build-title.published_at_iso}}"
  idempotency_key: "ta-{{today.iso_date}}"   # harness handles dedup
  emits:
    notion_url: "{{response.url}}"
    page_id: "{{response.id}}"

- id: post-review-comment
  type: publish
  sink: notion-comment
  depends_on: [publish-notion-page]
  config:
    page_id: "{{prev.publish-notion-page.page_id}}"
    body_file: data/reviewer-notes.md
  on_fail: ignore-warning   # comment failure is non-fatal

- id: extract-predictions
  type: script
  name: "Append predictions to registry"
  depends_on: [publish-notion-page]
  command: "python3 scripts/append_predictions.py --source crypto-ta-analise --post-title '{{prev.build-title.title}}' --page-id {{prev.publish-notion-page.page_id}} {{prev.reviewer.output_file}}"
  on_fail: ignore-warning

- id: notify-telegram
  type: publish
  sink: telegram
  depends_on: [publish-notion-page]
  template: |
    *{{prev.build-title.title}}*
    Rascunho publicado no Notion.
    [Ver análise]({{prev.publish-notion-page.notion_url}})
```

Now:

- Idempotency is the harness's job (`idempotency_key` field), not a hand-rolled file-parsing block.
- The title computation is testable in isolation (it's a Python script — write a unit test).
- The Notion publish is reusable across pipelines (any TA-style pipeline drops in a `publish-notion` step).
- A failing comment doesn't masquerade as a successful publish — `on_fail: ignore-warning` is explicit.
- The Telegram notification is a real `publish` step, not a `subprocess.run` hidden in an LLM prompt — so it can be mocked, replayed, and rate-limited by the harness.

---

## 12. Common mistakes — flag these in review

When reviewing a pipeline (yours or someone else's), the following are red flags:

- **Every step is `type: llm`.** A pipeline of all LLM calls is almost certainly mistyped. Real pipelines mix `script`, `llm`, `validate`, `publish` in roughly equal measure.
- **No `validate` step between an `llm` step and its consumer.** The downstream step is gambling on the LLM's structural compliance. It will fail eventually.
- **Mechanical work inside an LLM prompt.** API calls, regex transformations, JSON parsing, file conversions — if you can describe the work as "deterministic, same input gives same output," it's a `script`.
- **Side-effect calls in non-publish steps.** Telegram subprocess calls in an `llm` prompt, file writes outside the workspace from a `script` step, HTTP posts hidden in an analyst prompt.
- **Rules duplicated across prompt + skill + reviewer.** One change drifts. Consolidate to a `validate` step or a single skill.
- **No `output_file` declared.** "The model will figure out where to write" is how downstream steps fail to find input.
- **Missing `output_schema` on an LLM step that feeds a downstream step.** The downstream step is parsing free-form prose. It will break.
- **`accepts_overrides` exposing config knobs.** Model name, timeout, retry should not be runtime overrides — those are pipeline-author decisions.
- **`depends_on` on a step the current step doesn't actually read from.** Implicit "for safety" dependencies serialize the DAG and kill parallelism.
- **A `gate` step without an explicit timeout / abandonment policy.** Human-in-the-loop steps need a "what if no one clicks for 24 hours" answer.
- **Pipeline frontmatter says `notify: all` for a 12-step daily pipeline.** That's 12 Telegram messages every morning. Use `summary` or `final`.
- **Idempotency hand-rolled inside a step prompt.** The `publish` step's `idempotency_key` field is the right place.
- **Identical step names like `collect`, `analyze`, `publish` across many pipelines.** Step IDs become file paths and graph nodes — make them unique and meaningful (`collect-binance`, `analyze-headlines`).

---

## 13. Checklist before declaring the pipeline complete

Self-check every box before merging or scheduling. If any is uncertain, pause and resolve.

- [ ] Every step has a `type:` field, and the type matches the work (re-applied the decision tree in section 2.1)
- [ ] No `llm` step contains mechanical instructions (HTTP calls, regex, JSON parsing, format conversion)
- [ ] No `llm` step sends output to an external sink — only `publish` steps do
- [ ] Every `llm` step that produces structured output has a `validate` step downstream of it
- [ ] Every step declares `input` (when applicable) and `output_file`
- [ ] Every `publish` step has a registered sink and explicit config
- [ ] No rule appears in two places — mechanical rules live in `validate` schemas/rules files; style rules live in one skill file
- [ ] `accepts_overrides` is used only for genuine user-facing levers, not config knobs
- [ ] External calls (`script` HTTP, publish steps) have `retry: 1` or higher
- [ ] Timeouts are proportional: collectors short, analysts long, publishers short
- [ ] The DAG maximizes parallelism — independent steps share no `depends_on` chain
- [ ] No wikilinks inside step prompt files (parent owns the `## Steps` graph relationship)
- [ ] No frontmatter inside step prompt files (they are raw prompts)
- [ ] `notify:` is set deliberately (`final`, `summary`, `all`, `none`) not by default
- [ ] If the pipeline runs unattended (cron-scheduled), failure modes are explicit: every `validate` step has an `on_fail`, every external call has retry, every `gate` step has an abandonment policy
- [ ] Scratch a 30-second test: if the LLM steps all returned empty strings, would the pipeline cleanly fail (with a useful error) or silently corrupt downstream data?

If everything passes, the pipeline is ready. If even one item is uncertain, fix it before scheduling — flaky pipelines steal far more time downstream than the fix costs upfront.
