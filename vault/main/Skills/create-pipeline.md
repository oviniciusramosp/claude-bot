---
title: Create or Review Multi-Agent Pipeline
description: Skill for creating or reviewing pipelines with multiple parallel steps. Proactively analyzes parallelism opportunities and anti-patterns in existing pipelines.
type: skill
created: 2026-04-08
updated: 2026-04-12
trigger: "when the user wants to create, review, improve, or optimize a pipeline, routine with multiple steps, routine with sub-agents, or multi-step workflow"
tags: [skill, pipeline, routine, automation, multi-agent, review, parallelism]
---

## Modes of operation

This skill operates in two modes:

1. **Creation** — when the user wants to create a new pipeline
2. **Review** — when the user wants to review, improve, or optimize existing pipelines

Detect the mode from the conversation context. If ambiguous, ask.

---

## Creation Mode

### What is a pipeline

A pipeline is a routine of type `type: pipeline` that orchestrates multiple steps (sub-agents). Unlike a simple routine (one prompt → one Claude → one output), a pipeline:

- Has multiple steps, each with its own model (haiku/sonnet/opus)
- Steps can depend on others (`depends_on`) — respecting a DAG
- Steps without dependencies run in parallel automatically
- All steps of a pipeline run with `cwd = vault/<owning-agent>/.workspace/data/<pipeline-id>/`. Each step writes its output to `<step-id>.md` inside that folder and can read outputs from previous steps by path. The `.workspace/` prefix is a dotfile so Obsidian hides runtime pipeline data from the graph view automatically.
- The Python orchestrator manages execution, retries, and timeouts
- Only the step marked with `output: telegram` sends the final result

### File structure

The pipeline definition and its step prompt files live inside the owning agent's `Routines/` folder:

```
vault/<owning-agent>/Routines/
  {pipeline-name}.md              ← definition (frontmatter + ```pipeline block)
  {pipeline-name}/                ← folder with step prompts
    steps/
      {pipeline-name}-{step-1-id}.md   ← step 1 prompt (unique basename)
      {pipeline-name}-{step-2-id}.md   ← step 2 prompt
      ...
```

**Step file naming convention (v3.4+).** Prefix every step prompt file with `{pipeline-name}-` so the basename is unique vault-wide. Example: the `scout` step of pipeline `crypto-news` lives at `crypto-news/steps/crypto-news-scout.md`. Obsidian resolves bare wikilinks (`[[crypto-news-scout]]`) to unique basenames — if two pipelines both had a `scout.md`, one of them would resolve to the wrong file.

**Runtime data output.** At execution time the bot creates `vault/<owning-agent>/.workspace/data/{pipeline-name}/` and each step writes its result to `<step-id>.md` inside that folder. The bot manages this directory automatically — you don't create it or reference it from the step prompts.

### Steps to create

#### 1. Understand the objective

What should the pipeline produce at the end? What intermediate steps are needed?

#### 2. Decompose into steps with maximum parallelism

This is the most important step. The goal is to maximize parallelism and minimize total time.

**Principle: if two steps do not depend on each other's output, they MUST run in parallel.**

For each step, determine:
- `id`: kebab-case slug (e.g., `collect-data`, `analyze`, `write`)
- `name`: human-readable name (e.g., "Collect market data")
- `model`: haiku (fast/cheap), sonnet (balanced), opus (complex)
- `depends_on`: list of step ids that must complete before this one runs
- `timeout`: total time limit in seconds (default: 1200 = 20min)
- `inactivity_timeout`: inactivity time limit in seconds (default: 300 = 5min)
- `retry`: number of attempts on failure (default: 0)
- `output: telegram`: mark on the LAST step that produces the final output

**Ralph loop (optional) — iterate a step until a marker appears:**

Steps can loop-until-done via the Ralph technique. Use this for iterative refinement where the agent progresses across iterations. Syntax is flat inside the step:

```pipeline
steps:
  - id: refine
    name: Iteratively refine draft
    model: opus
    prompt_file: steps/refine.md
    loop_until: "DRAFT_READY"
    loop_max_iterations: 5
    loop_on_no_progress: abort
