---
title: Review and Optimize Pipelines
description: Skill for reviewing, improving, and optimizing existing pipelines. Analyzes parallelism, model assignment, resilience, prompt quality, and execution history.
type: skill
created: 2026-04-16
updated: 2026-04-16
trigger: "when the user wants to review, improve, optimize, audit, or fix an existing pipeline, check pipeline performance, or reduce pipeline cost"
tags: [skill, pipeline, review, optimization, parallelism, resilience]
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

1. Parallelize collection — split [step1] into 3 parallel sub-collectors
   Gain: collection from ~5min to ~1min

2. Add retry — [step1] and [step3] make external calls without retry
   Gain: resilience against transient failures

3. Adjust model — [step3] uses opus but only formats text (sonnet is enough)
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
| Raw curl to Telegram | Hardcoded env vars go stale, messages go to wrong topic | Use `scripts/telegram_notify.py "msg"` — auto-detects agent, reads routing from frontmatter |
