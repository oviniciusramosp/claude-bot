---
title: Pipeline v2 Specification
description: Architecture spec for typed steps, explicit I/O contract, runtime overrides, display statuses, failure injection, and Telegram leak prevention. Source of truth for executor v2 implementation.
type: note
created: 2026-05-02
updated: 2026-05-02
tags: [spec, pipeline, architecture, orchestration, infrastructure]
---

[[main/Notes/agent-notes|Notes]]

This document is the canonical specification for **Pipeline v2** — the next iteration of the bot's pipeline architecture. It is the source of truth that drives implementation. When a Pipeline v2 implementation choice diverges from this document, this document loses (i.e., update the spec first, then the code).

The current production implementation lives in `/Users/viniciusramos/claude-bot/claude-fallback-bot.py`. Key reference points used throughout this spec:

- `PipelineStep` (line 1238) — step dataclass
- `PipelineTask` (line 1284) — pipeline dataclass
- `PipelineExecutor` (line 5168) — main orchestrator
- `PipelineExecutor.execute()` (line 5229) — pipeline entrypoint
- `PipelineExecutor._execute_step()` (line 5623) — single-step driver
- `PipelineExecutor._run_dag_loop()` (line 5462) — wave scheduler with cascade-skip
- `_session_start_recall()` (line 3283) — first-turn `## Recent Context` injector
- `_is_no_reply_output()` (line 1214) — soft-skip sentinel detector
- `_inject_temp_parent_link()` (line 1501) — `[[<agent>/agent-temp|Temp]]` prepender

A reference v1 pipeline is `/Users/viniciusramos/claude-bot/vault/crypto-bro/Routines/crypto-ta-analise.md`.

## 1. Motivation

### 1.1. What's broken in v1

- **Every step is an LLM call.** Even mechanical work (calling Notion, running a regex linter, sending Telegram, scraping a public REST endpoint) goes through Claude. The result is slow, expensive, and non-deterministic. The `crypto-ta-analise` pipeline today spends Opus minutes on a `reviewer` step whose job is mostly "grep for forbidden tokens, count paragraphs."
- **No step contract.** The executor reads `data/<step>.md` after the fact and infers what happened. A step that wrote partial output, fell through, or returned `NO_REPLY` looks the same on disk as one that succeeded with empty content. The cascade-skip logic in `_run_dag_loop` patches this with sentinel detection (`_is_no_reply_output`), but the underlying problem is that a step has no honest way to say "I ran and decided not to publish — here's why."
- **Rule duplication.** "No tilde", "max 3 paragraphs", "only h2/h3 headings" are restated across the step prompt, the reviewer prompt, and any associated skill. Drift between copies means inconsistent enforcement: the writer adds an H1, the reviewer's prompt copy got updated last week to permit H1s, but the publisher prompt still asserts no-H1, and now the bot crashes at the wrong layer.
- **Telegram leakage by convention only.** The current rule is "set `output: none` on internal steps and tell the LLM not to print to stdout." Both are conventions; nothing physically prevents a chatty step from dumping its scratchpad to the user. A bug in `_notify_success` or a misbehaving prompt is one keystroke away from a leak.
- **Steps cannot be parameterized at runtime.** The pipeline definition is a static YAML inside a markdown file. The user cannot say "Crypto Bro, roda a TA com foco em ETH" and have the analyst step receive `focus_asset: ETH`. The only way today is to edit the prompt file in-place, which is racy and unfair to scheduled runs that fire at the same moment.
- **Failures are silent to the owning agent.** When a pipeline fails (or completes with a meaningful skip), the user gets a Telegram notification — but the **agent that owns the pipeline** never learns about it. The next time the user opens a session with crypto-bro, crypto-bro has no idea his TA blew up at 21:32. The user has to re-explain the failure manually.
- **Pipeline status drifts across surfaces.** The Python `RoutineStateManager` writes JSON. The Swift `ClaudeBotManager` reads it and re-derives a status string. The web dashboard does its own re-derivation in JavaScript. Three implementations of "is this pipeline scheduled, running, succeeded, or failed today?" — and they disagree at the edges (is `soft_success` a success? is `cancelled` a failure? does a `Scheduled` future run today override a `Skipped` morning run?).

### 1.2. What v2 enables

- **Mechanical work runs deterministically.** Notion calls, regex validation, Telegram publishing — all become `script`/`validate`/`publish` steps that don't spawn an LLM. The TA pipeline reviewer becomes a `validate` step that runs in milliseconds and returns structured feedback.
- **Single source of truth for rules.** A `validate` step is the canonical enforcement of "no tilde", "max 3 paragraphs". The writer's prompt may *describe* the rules, but only the validate step *enforces* them. Drift is impossible because the failing validation IS the rule.
- **Telegram leak prevention is structural.** The executor captures stdout. Stdout reaches Telegram only via an explicit `publish` step. A misbehaving LLM cannot leak.
- **Explicit step I/O contract.** Every step ends with a JSON status report. The executor never guesses again.
- **Agents trigger their own pipelines with overrides.** "Roda com foco em ETH" → crypto-bro produces `{analyst: {focus_asset: "ETH"}, writer: {focus_asset: "ETH"}}` → executor validates → executor injects.
- **Failures land in the owning agent's context.** Next session with crypto-bro starts with "I see the TA failed at 21:32 in step `analyst` — want me to look?"
- **One status enum, three surfaces.** Defined in Python, mirrored in Swift and JS, with a CI check for parity.

## 2. Step types

Step typing is the single biggest lever in this redesign. Today every step is implicitly `llm`. v2 introduces five types as a first-class field.