```

Fields:
- `loop_until`: substring that marks "done". When this string appears in the step output, the loop exits successfully. Omit (or leave empty) to disable looping
- `loop_max_iterations`: max loop iterations (default: 5, hard cap: `MAX_LOOP_ITERATIONS = 10`)
- `loop_on_no_progress`: `abort` (default) fails the step if two consecutive iterations produce identical output; `continue` keeps looping regardless

Behavior:
- Each iteration prepends the previous output as context to the next iteration's prompt so the agent can make progress
- Reaching `loop_max_iterations` without finding the marker is an ERROR — the step fails with a clear message
- Cancellation (`/stop`) aborts the loop immediately

**Model rules by step type:**
- Data collection → `haiku` (fast, cheap, good for APIs and scraping)
- Analysis / creative writing → `opus` (best reasoning, more expensive)
- Review / validation → `sonnet` or `opus` (depends on complexity)
- Publishing / API calls → `sonnet` or `haiku` (mechanical tasks)

#### 3. Apply parallelism rules (CRITICAL)

Analyze the proposed steps and proactively apply these rules:

**Rule 1 — Atomic collector: never create a monolithic collector.**
If a step needs to fetch data from 3+ independent sources (APIs, websites, databases), split it into parallel sub-steps — one per source or group of related sources.

BAD example:
```
[collector: fetches Binance + CoinGecko + Yahoo + GitHub] → [analyst]
```
Time: sum of all fetches (sequential).

GOOD example:
```
[collect-binance] ──┐
[collect-coingecko]─┤
[collect-yahoo] ────┼→ [analyst]
[collect-github] ───┘
```
Time: max of one fetch (parallel). Up to 4x faster.

**Rule 2 — Parallel assets with analysis.**
If the pipeline generates assets (cover, charts, images) that don't depend on the full analysis, run them in parallel with the analysis — not after.

BAD example:
```
[collect] → [analyst] → [cover] → [writer]
```

GOOD example:
```
[collect] → [analyst] → [writer]
[collect] → [cover] ─────────────→ [publisher]
```
Cover and analyst run in parallel because both depend only on collect.

**Rule 3 — Minimum dependency.**
Each step should only depend on the steps whose output it actually needs to read. Never depend on a step "for safety" if you won't use its output.

**Rule 4 — Retry on collectors.**
Steps that make external calls (APIs, scraping, webhooks) should have `retry: 1` at minimum. Transient failures are common and should not kill the entire pipeline.

**Rule 5 — Proportional timeouts.**
- Collectors (curl/API): 120-300s timeout, 120s inactivity
- Analysis (opus thinking): 600-900s timeout, 300s inactivity
- Writing (opus generating long text): 600-900s timeout, 300s inactivity
- Review: 300-600s timeout, 180s inactivity
- Publishing (API calls): 120-180s timeout, 60s inactivity

#### 4. Present visual DAG to the user

Before creating the files, show the proposed DAG in visual format:

```
Wave 1 (parallel):
  collect-source-a  ──┐  haiku, ~30s
  collect-source-b  ──┤  haiku, ~30s
  collect-source-c  ──┘  haiku, ~30s

Wave 2 (parallel):
  analyst  ←── all collectors    opus, ~3min
  cover    ←── collect-source-a  sonnet, ~1min

Wave 3:  writer    ←── analyst           opus, ~5min
Wave 4:  reviewer  ←── writer            opus, ~3min
Wave 5:  publisher ←── reviewer + cover  sonnet, ~1min

Estimated total time: ~13min (vs ~25min sequential)
```

Ask if the user approves or wants to adjust.

#### 5. Ask for schedule

Same options as a routine: times (HH:MM), days, end date.

#### 6. Generate name

Convert the objective to kebab-case.

#### 7. Create the main file

`vault/<owning-agent>/Routines/{name}.md`:

```yaml
---
title: "{descriptive title}"
description: "{short phrase about the pipeline}"
type: pipeline
created: {YYYY-MM-DD}
updated: {YYYY-MM-DD}
tags: [pipeline, {categories}]
schedule:
  times: ["{HH:MM}"]
  days: [{days}]
model: {default model}
enabled: true
agent: {agent if applicable}
notify: final
---

```pipeline
steps:
  - id: {step-1-id}
    name: "{Step 1 Name}"
    model: {model}
    prompt_file: steps/{step-1-id}.md
    timeout: {timeout}
    inactivity_timeout: {inactivity}
    retry: {retry}

  - id: {step-2-id}
    name: "{Step 2 Name}"
    model: {model}
    depends_on: [{step-1-id}]
    prompt_file: steps/{step-2-id}.md

  - id: {final-step-id}
    name: "{Final Step Name}"
    model: {model}
    depends_on: [{previous-step-id}]
    prompt_file: steps/{final-step-id}.md
    output: telegram
```

## Steps

