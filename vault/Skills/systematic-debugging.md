---
title: Systematic Debugging
description: Four-phase root cause methodology for any bug, test failure, or unexpected behavior. Enforces investigation before fixes. Use when debugging the bot, a routine, or a pipeline step.
type: skill
created: 2026-04-11
updated: 2026-04-11
trigger: "when encountering any bug, test failure, routine failure, pipeline step error, or unexpected behavior — BEFORE proposing a fix"
tags: [skill, debugging, root-cause, methodology, reliability]
---

# Systematic Debugging

Random fixes waste time and create new bugs. Quick patches mask underlying issues. This skill enforces the project's "zero silent errors" rule from `CLAUDE.md` — every error must be traced to its real origin, fixed at the source, and given structural protection.

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If Phase 1 is not complete, you cannot propose a fix. This applies even under time pressure — systematic debugging is faster than guess-and-check thrashing.

## When to use

For ANY technical issue:
- Bot crashes or restart loops (check `~/.claude-bot/bot.log`, then watchdog logs)
- Routine or pipeline step failure
- Telegram message not sent / markdown broken
- Test failure in `tests/` (Python) or `ClaudeBotManager/Tests/` (Swift)
- Unexpected session state (sessions.json corruption, workspace drift)
- macOS ClaudeBotManager misbehavior
- Performance regression (slow polling, high CPU)

**Use this ESPECIALLY when:**
- Under time pressure — emergencies make guessing tempting
- "Just one quick fix" seems obvious
- A previous fix didn't work
- You don't fully understand the issue

## The four phases

You MUST complete each phase before proceeding.

### Phase 1 — Root Cause Investigation

1. **Read error messages carefully.** Stack traces often contain the exact fix. Note line numbers, file paths, error codes. Read `~/.claude-bot/bot.log` (last 50-100 lines) before theorising.

2. **Reproduce consistently.** Can you trigger it reliably? Exact steps? If not reproducible → gather more data, don't guess. For intermittent routine failures, inspect `~/.claude-bot/routines-state/YYYY-MM-DD.json` for prior attempts.

3. **Check recent changes.** `git log -20`, `git diff HEAD~1`. What commit introduced the issue? What `BOT_VERSION` was running when it started failing?

4. **Gather evidence across component boundaries.** The bot has multiple layers:
   - Telegram API → `ClaudeTelegramBot` (polling loop, rate limiting)
   - `ClaudeTelegramBot` → `ClaudeRunner` (subprocess spawn, stream-json parsing)
   - `ClaudeRunner` → Claude CLI subprocess (cwd, env, stdin)
   - Claude CLI → vault files (CLAUDE.md hierarchy, agent workspace)

   Add targeted `logging.debug()` calls at each boundary. Run once. Analyse evidence to identify WHICH layer fails BEFORE diving into any single file.

5. **Trace data flow backward.** When an error is deep in the call stack, find where the bad value originates. Fix at the source, not at the symptom.

### Phase 2 — Pattern Analysis

1. **Find working examples in the same codebase.** If a new routine fails, read an existing routine that does a similar job. Compare line by line.

2. **Read references completely.** If implementing against `vault/CLAUDE.md` or `Skills/create-pipeline.md`, read the whole relevant section — do not skim.

3. **List every difference between working and broken.** "That can't matter" is usually wrong.

4. **Understand dependencies.** What env vars does this need? What vault files? What cwd? What entries in `sessions.json`?

### Phase 3 — Hypothesis and Testing

1. **Form a single hypothesis.** Write it down: "I think X is the root cause because Y." Be specific.

2. **Test minimally.** Smallest possible change to validate the hypothesis. One variable at a time. Never bundle "while I'm here" changes.

3. **Verify before continuing.** Worked? Move to Phase 4. Didn't work? Form a NEW hypothesis — don't stack fixes.

4. **Say "I don't know"** when you don't. Don't pretend.

### Phase 4 — Implementation

1. **Create a failing test case first.** For Python code, add it to `tests/` under the relevant `test_*.py`. For Swift, add it under `ClaudeBotManagerTests/`. Run with `./test.sh py` or `./test.sh swift` and confirm RED. If no existing test file fits, add a new one — see the tests section in `CLAUDE.md`.

2. **Implement a single fix.** Address the root cause. ONE change. No bundled refactoring.

3. **Verify the fix.** Re-run the test; confirm GREEN. Run the full suite (`./test.sh`) to ensure no regressions.

4. **Add structural protection.** Per `CLAUDE.md` "zero silent errors":
   - Validation / guard clause to prevent recurrence
   - Resilient handling for unavoidable external failures (API down, missing file)
   - Minimum `logging.error()` with context, plus Telegram notification when the failure blocks the user
   - No `except: pass` — ever

5. **Bump `BOT_VERSION` in the same commit** if the fix touches `claude-fallback-bot.py` (PATCH for fixes, MINOR for new features) — also update `ClaudeBotManager/Sources/App/Info.plist`. Vault-only fixes do NOT bump version.

6. **If fix doesn't work:**
   - Count fixes attempted. If < 3: return to Phase 1 with new evidence.
   - If >= 3: **STOP**. The pattern is architectural — question the design with the user before attempting fix #4.

## Red flags — STOP and return to Phase 1

If you catch yourself thinking:
- "Quick fix for now, investigate later"
- "Just try changing X and see if it works"
- "Skip the test, I'll manually verify"
- "It's probably X, let me fix that"
- "I'll write the test after confirming the fix works"
- "One more fix attempt" (when you've already tried 2+)
- Each fix reveals a new problem in a different place

All of these mean: STOP. Return to Phase 1.

## Common rationalizations

| Excuse | Reality |
|--------|---------|
| "Issue is simple, don't need process" | Simple issues have root causes too. The process is fast for simple bugs. |
| "Emergency, no time for process" | Systematic debugging is faster than guess-and-check thrashing. |
| "Just try this first, then investigate" | First fix sets the pattern. Do it right from the start. |
| "Multiple fixes at once saves time" | Can't isolate what worked. Causes new bugs. |
| "Reference is too long, I'll adapt" | Partial understanding guarantees bugs. Read it completely. |
| "I see the problem, let me fix it" | Seeing symptoms is not understanding the cause. |
| "One more fix attempt" | 3+ failures means architectural problem. Question the pattern. |

## Quick reference

| Phase | Activities | Success criteria |
|-------|-----------|------------------|
| 1. Root Cause | Read errors, reproduce, check git, gather evidence per layer | Understand WHAT and WHY |
| 2. Pattern | Find working examples, compare line by line | Identify all differences |
| 3. Hypothesis | Form a single theory, test minimally | Confirmed or new hypothesis |
| 4. Implementation | Failing test, fix, verify, add protection, bump version | Bug resolved, tests pass, structural guard in place |

## Notes

- This skill exists to enforce the "zero silent errors" rule in `CLAUDE.md`. Every error must eventually produce either a structural fix OR a visible notification (log + Telegram).
- When debugging routines, also consult `~/.claude-bot/routines-state/YYYY-MM-DD.json` for previous attempts.
- When debugging pipelines, inspect the shared workspace at `/tmp/claude-pipeline-{name}-{ts}/data/` before it's cleaned up.
- The bot's error classification helpers live in `tests/test_error_classification.py` and `claude-fallback-bot.py` (`classify_error`, `get_recovery_plan`). Use them to decide whether a failure is retryable.

> Adapted from https://github.com/obra/superpowers