| Type | Purpose | Spawns process | Determinism | Example |
|---|---|---|---|---|
| `llm` | Run Claude/Codex/GLM CLI with a prompt | Yes (LLM subprocess) | Non-deterministic | analyst, writer, cover generation |
| `script` | Run a Python/shell script with structured input | Yes (script subprocess) | Deterministic | Binance API call, RSS fetch, CSV transform |
| `validate` | Lint/schema-check the previous step's output | Yes (script subprocess) | Deterministic | regex for forbidden tokens, paragraph count, JSON schema check |
| `publish` | Send output to a sink (Telegram, Notion, file, external API) | Yes (script subprocess) | Deterministic | `scripts/notion_blocks.py`, `scripts/telegram_notify.py` |
| `gate` | Wait for human review (manual approval) | No (blocks executor thread) | Mixed | manual_review for sensitive outputs |

**Backward compatibility.** When `type` is omitted in the YAML, the executor defaults to `llm`. Every existing pipeline file in the vault keeps working without modification.

### 2.1. `llm` — generative work

Identical to today's behaviour: the executor builds a prompt, spawns the appropriate runner via `_make_runner_for(step.model)` (line 5657 in the current `_execute_step`), waits for completion under the dual-timeout guard, captures `result_text`, and writes the output file.

```yaml
- id: analyst
  type: llm
  name: "Technical and macro analysis"
  model: opus
  prompt_file: steps/analyst.md
  depends_on: [collect-binance, collect-sentiment, collect-macro]
  timeout: 900
  retry: 1
```

**Status report production.** For backward compat, an `llm` step is allowed to:

1. Emit no JSON at all. The executor synthesizes `{"status": "ready", "output_file": "data/<step>.md"}` if the file exists with non-empty content.
2. Emit `NO_REPLY` (existing soft-skip sentinel — `_is_no_reply_output` covers variants). The executor synthesizes `{"status": "skipped", "reason": "NO_REPLY"}`.
3. Emit a fenced JSON block as the LAST element of the response, in which case the executor honors it verbatim.

This means existing v1 step prompts continue to work. New step prompts can opt into explicit reporting by ending with a fenced JSON block.

### 2.2. `script` — deterministic data work

A `script` step replaces an `llm` step that was doing mechanical work. The executor invokes the script as a subprocess, with the same workspace, agent, and pipeline context, but **without** an LLM in the loop.

```yaml
- id: collect-binance
  type: script
  name: "Binance Collection (spot + futures)"
  command: "python3 scripts/collect_binance.py"
  timeout: 120
  retry: 2
  output_file: data/<pipeline>/collect-binance.json
  accepts_overrides:
    symbols:
      type: array
      items: {type: string}
      default: ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
```

The executor sets these env vars before invoking:

| Env var | Value |
|---|---|
| `PIPELINE_NAME` | `task.name` |
| `PIPELINE_AGENT` | `task.agent` |
| `PIPELINE_DATA_DIR` | absolute path to the pipeline's `data/<task.name>/` |
| `PIPELINE_STEP_ID` | `step.id` |
| `PIPELINE_STEP_OUTPUT_FILE` | absolute path of the file the script should write |
| `PIPELINE_RUN_ID` | unique per-run identifier (e.g., epoch-secs + 6-hex) |
| `PIPELINE_TIME_SLOT` | `task.time_slot` |
| `STEP_OVERRIDE_<KEY>` | one per declared `accepts_overrides` field, value JSON-stringified for non-string types |

The script's `stdout` is captured and used as the status report (last line is parsed as JSON; everything before is logged). The script's `stderr` is logged at `WARNING` level. Exit code is honored: non-zero implies `status: failed` even if no JSON was emitted.

### 2.3. `validate` — schema/lint enforcement

A `validate` step takes the output of a previous step (declared via `validates`) and runs a deterministic check. Its purpose is to be the single source of truth for content rules.

```yaml
- id: writer-validate
  type: validate
  name: "Enforce writer rules"
  command: "python3 scripts/validate_ta_writer.py"
  validates: writer
  depends_on: [writer]
  timeout: 30
  on_failure: fail   # "fail" | "feedback" | "warn"
```

`validates: <step_id>` is sugar for "the file under validation is `data/<task.name>/<step_id>.md`". The path is exposed to the script as `PIPELINE_VALIDATION_TARGET`.

**`on_failure` semantics.**

- `fail` (default) — a failed validation aborts the pipeline. Status report is `status: failed`. Behaves like a v1 hard error.
- `feedback` — a failed validation is converted into a *retry signal* for the validated step. The validate step's status report contains a `feedback` field (string). The executor re-runs the validated step (incrementing `step.retry` once) with the feedback appended to the prompt as a `## Validation feedback from previous attempt` section. Maximum one feedback retry per validate step per run, to bound cost. After the retry, validation runs again and `on_failure: feedback` is downgraded to `fail` for that pass.
- `warn` — a failed validation is logged at `WARNING` and recorded in the status report, but the pipeline continues. Used for non-blocking style checks.

A passing validation emits `status: ready` and the executor proceeds.

### 2.4. `publish` — sinks

A `publish` step sends the output of an upstream step to an external destination. It is the **only** step type allowed to talk to the outside world (Telegram, Notion, HTTP, file-system outside the pipeline workspace).

```yaml
- id: publish-notion
  type: publish
  name: "Publish to Notion"
  command: "python3 scripts/notion_blocks.py"
  publishes: writer
  depends_on: [writer-validate]
  timeout: 120
  retry: 2
  sink: notion   # "telegram" | "notion" | "file" | "http" | "custom"
  sink_config:
    database_id_env: NOTION_DATABASE_ID
    parent_page_env: NOTION_PARENT_PAGE
```

