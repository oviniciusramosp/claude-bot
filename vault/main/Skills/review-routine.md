---
title: Review and Optimize Routines
description: Skill for reviewing, improving, and optimizing existing routines. Checks model assignment, context mode, prompt quality, schedule appropriateness, and pipeline conversion opportunities.
type: skill
created: 2026-04-16
updated: 2026-04-16
trigger: "when the user wants to review, improve, optimize, audit, or fix existing routines, check routine performance, or reduce routine cost"
tags: [skill, routine, review, optimization]
---

## Review Mode

Triggered when the user asks to review, improve, or optimize existing routines.

### Step 1 — Identify scope

- If the user mentioned a specific routine → review only that one
- If they asked for a general review → iterate every `vault/<agent>/Routines/*.md` under each agent folder (skip `agent-routines.md` indexes and pipeline step folders) and analyze each one

### Step 2 — Analyze each routine

For each routine with `type: routine`, read the full file and evaluate:

**Review checklist:**

1. **Should it be a pipeline?** — Does the prompt perform multiple sequential tasks? Does it fetch data from multiple sources? Are there steps that could run in parallel? If so, suggest conversion to pipeline.

2. **Appropriate model?** — Simple tasks (reminder, backup, notification) should use `haiku`. Analysis/writing tasks should use `opus` or `sonnet`. Is the model over- or under-estimated?

3. **Appropriate context?** — Routines that don't need to read the entire vault should use `context: minimal` to save tokens and run faster.

4. **Clear prompt?** — Is the prompt specific enough? Are there ambiguous instructions? Missing output instructions?

5. **Appropriate schedule?** — Do the time and frequency make sense for the goal?

6. **Recent executions** — Read `~/.claude-bot/routines-state/` and locate the JSON for the current day (format `YYYY-MM-DD.json`). Check:
   - Is the routine executing successfully or failing?
   - If failing: what is the error? How long has it been failing consecutively?
   - Is the execution time within the expected range or hitting the timeout?
   - If the routine doesn't appear in the state file, it may have never executed (wrong schedule? `enabled: false`?)

### Step 3 — Present recommendations

For each analyzed routine, present:
```
### {routine-name}
Status: OK / Improvements suggested

- [improvement 1]: reason and benefit
- [improvement 2]: reason and benefit
```

### Step 4 — Execute approved improvements

Ask which improvements the user wants to apply. For each approved one:

- If it's a conversion to pipeline → read and follow the `Skills/create-pipeline.md` skill
- If it's a model/context/schedule change → edit the file directly
- If it's a prompt improvement → rewrite the prompt and show the diff to the user

### Step 5 — Record in the Journal

Append to the day's journal with the applied changes.
