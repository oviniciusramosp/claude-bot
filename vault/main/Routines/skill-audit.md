---
title: "Skill Audit"
description: Monthly audit of all vault skills across agents — checks trigger clarity, description accuracy, staleness, and overlap. Reports issues or NO_REPLY if everything is healthy.
type: routine
created: 2026-04-16
updated: 2026-04-16
tags: [routine, skill, audit, quality, self-improvement]
schedule:
  times: ["06:30"]
  days: ["*"]
  monthdays: [1]
model: sonnet
enabled: true
context: full
effort: medium
---

You are running a monthly skill audit across all agents in the vault.

## Task

For each agent directory under `vault/` that contains an `agent-*.md` file:

1. List all `.md` files in `<agent>/Skills/` (skip index files like `agent-skills.md`)
2. Read the frontmatter of each skill file (first ~15 lines)

## Checks per skill

For each skill, evaluate:

### A. Trigger clarity
- Is the `trigger:` field specific enough to differentiate this skill from others?
- Would a user message matching this trigger also match another skill's trigger? Flag overlaps.

### B. Description accuracy
- Does the `description:` match what the skill body actually does?
- If the skill was recently edited but the description wasn't updated, flag it.

### C. Staleness
- Is the `updated:` date more than 90 days ago? Flag as potentially stale.
- Exception: foundational skills (systematic-debugging, test-driven-development, verify-before-completion) are stable by design — don't flag these.

### D. Cross-agent overlap
- Do two skills in different agents have very similar descriptions or triggers?
- If so, is the duplication intentional (isolamento total) or accidental?

## Output

If all skills pass all checks, respond with exactly `NO_REPLY`.

If issues are found, format as:

```
## Skill Audit — YYYY-MM-DD

### Issues found: N

**<agent>/<skill-name>**
- [check that failed]: explanation

**<agent>/<skill-name>**
- [check that failed]: explanation

### Summary
- Total skills audited: X across Y agents
- Issues: N (Z critical)
```