`publishes: <step_id>` exposes the published file path as `PIPELINE_PUBLISH_SOURCE`. `sink_config` is a free-form dict whose keys the publish script can interpret; the executor passes it as `STEP_PUBLISH_<KEY>` env vars (matching the override env var convention).

**The 3-condition gate (see also section 7).** A `publish` step actually emits to its sink only if:

1. The step's `sink` is declared in YAML (no implicit Telegram).
2. The step's status report is `status: ready` after running.
3. The content sent to the sink is the contents of `output_file` (not the raw stdout/stderr).

Stdout from a publish script is logs, not message body.

### 2.5. `gate` — manual review

A `gate` step pauses the pipeline and waits for human approval via Telegram. This is a generalization of today's `manual: true` flag (line 1264 of `PipelineStep`).

```yaml
- id: review-before-publish
  type: gate
  name: "Manual review before Notion"
  reviews: writer
  depends_on: [writer]
  manual_timeout: 86400  # 24h default
  tunnel: true
```

The executor's `_execute_manual_step` continues to handle the Telegram message + web tunnel flow. The gate's status report is one of `{ready, skipped, failed}`:

- Approved → `ready` (downstream proceeds with the gated content)
- Rejected → `skipped` with `reason: "rejected by user"` (downstream cascade-skips per the existing NO_REPLY-cascade logic)
- Timeout → `failed` with `reason: "manual review timed out after Ns"`

## 3. Step contract (I/O)

Every step terminates by emitting a structured **status report**. The report is the executor's canonical signal — it is what the state machine reads to decide what happens next. The current `_execute_step` infers status by checking `output_file.exists() and stat().st_size > 0` (line 5774); v2 replaces inference with explicit declaration.

### 3.1. JSON schema

```json
{
  "status": "ready" | "skipped" | "failed",
  "output_file": "data/<pipeline>/<step>.md" | null,
  "reason": "human-readable explanation",
  "metrics": {
    "duration_ms": 12345,
    "tokens_in": 0,
    "tokens_out": 0,
    "cost_usd": 0.0
  },
  "feedback": "string for type=validate when on_failure=feedback",
  "metadata": {}
}
```

| Field | Required | Description |
|---|---|---|
| `status` | yes | `ready` (success, output ready for downstream), `skipped` (intentional no-op, downstream may cascade-skip), `failed` (hard error, retry or abort) |
| `output_file` | when `status == ready` | Path RELATIVE to `PIPELINE_DATA_DIR`. Must exist with non-empty content when status is `ready`. May be omitted/null for `skipped` and `failed`. |
| `reason` | when `status != ready` | Required for `skipped` and `failed` so `_skip_reasons` (line 5204) and `_step_errors` (line 5201) capture intent. Optional for `ready`. |
| `metrics` | no | Optional, populated by runners that have telemetry (LLM token counts, script duration). Used by the cost dashboard. |
| `feedback` | when `validate.on_failure=feedback` | The feedback string injected into the validated step's retry prompt. |
| `metadata` | no | Free-form dict for step-specific data (e.g., a `script` step might emit `{"rows_written": 1234}`). Surfaced in logs but not interpreted by the executor. |

### 3.2. Per-type fulfillment

#### `llm` steps

The LLM is not required to emit JSON. Backward-compat mode applies:

- If the response ends with a fenced ` ```json ... ``` ` block whose content parses, the executor uses it.
- Otherwise, if `_is_no_reply_output(result)` is true (existing helper at line 1214), executor synthesizes `{"status": "skipped", "reason": "NO_REPLY"}`.
- Otherwise, if `output_file` exists with content, executor synthesizes `{"status": "ready", "output_file": "..."}`.
- Otherwise, executor synthesizes `{"status": "failed", "reason": "Step produced no output"}`.

Step prompts MAY be updated to end with an explicit JSON block; the executor extracts and removes the block from the file before downstream steps read it (so the published markdown is clean).

#### `script` / `validate` / `publish` steps

The script's `stdout` is captured. The **last line** of stdout (after stripping trailing whitespace) MUST be the JSON status report. Everything before the last line is logged at `INFO` to `bot.log` for debugging.

If the last line does not parse as JSON, the executor falls back to:

- exit code 0 + non-empty `output_file` → synthesize `{"status": "ready", "output_file": "..."}`
- exit code 0 + empty `output_file` → synthesize `{"status": "skipped", "reason": "Empty output, no JSON report"}`
- exit code != 0 → synthesize `{"status": "failed", "reason": "Exit code N, no JSON report"}`

This fallback exists to make scripts tolerant during development. New scripts should always emit JSON explicitly.

#### `gate` steps

Status is set by the manual review handler in the bot, not by an external process. The gate emits one of:

```json
{"status": "ready", "output_file": "data/<pipeline>/<reviewed-step>.md", "reason": "approved"}
{"status": "skipped", "reason": "rejected by user"}
{"status": "failed", "reason": "manual review timed out after 86400s"}
```

### 3.3. Reading the report — executor responsibility

`_execute_step` (renamed `_execute_step_v2` during transition) parses the report into the in-memory state:

```python
report = parse_status_report(stdout_or_response)
with self._lock:
    if report["status"] == "ready":
        self._step_status[step.id] = "completed"
        self._step_outputs[step.id] = read_output_file(report["output_file"])
    elif report["status"] == "skipped":
        self._step_status[step.id] = "skipped"
        self._skip_reasons[step.id] = report["reason"]
    elif report["status"] == "failed":
        self._step_status[step.id] = "failed"
        self._step_errors[step.id] = report["reason"]
```

