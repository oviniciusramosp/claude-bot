---
title: Review and Optimize Agents
description: Skill for reviewing, improving, and evaluating existing agents. Checks model assignment, personality quality, usage frequency, and merge opportunities.
type: skill
created: 2026-04-16
updated: 2026-04-16
trigger: "when the user wants to review, improve, optimize, audit, or evaluate existing agents, check if agents are still useful, or merge agents"
tags: [skill, agent, review, optimization]
---

## Review Mode

Triggered when the user asks to review, improve, or evaluate existing agents.

### Step 1 — Identify scope

- If the user mentioned a specific agent → review only that one
- If a general review was requested → list every `<id>/` at the vault root that contains `agent-<id>.md`, and analyze each one (including the Main Agent)

### Step 2 — Analyze each agent

For each agent, read `agent-<id>.md` and `CLAUDE.md` in full. Evaluate using the checklist below.

**Review checklist:**

#### A. CLAUDE.md up to date?

- [ ] Do the instructions reflect the agent's actual usage? (compare with recent Journal)
- [ ] Are there obsolete instructions or ones that are never used?
- [ ] Are instructions missing for tasks the agent performs frequently?

#### B. Model appropriate?

- [ ] Is the agent doing simple tasks with `opus`? → suggest `sonnet` or `haiku`
- [ ] Is the agent doing complex analysis with `haiku`? → suggest `sonnet` or `opus`
- [ ] Does the agent have frequent routines with an expensive model? → evaluate cost-benefit

#### C. Agent in use?

- [ ] Does the Journal have recent entries (last 2 weeks)?
- [ ] If not — is the agent still relevant? Suggest disabling or removing.
- [ ] If few entries — does the usage justify a dedicated agent or would Main suffice?

#### D. Distinctive personality?

- [ ] Is the personality in `agent-<id>.md` specific enough?
- [ ] Does the tone in CLAUDE.md match the `personality` field?
- [ ] Does the agent clearly differentiate itself from Main?
- [ ] If the personality is generic ("be helpful") → suggest refinement

#### E. Merge opportunity?

- [ ] Do two agents have overlapping specializations?
- [ ] Does one agent do so little that it could be absorbed by another?
- [ ] If a merge makes sense → propose which one survives and what it absorbs

### Step 3 — Present recommendations

For each analyzed agent, present:

```
### {agent-name}
Status: OK / Improvements suggested

- [improvement 1]: reason and benefit
- [improvement 2]: reason and benefit
```

If the review is general, include a consolidated overview:
```
### Overview

- Total agents: X (+ Main)
- Actively in use: Y
- No recent usage: Z
- Merge candidates: [list]
- Removal candidates: [list]
```

### Step 4 — Apply approved improvements

Ask which improvements the user wants to apply. For each approved one:

- **Model change** → edit `agent-<id>.md` (field `model`)
- **Personality refinement** → edit `agent-<id>.md` (field `personality`) and `CLAUDE.md` (Personality section)
- **Instructions update** → edit `CLAUDE.md`, show diff to the user
- **Agent merge** → migrate relevant instructions to the surviving agent, move Journal entries if necessary
- **Removal** → confirm with the user before deleting (via macOS Trash if available)

When modifying an agent:
1. Update the `updated` field in `agent-<id>.md` frontmatter
2. Record changes in the Journal

### Step 5 — Record in the Journal

Append to the day's journal with the applied changes.