- [[{name}/steps/{step-1-id}|{step-1-id}]]
- [[{name}/steps/{step-2-id}|{step-2-id}]]
- [[{name}/steps/{final-step-id}|{final-step-id}]]
```

**About the `## Steps` section:** this is a graph artifact that owns the parent→step edges in the Obsidian graph. List the steps in execution order (parallel collectors first, dependent steps after). The macOS app regenerates this automatically when saving a pipeline; when you create a pipeline via this skill, you write it once at creation. Step files MUST NOT contain backlinks to the parent — see `vault/CLAUDE.md` "Pipeline graph" section.

**Additional optional fields in frontmatter:**

- `context: minimal` — skips the vault system prompt (Tooling, Journal, etc.). Useful when pipeline steps don't need vault knowledge and you want to save tokens and gain speed. Ideal for purely technical pipelines (data collection, transformation, delivery).
- `voice: true` — in addition to sending the final output as text on Telegram, also sends it as audio (TTS). Useful for newsletters, morning briefings, or any output the user wants to hear rather than read.

#### 8. Create the steps folder

`vault/<owning-agent>/Routines/{name}/steps/`

#### 9. Create a prompt file for each step

`vault/<owning-agent>/Routines/{name}/steps/{name}-{step-id}.md` — note the `{name}-` prefix that makes basenames unique vault-wide (see the File structure section above).

IMPORTANT about step prompts:
- DO NOT mention file sharing — the orchestrator already injects workspace instructions automatically
- DO NOT instruct the step to read or write to `data/` — this is automatic
- Focus only on the step's TASK: "Analyze the collected data and produce a technical analysis"
- The step automatically receives: list of available files, instruction on where to write output
- Write short and direct prompts — the pipeline context is already injected by the orchestrator
- **NO frontmatter** in step files — they are read as raw prompts
- **NO wikilinks anywhere** in step files — `[[...]]` syntax can leak into the LLM response and break downstream parsing. The parent→step relationship lives in the parent pipeline file's `## Steps` section, not in the step (parent owns the relationship)
- When a step needs to mention another step's output file, use the plain path: `data/<other-step>.md` — never wrap it in wikilink brackets

**When to add an `## Expected Output` section to step prompts:**

If a step's output is consumed by a downstream step (i.e., another step has `depends_on` pointing to it), include an `## Expected Output` section at the end of the step prompt file. This is critical for pipeline reliability — downstream steps need to parse the output, and ambiguous formats cause cascading failures.

The section should describe:
- **Format**: JSON, key-value, markdown with specific headers, free text
- **Key fields/sections**: what will be present and what each means
- **Approximate size**: one-liner, short block, or multi-section document

Skip it for the final step (`output: telegram`) since nothing downstream consumes its output.

Example step prompt with output contract:

```
You are a market data collector. Fetch spot prices and 24h changes for BTC, ETH, and SOL.

Use the available API tools to collect current data. Report only factual data — never invent values.

## Expected Output

Write to the output file in this format:

=== BTC ===
Price: $XX,XXX.XX
24h: +/-X.XX%

=== ETH ===
Price: $X,XXX.XX
24h: +/-X.XX%

=== SOL ===
Price: $XXX.XX
24h: +/-X.XX%

=== Collected at YYYY-MM-DD HH:MM UTC ===

The analyst step will parse these sections by header (=== TOKEN ===).
```

This pattern is already proven in production — step prompts that define their output format (like the scout/write-review chain in crypto-news) have significantly more reliable downstream parsing than those that don't.

#### 10. Let the index regenerate itself

The owning agent's `vault/<agent>/Routines/agent-routines.md` has a `vault-query:start` marker block that auto-picks up any new pipeline on the next `scripts/vault_indexes.py` run (or the daily `vault-indexes-update` routine, or manual `/indexes` on Telegram). No manual editing.

#### 11. Record in the Journal

Append to today's journal with details of the created pipeline.

#### 12. Confirm

Inform the user of the created pipeline, how many steps it has, which ones run in parallel, and when the next execution will be.

---

## Full example: Weekly Newsletter

Objective: pipeline that every Monday researches 3 sources (blog, Reddit, Hacker News), writes a newsletter, reviews it, and sends it by email.

### Main file: `vault/main/Routines/weekly-newsletter.md` (example assumes the pipeline belongs to Main)