The cascade-skip logic in `_run_dag_loop` (line 5462) keeps working unchanged because it operates on `_step_status` values; v2 just feeds it more accurate inputs.

## 4. Override schema (`accepts_overrides`)

Overrides are runtime parameters delivered by the caller (slash command, scheduled trigger, or agent NL trigger). They let a single static pipeline definition handle many invocations.

### 4.1. YAML declaration

Each step declares the attributes it accepts as a JSON-schema-flavoured dict:

```yaml
- id: analyst
  type: llm
  prompt_file: steps/analyst.md
  accepts_overrides:
    focus_asset:
      type: string
      enum: ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "DOGE", "AVAX", "LINK"]
      description: "Which asset to spotlight in this run's analysis"
    depth:
      type: string
      enum: ["quick", "normal", "deep"]
      default: "normal"
      description: "How deep the technical analysis goes"
    include_macro:
      type: boolean
      default: true
```

Supported types: `string`, `integer`, `number`, `boolean`, `array` (with `items: {type: ...}`), `object` (free-form dict, no nested validation in v2).

### 4.2. Delivery mechanism per step type

| Step type | Delivery |
|---|---|
| `llm` | Appended to the prompt as a `## Overrides for this run` section containing the JSON values. The prompt-builder injects this AFTER the base prompt body but BEFORE downstream-step output context. |
| `script`, `validate`, `publish` | One env var per override: `STEP_OVERRIDE_<UPPER_SNAKE_KEY>=<json-string>`. Strings are stored unquoted; non-strings are JSON-encoded so the script can parse with `json.loads(os.environ[...])` if needed. Booleans are `"true"` / `"false"` for ergonomic shell use. |
| `gate` | Surfaced in the Telegram review message as a "Run parameters" block so the human sees what was requested. |

### 4.3. Validation flow

The executor validates incoming overrides BEFORE any step runs. The pipeline-level `validate_overrides(task, overrides)` function:

1. For each `step_id` in the overrides dict, check that the step exists. Unknown step IDs → reject the entire run.
2. For each `attr` in the step's overrides dict, check it appears in the step's declared `accepts_overrides`. Unknown attrs → reject the entire run.
3. For each declared attr, type-check against the schema. Mismatches → reject the entire run.
4. Apply defaults for declared-but-unprovided attrs.
5. Reject NaN, Infinity, and oversized strings (>4 KB) defensively.

A rejection returns a structured error to the caller (slash command sees a Telegram error message; agent NL trigger sees the error in its subprocess stderr). The pipeline never starts.

### 4.4. Agent NL → overrides flow

The user says "Crypto Bro, roda a TA com foco em ETH". The crypto-bro session:

1. Reads `vault/crypto-bro/Routines/crypto-ta-analise.md` to find the steps that accept `focus_asset`.
2. Builds the overrides dict: `{"analyst": {"focus_asset": "ETH"}, "writer": {"focus_asset": "ETH"}}`.
3. Invokes `python3 scripts/run_pipeline.py crypto-ta-analise --overrides '<json>'`.
4. The runner script calls into the bot's pipeline-spawning helper (today: `_enqueue_pipeline`) with overrides attached to the run.

The agent does NOT call the executor in-process. The trigger is always out-of-band so the agent's own LLM session doesn't block waiting for a 20-min pipeline to finish.

### 4.5. Conflict policy

If two callers attempt to start the same pipeline within the same time slot with different overrides, the executor follows the existing single-run-per-slot rule (`set_pipeline_status` deduplication): the second call is rejected with a clear "Pipeline already running for this slot" error. Overrides do not change slot identity.

## 5. Pipeline display statuses

The state of a pipeline is read by three surfaces today: the bot's Telegram replies, the macOS `ClaudeBotManager` app (Swift), and the web dashboard (JavaScript). These three implementations have drifted. v2 declares ONE enum and propagates it.

### 5.1. The enum

| Status | Condition |
|---|---|
| `Idle` | No run today AND no schedule.times remaining today AND no schedule.interval would fire before midnight |
| `Scheduled` | At least one upcoming `schedule.times` slot today, OR the next `schedule.interval` boundary lands today |
| `Running` | The executor's `_step_status` dict has at least one step in `running` (or the pipeline-level state is `running`) |
| `Success` | Most recent run today has `final_status` in `{completed, soft_success}` AND a `publish` step (or `output: telegram`) actually emitted |
| `Failed` | Most recent run today has `final_status == failed` OR `final_status == cancelled` |
| `Skipped` | Most recent run today has `final_status` in `{completed, soft_success}` BUT no publish/output step emitted (NO_REPLY cascade reached the sink) |

Priority when multiple conditions could match: `Running > Failed > Success > Skipped > Scheduled > Idle`.

### 5.2. Composition algorithm

```python
def pipeline_display_status(name: str, today: date, state: RoutineStateManager) -> str:
    runs_today = state.runs_for(name, today)
    if any(r.final_status == "running" for r in runs_today):
        return "Running"
    most_recent = runs_today[-1] if runs_today else None
    if most_recent:
        if most_recent.final_status in ("failed", "cancelled"):
            return "Failed"
        if most_recent.final_status in ("completed", "soft_success"):
            return "Skipped" if most_recent.publish_emitted is False else "Success"
    if has_pending_schedule_today(name, now=now()):
        return "Scheduled"
    return "Idle"
```

`runs_today` is sorted by start time. `publish_emitted` is a new boolean recorded by the executor at finalization time: it is true iff at least one step with `type: publish` (or v1 `output: telegram`) emitted to its sink. This boolean removes the current `output_skipped` heuristic at line 5314.

### 5.3. Single source of truth

The enum is defined once in Python:

```python
# claude-fallback-bot.py
class PipelineDisplayStatus(str, Enum):
    IDLE = "Idle"
    SCHEDULED = "Scheduled"
    RUNNING = "Running"
    SUCCESS = "Success"
    FAILED = "Failed"
    SKIPPED = "Skipped"
```

Mirrored verbatim in:

- `ClaudeBotManager/Sources/Models/PipelineDisplayStatus.swift` — Swift enum with raw `String` values
- `web/index.html` — JS object literal `const PIPELINE_DISPLAY_STATUS = {IDLE: "Idle", ...}`

A CI test (`tests/test_pipeline_status_parity.py`) parses all three files and asserts the enum members + raw values are identical. A diff in any direction fails the build.

The composition algorithm is duplicated across surfaces (the bot reads `state.json` directly from Python; Swift and JS read the same file via the dashboard API). The CI parity test does NOT require algorithm parity — it just locks the enum values. Surfaces are free to derive the status from state in their own idiomatic way, as long as they map to the same six values.

## 6. Failure injection into agent context

When a pipeline fails (or skips for a non-trivial reason), the owning agent learns about it the next time it starts a session. This closes the loop: the user no longer has to re-explain "your TA failed at 21:32 last night."

### 6.1. The block format

On finalization, the executor appends a structured block to `vault/<owning-agent>/agent-temp.md`:

```markdown
## pipeline_failure

- pipeline: crypto-ta-analise
- step: analyst
- ran_at: 2026-05-02T21:32:14-03:00
- run_id: 1746234734-a3f9c2
- reason: "Step 'analyst' returned status='failed': RuntimeError: Step analyst exceeded 900s hard limit (ran 901s)"
- final_status: failed
- state_path: ~/.claude-bot/routines-state/2026-05-02.json
- last_step_output: data/crypto-ta-analise/analyst.md
- overrides: {"analyst": {"focus_asset": "ETH"}}
- pipeline_display_status: Failed
```

For SKIPPED runs that publish nothing (NO_REPLY cascade reached the sink), the block uses the same shape with `final_status: completed-skipped` and `pipeline_display_status: Skipped`. For pure success runs, the block is NOT appended.

When multiple failures stack up before the agent reads them, each appends its own `## pipeline_failure` block. The agent sees all of them in chronological order.

### 6.2. SessionStart integration

`_session_start_recall` (line 3283) currently injects a `## Recent Context` block from the FTS index. v2 extends it: BEFORE the FTS search, it reads `vault/<agent>/agent-temp.md` and looks for `## pipeline_failure` blocks. If any exist, it prepends a `## Pipeline status` block to the user prompt:

```markdown
## Pipeline status

The following pipeline runs need your attention since the last session:

- crypto-ta-analise — Failed at 2026-05-02T21:32:14-03:00 in step `analyst`
  reason: Step 'analyst' returned status='failed': RuntimeError: Step analyst exceeded 900s hard limit
  state_path: ~/.claude-bot/routines-state/2026-05-02.json
  last_step_output: vault/crypto-bro/data/crypto-ta-analise/analyst.md

When responding, briefly acknowledge the failure(s) and ask the user whether to investigate, retry, or ignore. Do not silently proceed without a one-sentence acknowledgement.
```

The block is injected only on the first turn of a fresh session (same condition as the existing `## Recent Context` injector). Resumed sessions (`session_id is not None`) do not get re-prompted — they already saw the failure on their first turn.

### 6.3. Clearing mechanism

Each `## pipeline_failure` block carries `run_id`. The agent has three ways to clear a block:

1. **Explicit acknowledgement command.** The bot exposes a slash command `/ack <run_id>` (or via inline keyboard on the failure notification). Clicking it removes the matching `## pipeline_failure` block from `agent-temp.md`.
2. **Agent self-clearance.** When the agent's response acknowledges a specific `run_id` (detected via a magic string in the response, e.g., `<ack-pipeline run_id="1746234734-a3f9c2"/>`), a post-turn hook in `_run_claude_prompt()` strips the matching block. The magic string is also stripped from the user-visible response.
3. **Re-run success.** When a fresh run of the same pipeline completes with `Success`, all prior `## pipeline_failure` blocks for that pipeline are auto-cleared. The user implicitly told the bot "the problem is resolved" by triggering a successful run.

Mechanism #1 is canonical. #2 is the ergonomic path (agent does it without the user noticing). #3 is the safety net.

## 7. Telegram leak prevention

Stdout is captured. The user sees content via Telegram only through an explicit, gated path.

### 7.1. The 3-condition gate

The executor sends content to Telegram (or any sink) only if ALL three conditions hold:

1. **Declared sink.** The step is `type: publish` with a non-empty `sink` field, OR (v1 backward-compat) the step's `output_to_telegram == True` (today: `output: telegram`).
2. **Step succeeded.** The step's status report is `status: ready`.
3. **Content from output_file.** The bytes sent to the sink are the contents of `output_file`. Stdout/stderr captured during the step run are diverted to `bot.log` only — they NEVER form the message body.

Any step that does not meet all three is silent to Telegram. Stray prints from an `llm` or `script` step are logs, not messages.

### 7.2. Capture mechanism

For `script`/`validate`/`publish` steps, the executor invokes the subprocess with `stdout=PIPE, stderr=PIPE`. Stdout is buffered, the last-line JSON parsed as the status report, and the rest written to `bot.log` at `INFO` with `pipeline=<name> step=<id>` prefix. Stderr is written at `WARNING`.

For `llm` steps, the runner already captures `result_text` and `accumulated_text` separately (today: line 5720). v2 adds an explicit step that writes `result_text` to `output_file` BEFORE any sink decision is made — this guarantees the file is the single source of truth, not the runner's in-memory buffer.

