---
title: Repo State Snapshot
description: Live snapshot of the claude-bot repo state — working tree, recent commits, branch status. Use when evaluating whether something is ready to commit, to build a PR summary, or before running verification commands.
type: skill
created: 2026-04-14
updated: 2026-04-14
tags: [skill, git, state, verification]
trigger: "repo state, git status, working tree, what's changed, uncommitted, ready to commit, pr summary"
allow_shell: true
---

# Repo State Snapshot

This skill demonstrates the `allow_shell: true` feature — when the bot matches it against a prompt, the `!`cmd`` substitutions below are pre-executed and their output is injected into the system prompt. Claude sees live state without having to spend Bash tool calls.

## Current working tree

```!
git -C "$(dirname "${CLAUDE_PROJECT_DIR:-$PWD}")/claude-bot" status --short 2>/dev/null || git status --short
```

## Recent commits

!`git log --oneline -5 2>/dev/null`

## Branch

!`git rev-parse --abbrev-ref HEAD 2>/dev/null`

## Unpushed commits

!`git log --oneline @{u}..HEAD 2>/dev/null | head -5`

---

## How to use

When Claude sees this skill loaded with the live snapshot above:

1. **Ready-to-commit check** — does the working tree look ready? Are the changes coherent?
2. **PR summary prep** — use the recent commits + unpushed list to draft the summary
3. **Verification backstop** — cross-check claims like "nothing's modified" against the actual `git status --short`

The snapshot runs every time this skill is injected (which is every interactive turn where the prompt matches the triggers). Cost: ~50ms of subprocess work. No tool calls consumed.