```yaml
---
title: "Weekly Tech Newsletter"
description: "Weekly pipeline that researches 3 sources, drafts a newsletter, and sends it by email"
type: pipeline
created: 2026-04-09
updated: 2026-04-09
tags: [pipeline, newsletter, tech]
schedule:
  times: ["08:00"]
  days: [mon]
model: sonnet
enabled: true
notify: final
---

```pipeline
steps:
  - id: collect-blogs
    name: "Collect blog posts"
    model: haiku
    prompt_file: steps/collect-blogs.md
    timeout: 180
    inactivity_timeout: 120
    retry: 1

  - id: collect-reddit
    name: "Collect Reddit posts"
    model: haiku
    prompt_file: steps/collect-reddit.md
    timeout: 180
    inactivity_timeout: 120
    retry: 1

  - id: collect-hn
    name: "Collect Hacker News posts"
    model: haiku
    prompt_file: steps/collect-hn.md
    timeout: 180
    inactivity_timeout: 120
    retry: 1

  - id: write-newsletter
    name: "Draft newsletter"
    model: opus
    depends_on: [collect-blogs, collect-reddit, collect-hn]
    prompt_file: steps/write-newsletter.md
    timeout: 600
    inactivity_timeout: 300

  - id: review
    name: "Review newsletter"
    model: opus
    depends_on: [write-newsletter]
    prompt_file: steps/review.md
    timeout: 300
    inactivity_timeout: 180

  - id: send-email
    name: "Send by email"
    model: haiku
    depends_on: [review]
    prompt_file: steps/send-email.md
    timeout: 120
    inactivity_timeout: 60
    output: telegram
```

## Steps

- [[weekly-newsletter/steps/collect-blogs|collect-blogs]]
- [[weekly-newsletter/steps/collect-reddit|collect-reddit]]
- [[weekly-newsletter/steps/collect-hn|collect-hn]]
- [[weekly-newsletter/steps/write-newsletter|write-newsletter]]
- [[weekly-newsletter/steps/review|review]]
- [[weekly-newsletter/steps/send-email|send-email]]
```

### Visual DAG

```
Wave 1 (parallel):
  collect-blogs  ──┐  haiku, ~30s
  collect-reddit ──┤  haiku, ~30s
  collect-hn     ──┘  haiku, ~30s

Wave 2:  write-newsletter ←── all collectors   opus, ~5min
Wave 3:  review           ←── write-newsletter  opus, ~2min
Wave 4:  send-email       ←── review            haiku, ~30s

Estimated total time: ~8min (vs ~15min sequential)
```

### Step prompt example: `steps/write-newsletter.md`

```markdown
You are a technology newsletter writer.

Read the data collected from the 3 sources and write a concise newsletter with:
- 5-7 highlights of the week, prioritized by relevance and novelty
- For each highlight: title, 2-3 sentence summary, and original link
- Tone: informative but accessible, without unnecessary jargon
- Format: Markdown with headers and bullet points

## Expected Output

# Weekly Tech Newsletter — YYYY-MM-DD

## 1. [Highlight title]
[2-3 sentence summary of the highlight, covering what happened and why it matters.]
Source: [URL]

## 2. [Highlight title]
[2-3 sentence summary.]
Source: [URL]

... (up to 7 highlights)

The review step will check structure, tone, and factual accuracy of each highlight.
```

Note that the prompt does NOT mention `data/`, input file paths, or instruct about the workspace — all of that is injected automatically by the orchestrator. The `## Expected Output` section is optional but recommended for steps whose output feeds a downstream step — it acts as a contract that prevents parsing failures.

---

## Review Mode

Triggered when the user asks to review, improve, or optimize existing pipelines.

### Step 1 — Identify scope

- If the user mentioned a specific pipeline → review only that one
- If they asked for a general review → iterate every `vault/<agent>/Routines/*.md` across all agent folders and filter to `type: pipeline`

### Step 2 — Analyze each pipeline

For each pipeline, read the main file and all step prompts. Evaluate using the checklist below.

**Review checklist:**

#### A. Parallelism

- [ ] **Monolithic collector?** — Does one step collect data from 3+ sources? Suggest splitting into parallel sub-collectors.
- [ ] **100% sequential chain?** — Do all steps depend on the previous one? Check if any could run in parallel (e.g., cover in parallel with analysis).
- [ ] **Excessive dependencies?** — Does any step depend on another without using its output? Remove the dependency.
- [ ] **Assets in series?** — Does image/cover/chart generation wait for analysis to finish? If it doesn't need the analysis output, parallelize.

#### B. Models

- [ ] **Haiku for collection?** — Steps that only do curl/API calls should use `haiku`, never `opus`.
- [ ] **Opus for analysis/writing?** — Steps that require deep reasoning or creativity should use `opus`.
- [ ] **Expensive model on a simple task?** — Mechanical steps (publish, send, format) don't need `opus`.