### 7.3. v1 fields kept for backward compat

`output: telegram` and `output: none` continue to work. Internally, v2 maps:

- `output: telegram` → synthesized `publish` step appended after the original step, with `sink: telegram` and `publishes: <step_id>`. Existing pipelines run identically.
- `output: none` → no synthesis. Same as today.
- `output: file` (default) → no synthesis. Output stays inside `data/`.

This synthesis is internal — the YAML on disk is unchanged. When migrating a pipeline to `version: 2`, authors are encouraged to make the publish step explicit, but they are not forced to until they want to take advantage of `sink_config`, `publishes`, or `accepts_overrides` on the publish step.

## 8. Orchestrator as contract

A core principle: there is no single "orchestrator entity." There is a CONTRACT, and several components honor it. Any component that respects the contract — the Python executor, a future Rust executor, an agent invoking the runner script, a unit test — can drive the same pipeline and produce the same result.

### 8.1. The five properties

1. **Central state machine — deterministic, never an LLM.** The Python executor (today: `PipelineExecutor`) is the single source of truth for step status, retry, checkpoint, cascade-skip. It contains zero LLM calls. Adding an LLM here is a bug. State transitions are pure functions of `(current_state, step_report)`.

2. **Step contract.** Section 3. Every step type honors the JSON status report. The executor never reads stdout to "guess what happened" or globs `data/` to "see if a file appeared." It reads the report.

3. **Workspace as transport.** `data/<pipeline>/` is the channel between steps. Rules:
   - Step N writes `data/<pipeline>/<step-N>.md` (or whatever it declared in `output_file`).
   - Step N+1 reads `data/<pipeline>/<step-N>.md` if it depends on step N.
   - Steps NEVER read each other's stdout. NEVER read each other's logs. NEVER read each other's prompts.
   - The data dir is per-pipeline-per-run-resumable: the same dir is reused across resume attempts (today: `self.workspace / "data" / self.task.name`).

4. **Sinks isolated.** Only `publish` steps talk to the outside world. `llm`/`script`/`validate`/`gate` steps NEVER call Telegram, NEVER call Notion, NEVER call external HTTP endpoints (except for read-only data collection inside `script` steps, where the data is fetched into the workspace, not pushed out).

5. **Validators between LLM steps.** Any LLM output that becomes input to another LLM step SHOULD pass through a `validate` step first. This is a strong recommendation, not a hard enforcement — but pipelines that skip it accept that LLM-to-LLM drift is their problem.

### 8.2. Why this matters

When all 5 are in place, "who triggered this run" stops being a special case. The slash command `/run` calls `executor.execute()`. The cron tick calls `executor.execute()`. The agent's NL trigger calls `executor.execute()`. The unit test calls `executor.execute()`. The system behaves identically because the contract is identical.

## 9. Triggering modes

### 9.1. Manual slash

```
/run crypto-ta-analise
/run crypto-ta-analise --overrides '{"analyst": {"focus_asset": "ETH"}}'
```

The bot's `cmd_run` parses `--overrides` as JSON. Validation happens in `validate_overrides()` (section 4.3). On error, the user sees a Telegram message:

```
❌ Pipeline crypto-ta-analise: invalid overrides
   Step 'foo' is not a step of this pipeline.
   Valid steps: collect-binance, collect-sentiment, ..., publish-notion
```

On success, the pipeline starts and the user sees the standard live-progress message.

### 9.2. Scheduled

YAML frontmatter `schedule.times` / `schedule.interval` / `schedule.days` / `schedule.monthdays` works exactly as today. The cron-style scheduler (`_pipeline_scheduler_thread` and friends) calls `executor.execute()` with no overrides. Defaults declared in `accepts_overrides` are applied.

A future enhancement (out of scope for v2 initial cut) is `schedule.overrides` in frontmatter — letting a routine declare "run at 09:00 with focus_asset=BTC, then again at 21:30 with focus_asset=ETH". For v2, only one schedule per pipeline file is supported.

### 9.3. Agent natural-language trigger

The agent reads the user's message, decides a pipeline should run, builds an overrides dict, and invokes:

```bash
python3 /Users/viniciusramos/claude-bot/scripts/run_pipeline.py \
  crypto-ta-analise \
  --agent crypto-bro \
  --overrides '{"analyst": {"focus_asset": "ETH"}, "writer": {"focus_asset": "ETH"}}' \
  --triggered-by "agent:crypto-bro"
```

