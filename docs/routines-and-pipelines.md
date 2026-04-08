# Routines & Pipelines Guide

This document covers automated task execution: simple routines (single-step scheduled prompts) and pipelines (multi-step DAGs with parallel execution).

## Routines

A routine is a scheduled prompt that the bot executes automatically at specified times. Each routine is a `.md` file in `vault/Routines/` with YAML frontmatter defining the schedule and a markdown body containing the prompt.

### Routine Format

```yaml
---
title: "Morning BTC Price"
description: "Sends the current Bitcoin price via Telegram every day at 8:30."
type: routine
created: 2026-04-07
updated: 2026-04-07
tags: [routine, crypto, daily]
schedule:
  days: ["*"]
  times: ["08:30"]
model: haiku
agent: crypto-bro
enabled: true
---

[[Routines]]

Your prompt text goes here. This is what gets sent to Claude Code
when the routine triggers. It can be multiple paragraphs and include
code blocks, instructions, etc.
```

### Frontmatter Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `title` | Yes | string | Human-readable name |
| `description` | Yes | string | Short description for scanning/filtering |
| `type` | Yes | string | Must be `routine` (or `pipeline` for multi-step) |
| `schedule` | Yes | object | Scheduling configuration (see below) |
| `model` | Yes | string | Claude model to use: `sonnet`, `opus`, or `haiku` |
| `enabled` | Yes | boolean | Whether the routine is active |
| `agent` | No | string | Agent ID to run under (changes workspace to agent's directory) |
| `created` | Yes | date | Creation date (YYYY-MM-DD) |
| `updated` | Yes | date | Last modified date |
| `tags` | Yes | list | Tags for categorization |

### Schedule Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `times` | list | (required) | Execution times in HH:MM format (24h, local time) |
| `days` | list | `["*"]` | Days of the week: `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`, or `["*"]` for every day |
| `until` | string | (none) | Expiry date in YYYY-MM-DD format (routine stops after this date) |

### Execution Flow

1. The `RoutineScheduler` runs in a background thread, checking `vault/Routines/*.md` every 60 seconds
2. For each enabled routine file, it validates required frontmatter fields (`title`, `type`, `schedule`, `model`, `enabled`)
3. It checks if the current day matches the `days` field
4. It checks if the current time (HH:MM) matches any entry in `times`
5. It checks the daily state file to avoid re-executing a routine that already ran at this time slot
6. If all checks pass, the routine is enqueued for execution
7. The prompt body is sent to Claude Code with the configured model and workspace
8. Execution status is tracked in the daily state file

Routines do not block interactive messages -- they are enqueued and processed alongside user requests.

## Creating Routines

### Via Telegram

Use the `/routine` command, which triggers the `create-routine` skill. The skill walks you through defining the schedule, model, and prompt interactively.

### Manually

Create a `.md` file directly in `vault/Routines/` with the proper frontmatter format. File names should be in kebab-case (e.g., `morning-report.md`).

Requirements:
- Must have complete YAML frontmatter with all required fields
- Must have `[[Routines]]` as the first line of the body (for Obsidian graph)
- Prompt text follows the wikilink

## Pipelines

A pipeline is a multi-step routine that orchestrates several Claude Code invocations as a directed acyclic graph (DAG). Steps can run in parallel when they have no dependencies, and outputs from earlier steps are automatically available to later ones.

### Pipeline Format

Pipeline files live in `vault/Routines/` with `type: pipeline` in frontmatter. The prompt body contains a fenced code block tagged `pipeline` with the step definitions in YAML:

```yaml
---
title: "Crypto Analysis Pipeline"
description: "Daily crypto analysis with data collection, analysis, and publishing."
type: pipeline
created: 2026-04-08
updated: 2026-04-08
tags: [pipeline, crypto, daily]
schedule:
  times: ["21:30"]
  days: ["*"]
model: sonnet
agent: crypto-bro
enabled: true
notify: final
---

[[Routines]]
```

````
```pipeline
steps:
  - id: collector
    name: "Collect data"
    model: sonnet
    prompt_file: steps/collector.md
    timeout: 300
    inactivity_timeout: 120

  - id: analyst
    name: "Technical analysis"
    model: opus
    depends_on: [collector]
    prompt_file: steps/analyst.md
    timeout: 600
    inactivity_timeout: 300

  - id: publisher
    name: "Publish results"
    model: sonnet
    depends_on: [analyst]
    prompt_file: steps/publisher.md
    timeout: 120
    output: telegram
```
````

### Step Prompts

Each step's prompt lives in a separate file under `Routines/{pipeline-name}/steps/{id}.md`. The directory structure:

```
Routines/
  my-pipeline.md                    # Pipeline definition
  my-pipeline/
    steps/
      collector.md                  # Prompt for the "collector" step
      analyst.md                    # Prompt for the "analyst" step
      publisher.md                  # Prompt for the "publisher" step
```

### Step Properties

| Property | Required | Default | Description |
|----------|----------|---------|-------------|
| `id` | Yes | -- | Unique slug in kebab-case |
| `name` | Yes | -- | Human-readable step name |
| `model` | No | pipeline's model | Claude model override for this step |
| `prompt_file` | Yes* | -- | Path to prompt file, relative to the pipeline directory |
| `prompt` | No | -- | Inline prompt text (fallback if `prompt_file` not found) |
| `depends_on` | No | `[]` | List of step IDs that must complete before this step runs |
| `agent` | No | pipeline's agent | Agent override for this step |
| `timeout` | No | `1200` | Hard wall-clock timeout in seconds |
| `inactivity_timeout` | No | `300` | Max seconds without any Claude output before killing the step |
| `retry` | No | `0` | Number of retry attempts on failure |
| `output` | No | -- | Set to `telegram` to mark this step's output for the final notification |
| `engine` | No | `"claude"` | Execution engine (reserved for future use) |

## Pipeline Execution

The `PipelineExecutor` class handles pipeline runs using wave-based parallelism.

### Wave-Based Parallelism

1. The executor identifies all steps whose dependencies are fully satisfied
2. These "ready" steps launch in parallel (each in its own thread)
3. When a wave completes, the executor checks for newly ready steps
4. This repeats until all steps reach a terminal state (completed, failed, or skipped)

### DAG Cycle Detection

Before execution begins, the scheduler performs a DFS-based cycle detection on the dependency graph. If a cycle is found, the pipeline is rejected with an error log and does not execute.

### Shared Workspace

Each pipeline run creates a temporary workspace at `/tmp/claude-pipeline-{name}-{timestamp}/`:

```
/tmp/claude-pipeline-my-pipeline-1712345678/
  data/
    collector.md      # Output from the "collector" step
    analyst.md        # Output from the "analyst" step
    publisher.md      # Output from the "publisher" step
```

- Each step's output is written to `data/{step_id}.md`
- Later steps can read outputs from their dependencies (the executor builds a context prefix listing available data files)
- Step prompts do not need to reference data files explicitly -- the orchestrator injects workspace context automatically

On successful completion, the workspace is cleaned up. On failure, it is preserved for debugging.

Stale pipeline workspaces (older than 24 hours) are cleaned up on bot startup.

## Timeouts

Pipelines use a dual timeout system:

### Hard Timeout (`timeout`)

Maximum wall-clock seconds a step is allowed to run. Default: **1200 seconds** (20 minutes). When exceeded, the step's Claude process is killed and the step is marked as failed.

### Inactivity Timeout (`inactivity_timeout`)

Maximum seconds without any output from Claude. Default: **300 seconds** (5 minutes). This catches steps that are stuck or idle. The inactivity timer only starts after Claude has produced at least some output (so initial thinking time does not trigger it).

Example configuration:
```yaml
- id: analyze
  timeout: 600           # Kill after 10 minutes total
  inactivity_timeout: 120  # Kill if idle for 2 minutes
```

## Retry & Failure

### Retry Behavior

- Each step can specify `retry: N` where N is the number of additional attempts after the first failure
- After a step fails, if retries remain, its status resets to `pending` and it will be picked up in the next wave
- The retry count is tracked per step across attempts

### Cascade Skip

When a step fails and has no retries remaining:
- All downstream steps that depend on it (directly or transitively) are marked as `skipped`
- Skipped steps do not execute
- This prevents wasting compute on steps whose inputs are missing

### Pipeline-Level Outcome

A pipeline is considered successful only if **all** steps complete. Any failed or skipped steps result in a failed pipeline status.

## Notifications

The `notify` field in the pipeline frontmatter controls when the bot sends Telegram messages about pipeline progress.

| Mode | Behavior |
|------|----------|
| `none` | No notifications (failures still always notify) |
| `summary` | Send a summary message with step counts and elapsed time on completion |
| `all` | Send a progress message after each wave completes |
| `final` | Send the output from the step marked `output: telegram` (default mode) |

**Failures always notify**, regardless of the notify mode. Failure notifications include the error message and a per-step status summary with icons.

### Output Step

Mark one step with `output: telegram` to designate its output as the pipeline's final result. In `final` mode, this step's full output is sent to Telegram. If no step is marked, the last completed step's output is used as a fallback.

## State Tracking

### Daily State Files

Routine and pipeline execution state is tracked in `~/.claude-bot/routines-state/YYYY-MM-DD.json`. Each file contains a JSON object keyed by routine name, then by time slot:

```json
{
  "morning-report": {
    "08:30": {
      "status": "completed",
      "started_at": "2026-04-08T08:30:01",
      "completed_at": "2026-04-08T08:31:45"
    }
  },
  "crypto-analysis": {
    "21:30": {
      "status": "running",
      "type": "pipeline",
      "steps": {
        "collector": {"status": "completed", "attempt": 1},
        "analyst": {"status": "running", "attempt": 1},
        "publisher": {"status": "pending"}
      }
    }
  }
}
```

### Stale Run Cleanup

On startup, the `RoutineStateManager` scans today's state file and marks any entries with `"status": "running"` as `"failed"`. This handles the case where the bot was killed mid-execution.

## Control Server API

The bot runs a local HTTP control server on `127.0.0.1:27182` for programmatic control of routines and pipelines. All endpoints require authentication.

### Authentication

Every request must include an `X-Bot-Token` header with the bearer token. The token is generated at bot startup, written to `~/.claude-bot/.control-token` (mode 0600), and remains valid for the lifetime of the bot process.

```bash
TOKEN=$(cat ~/.claude-bot/.control-token)
curl -X POST http://127.0.0.1:27182/routine/run \
  -H "X-Bot-Token: $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "morning-report"}'
```

### Endpoints

**POST /routine/run** -- Trigger a routine or pipeline manually

Request body:
```json
{
  "name": "routine-name",
  "time_slot": "now"
}
```
- `name`: routine file stem (without `.md`)
- `time_slot`: arbitrary label for state tracking (default: `"now"`)
- Automatically detects if the routine is a pipeline and uses the appropriate executor

**POST /routine/stop** -- Cancel a running routine or pipeline

Request body:
```json
{
  "name": "routine-name"
}
```
- Checks active pipelines first, then active routine contexts
- For pipelines, cancels all running steps and skips remaining ones

**POST /pipeline/status** -- Get pipeline step status

Request body:
```json
{
  "name": "pipeline-name",
  "time_slot": "21:30"
}
```
- If `time_slot` is omitted, returns the latest time slot for today
- Returns the per-step status from the state file

## Examples

### Simple Routine

A routine that checks BTC price every morning:

```yaml
---
title: "BTC Morning Price"
description: "Sends Bitcoin price via Telegram every day at 8:30 AM."
type: routine
created: 2026-04-07
updated: 2026-04-07
tags: [routine, crypto, daily]
schedule:
  days: ["*"]
  times: ["08:30"]
model: haiku
enabled: true
---

[[Routines]]

Fetch the current Bitcoin price using the Binance public API and send
a formatted message with price, 24h change, high, and low.
```

### Pipeline with Dependencies

A multi-step analysis pipeline where steps run in parallel when possible:

```yaml
---
title: "Crypto Technical Analysis"
description: "Multi-step pipeline: collect data, analyze, generate cover, write report, review, publish."
type: pipeline
created: 2026-04-08
updated: 2026-04-08
tags: [pipeline, crypto, daily]
schedule:
  times: ["21:30"]
  days: ["*"]
model: sonnet
agent: crypto-bro
enabled: true
notify: final
---

[[Routines]]
```

````
```pipeline
steps:
  - id: collector
    name: "Collect data"
    model: sonnet
    prompt_file: steps/collector.md
    timeout: 300

  - id: analyst
    name: "Technical analysis"
    model: opus
    depends_on: [collector]
    prompt_file: steps/analyst.md
    timeout: 600

  - id: cover
    name: "Generate cover image"
    model: sonnet
    depends_on: [collector]
    prompt_file: steps/cover.md
    timeout: 120

  - id: writer
    name: "Write report"
    model: opus
    depends_on: [analyst]
    prompt_file: steps/writer.md
    timeout: 600

  - id: reviewer
    name: "Review and validate"
    model: opus
    depends_on: [writer]
    prompt_file: steps/reviewer.md
    timeout: 300

  - id: publisher
    name: "Publish to Notion + Telegram"
    model: sonnet
    depends_on: [reviewer, cover]
    prompt_file: steps/publisher.md
    timeout: 120
    output: telegram
```
````

In this pipeline:
- `collector` runs first (no dependencies)
- `analyst` and `cover` run in parallel (both depend only on `collector`)
- `writer` waits for `analyst`
- `reviewer` waits for `writer`
- `publisher` waits for both `reviewer` and `cover` -- it is the final step and its output is sent to Telegram