#### C. Resilience

- [ ] **Retry on collectors?** — Steps with external calls should have `retry: 1` at minimum.
- [ ] **Adequate timeout?** — Is >300s excessive for collectors? Is <300s insufficient for opus steps?
- [ ] **Inactivity timeout?** — Steps without explicit `inactivity_timeout` use the default (300s). Collectors should have 120s. Publishing 60s.

#### D. Prompts

- [ ] **Step prompt mentions `data/`?** — Remove it. The orchestrator injects this automatically.
- [ ] **Too generic a prompt?** — Vague instructions like "analyze the data" without specifying WHAT to analyze.
- [ ] **Prompt too long?** — If >500 words, consider whether everything is necessary.
- [ ] **Missing output contract?** — Does a non-final step lack an `## Expected Output` section? If downstream steps parse its output, add one.

#### E. Execution history

- Read `~/.claude-bot/routines-state/YYYY-MM-DD.json` (last 2-3 days)
- Check for recurring failures, which steps fail, and with what error
- Actual timeouts vs configured — if the step is being killed by the timeout, adjust it
- If a collector is taking too long, it's a candidate for parallel split

### Step 3 — Present recommendations

For each analyzed pipeline, present:

```
### {pipeline-name}

**Current structure:**
[step1] → [step2] → [step3] → [step4]
Estimated time: ~Xmin (sequential)

**Suggested improvements:**

1. ⚡ **Parallelize collection** — split [step1] into 3 parallel sub-collectors
   Gain: collection from ~5min to ~1min

2. 🔄 **Add retry** — [step1] and [step3] make external calls without retry
   Gain: resilience against transient failures

3. 🧠 **Adjust model** — [step3] uses opus but only formats text (sonnet is enough)
   Gain: ~40% faster and cheaper

**Proposed structure:**
[sub-collect-a] ──┐
[sub-collect-b] ──┼→ [analyst] → [writer] → [publisher]
[sub-collect-c] ──┘
Estimated time: ~Ymin (Zx faster)
```

### Step 4 — Apply approved improvements

Ask which improvements the user wants to apply. For each approved one:

- **Collector split** → create new step files, update pipeline definition, remove old step
- **Model/timeout/retry change** → edit the pipeline definition
- **Prompt rewrite** → edit the step file, show diff to the user
- **DAG reorganization** → update `depends_on` on the affected steps

When modifying a pipeline:
1. Update the `updated` field in frontmatter
2. Keep old step files until confirming the new ones work (or delete if the user approves)
3. Record changes in the Journal

### Step 5 — Record in the Journal

Append to today's journal with the applied changes.

---

## Anti-patterns (quick reference)

| Anti-pattern | Problem | Solution |
|-------------|---------|---------|
| Monolithic collector | One step fetches 10 APIs sequentially | Split into N parallel sub-collectors |
| Fully linear chain | A → B → C → D → E with no parallelism | Identify independent steps and parallelize |
| Opus for curl | Expensive model making trivial HTTP calls | Use haiku for collection |
| No retry on API calls | Transient failures kill the pipeline | retry: 1 on steps with external calls |
| Uniform timeout | All steps with 1200s | Adjust by type: short for collectors, long for analysis |
| Sequential cover | Cover generation waits for entire analysis | Parallelize if cover only depends on raw data |
| Prompt with `data/` | Step mentions workspace | Remove — orchestrator injects automatically |
| Wikilink in step file | `[[...]]` leaks to LLM, pollutes graph | Keep step prompts free of wikilinks; parent owns the `## Steps` section |

---

## Notes

- The scheduler automatically detects `type: pipeline` and uses the PipelineExecutor
- Pipelines run with a persistent workspace at `vault/<owning-agent>/.workspace/data/<pipeline-name>/` — the dotfile prefix keeps it out of Obsidian's graph view. Pipelines without an owning agent fall back to a temporary `/tmp/claude-pipeline-{name}-{timestamp}/data/` directory (rare — every agent, including Main, has its own `.workspace/` by default)
- Each step is an independent Claude CLI subprocess (they don't share a session)
- If a step fails and has `retry > 0`, it is re-executed
- If a step fails without retry, all dependent steps are marked as SKIPPED
- Timeouts: `inactivity_timeout` kills idle steps (no output), `timeout` is the hard total limit
- The `notify` field controls Telegram notifications: `final` (output only), `all` (each step), `summary`, `none`
- Failures ALWAYS notify on Telegram regardless of the mode