`scripts/run_pipeline.py` is a new thin wrapper that POSTs to a control endpoint already exposed by the bot (or, if no endpoint is yet exposed, writes a request file under `~/.claude-bot/pipeline-requests/` and the bot's main loop drains it). Either way, the executor invocation is the same `executor.execute()` path; the agent is fire-and-forget.

The agent does NOT block on the pipeline. It returns to the user "Pipeline started — run_id 1746234734-a3f9c2. I'll let you know when it finishes." The eventual completion notification flows through the existing `_notify_success`/`_notify_failure` path AND through the `agent-temp.md` `## pipeline_failure` block on failure (so the next session sees it too).

### 9.4. Trigger metadata in state

Every run records who triggered it:

```json
{
  "run_id": "1746234734-a3f9c2",
  "triggered_by": "manual:user|schedule:cron|agent:crypto-bro|test:unit",
  "trigger_args": {"overrides": {...}, "slot": "21:30"}
}
```

This metadata is surfaced in the dashboard, useful for debugging "why did this fire?"

## 10. What already exists

The current `PipelineExecutor` is the foundation v2 builds ON. The following capabilities are reused unchanged unless explicitly noted:

| Capability | Current location |
|---|---|
| DAG execution with parallel waves | `_run_dag_loop` (line 5462) |
| Resume from checkpoint | `_resumed`/`resume_state` (line 5178) and `vault_checkpoint_create` |
| Per-step retry (`retry: N`) | `_step_attempts` (line 5202), retry loop in `_execute_step` |
| Step states `completed/failed/skipped/cancelled` | `_step_status` (line 5199) |
| Soft success via NO_REPLY cascade | `_is_no_reply_output` (line 1214), cascade logic in `_run_dag_loop` |
| Notification modes `final/all/summary/none` | `_notify_success`, `_notify_failure`, `_send_progress_message` |
| Output capture `output_type` and `output_file` | `PipelineStep.output_type`, `PipelineStep.output_file` (line 1249) |
| Manual review gate | `_execute_manual_step` (called from `_execute_step`, line 5630) |
| Loops (Ralph) | `_execute_loop_step`, `loop_until`/`loop_max_iterations` (line 1260) |
| Dual timeout (inactivity + hard) | `_execute_step` lines 5684-5715 |
| Workspace fallback (temp dir) | `PipelineExecutor.__init__` lines 5183-5190 |
| Path locking on output file | `_output_file_locks` (line 5215) |
| Activity sidecar | `_write_step_activity` (line 5394), `_remove_step_activity` |
| Agent-temp parent link injection | `_inject_temp_parent_link` (line 1501) |
| Provider routing per step (Anthropic/GLM/Codex) | `_make_runner_for(step.model)` |
| Vault checkpoint create/restore/drop | `vault_checkpoint_*` helpers |

What v2 ADDS:

- `type` field on `PipelineStep` (with default `llm` for backward compat)
- `command`/`script` fields for non-LLM steps
- `sink`/`sink_config`/`publishes`/`validates`/`reviews` fields
- `accepts_overrides` schema validation + delivery
- `validate_overrides()` pre-flight check
- Status-report parsing in `_execute_step`
- `publish_emitted` bool in pipeline state
- `PipelineDisplayStatus` enum + Swift/JS mirror
- `## pipeline_failure` block writer + reader
- `/ack <run_id>` command + `<ack-pipeline/>` magic string handler
- Stdout capture via PIPE for non-LLM steps

What v2 EXTENDS:

- `_session_start_recall` — adds `## Pipeline status` block ahead of `## Recent Context`
- `_finalize_progress` — sets `publish_emitted` based on actual sink emission
- `cmd_run` — accepts `--overrides` JSON

## 11. Migration strategy

v2 ships behind a feature flag with per-pipeline opt-in. v1 and v2 coexist until every pipeline is migrated.

### 11.1. Feature flag

```bash
# ~/claude-bot/.env
PIPELINE_V2_ENABLED=true
```

When `PIPELINE_V2_ENABLED=false` (default during initial rollout), the executor ignores `version: 2` and runs every pipeline on the v1 path. This is the kill-switch.

When `PIPELINE_V2_ENABLED=true`, pipelines are dispatched per-file based on frontmatter.

### 11.2. Per-pipeline opt-in

A pipeline opts into v2 by adding `version: 2` to its frontmatter:

```yaml
---
title: "Análise Técnica Diária"
type: pipeline
version: 2
schedule:
  times: ["21:30"]
agent: crypto-bro
---
```

Pipelines without `version: 2` (or with `version: 1`) run on the legacy v1 code path unchanged. The pipeline parser in `_parse_pipeline_block` (around line 2254) inspects the version and routes to either `PipelineExecutor` (v1) or `PipelineExecutorV2`.

### 11.3. Rollout plan

1. **Phase 0 — spec freeze.** This document is reviewed and accepted. Open questions (section 12) get user decisions.
2. **Phase 1 — executor scaffolding.** `PipelineExecutorV2` ships with `script`/`validate`/`publish`/`gate` types implemented. Unit tests cover the status-report parser, override validator, and the parity test for `PipelineDisplayStatus`. No production pipeline is migrated yet. Feature flag stays false in `.env.example` but true in dev `.env`.
3. **Phase 2 — first migration.** `crypto-ta-analise` migrates to `version: 2`. Reviewer becomes `validate`. Publisher becomes `publish`. Collect steps stay `llm` initially (data collection from public APIs is one judgement call away from being a `script`; we leave it `llm` for one full week to compare runs).
4. **Phase 3 — second migration.** `crypto-news-produce` and one parmeirense pipeline migrate. By now the v2 path has logged a few hundred runs and the contracts have shaken out.
5. **Phase 4 — bulk migration.** All remaining pipelines flip to `version: 2`. Feature flag default flips to `true` in `.env.example`.
6. **Phase 5 — v1 removal.** After two full weeks with all pipelines on v2 and zero rollback events, the v1 code path is deleted in a single commit. The feature flag is removed.

Each phase ships behind a version bump per `versioning.md` (PATCH for internal scaffolding, MINOR when first user-visible pipeline migrates, MAJOR for v1 deletion).

### 11.4. Test parity during transition

`tests/test_pipeline_executor_v2.py` runs every migrated pipeline on a fixture vault and asserts:

- Same `final_status` as the v1 baseline
- Same `_step_status` per step (modulo new types)
- Same `publish_emitted` bool (true iff sink fired)
- Same Telegram/Notion side-effects (recorded by stub sinks, verified by message counts)

If the parity test fails for a migrated pipeline, the migration is rejected.

## 12. Open questions

These are points where the spec is intentionally vague, where competing reasonable choices exist, or where a user decision is required before implementation begins. Each one needs a yes/no or a pick-one before phase 1 starts.

**Q1. How does a `## pipeline_failure` block get cleared?** Section 6.3 lists three mechanisms (slash command, magic string, re-run success). Should v2 ship all three on day one, or pick one canonical path? Recommendation: ship #1 (slash command) for explicit control, plus #3 (re-run success) as an automatic safety net. Defer #2 (magic string) to a later iteration — the magic string adds prompt complexity that may not be worth the ergonomic win.

**Q2. What happens if two `accepts_overrides` declarations conflict?** Example: both the `analyst` step and the `writer` step declare `focus_asset: BTC` as default, but the caller passes `{"analyst": {"focus_asset": "ETH"}}` and omits `writer`. Should `writer` see `BTC` (its own default) or `ETH` (inherited from the upstream override)? Recommendation: each step is isolated; `writer` sees its own default unless explicitly overridden. The agent that calls the pipeline is responsible for spreading overrides across steps that need them. This mirrors the slash-command surface, where the user types one JSON dict.

**Q3. Should `validate` steps run by default after every `llm` step, or be opt-in?** Strong recommendation says yes (section 8.1, property 5). But "default" here is operationally messy: existing pipelines have no validators, and forcing a validator on every existing `llm` step would block migrations. Recommendation: opt-in only. Document the recommendation in the migration guide and in the `create-pipeline` skill so new pipelines pick it up.

**Q4. Where do `script` step files live?** Three options: (a) inside the pipeline's folder, e.g., `vault/<agent>/Routines/crypto-ta-analise/scripts/collect_binance.py`; (b) in a global `scripts/` directory, e.g., `scripts/crypto/collect_binance.py`; (c) wherever the YAML's `command` field points, with no enforced convention. Recommendation: (b) for shared infrastructure scripts (like `notion_blocks.py`, `telegram_notify.py`), (a) for pipeline-specific scripts that don't generalize. Enforce by lint: a `command:` whose first arg starts with `vault/` outside the pipeline's own folder fails the linter.

**Q5. Are pipeline `script` steps allowed to import from the bot's own module (`claude-fallback-bot.py`)?** This would let a script reuse `_inject_temp_parent_link`, `vault_index` upsert helpers, etc. Risk: the bot's module is not designed as a library and its top-level imports take time. Recommendation: forbid by lint. Scripts that need vault helpers import from `scripts/vault_index.py` (already a library) or from a future `scripts/lib/` package. This decouples step scripts from bot internals.

**Q6. Do `accepts_overrides` defaults override the prompt's default phrasing?** Example: the analyst prompt says "Focus on BTC unless otherwise specified." If the schema declares `focus_asset` with `default: "BTC"`, the override section is always appended ("Overrides for this run: focus_asset=BTC"), so the prompt sees the redundant statement. Recommendation: the prompt MAY assume any declared override will be present in the override section, with its default value if not user-provided. Authors should write prompts that read the override section as the source of truth and remove ambient defaults. Not a hard rule — soft guidance in the `create-pipeline` skill.

**Q7. How are LLM steps' embedded JSON status reports stripped from the output file before downstream steps read them?** If the LLM ends with a fenced JSON block, the executor parses it but the file under `data/<step>.md` still contains the block. Downstream steps would see "garbage at the end." Recommendation: after parsing, the executor rewrites the file with the JSON block removed (and trailing whitespace trimmed). Authors testing locally see the JSON during development; once parsed, it's gone.

**Q8. When the executor synthesizes a `publish` step from v1 `output: telegram`, where does the message go for forum-thread routing?** Today, `output: telegram` for a routine on a secondary chat with a thread-mapped agent goes to the right thread because `_notify_success` reads the agent's `chat_id`/`thread_id`. v2 should preserve this. Recommendation: the synthesized `publish` step inherits its routing from the agent's frontmatter, identical to today. No new YAML field needed.

**Q9. Should `script` step subprocess timeouts use the same dual-timeout as `llm` (inactivity + hard)?** Scripts don't have an LLM's "stuck thinking" failure mode but they can hang on a slow API. Recommendation: hard timeout only (`timeout` field). Inactivity is meaningless for a script that does one POST and waits for a response. Document this in the `script` step section of `create-pipeline`.

**Q10. What does `pipeline_display_status: Skipped` mean in the failure block when the run produced no notification?** A SKIPPED pipeline is not a failure in the operational sense — the user didn't WANT a publication. Should the agent be told? Recommendation: append a `## pipeline_skip` block (NOT `## pipeline_failure`) with the same shape but a different header. The SessionStart injector treats them differently: pipeline_failure → strong "you must acknowledge"; pipeline_skip → light "FYI, the daily TA had nothing to publish today (probably no market action)." This way the agent isn't blamed for a normal operating state.

**Q11. What is the Swift `PipelineDisplayStatus` decoded from?** The bot writes `~/.claude-bot/routines-state/YYYY-MM-DD.json` with the new fields (`publish_emitted`, `final_status`). Swift currently reads this file and synthesizes a status string. With the v2 enum, Swift could decode the status directly from a new field (`pipeline_display_status: "Success"`) instead of re-deriving. Recommendation: write the enum value into the JSON as `pipeline_display_status` AND keep the underlying state fields. Swift and JS consumers can either trust the precomputed value (simple path) or re-derive (defensive path). The CI parity test only locks the enum members, not the consumer logic, so both paths remain viable.

**Q12. Is `version: 2` the right opt-in marker?** Alternatives: `pipeline_version`, `engine: v2`, a separate file extension. Recommendation: stick with `version: 2`. It's terse, common in YAML conventions, and aligns with the spec naming. Avoid magic strings in the `engine` field — that field today implies LLM provider (`engine: claude`) at the step level, and reusing it at the pipeline level would confuse readers.
