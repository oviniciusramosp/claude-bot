---
name: systematic-debugging
description: Four-phase root cause methodology for any bug, test failure, or unexpected behavior. Enforces investigation before fixes. Use when debugging — BEFORE proposing a fix — especially under time pressure, after a failed fix, or when the issue isn't fully understood.
when_to_use: "bug, crash, error, test failure, unexpected behavior, regression, investigation, root cause, debugging"
---

# Systematic Debugging

Random fixes waste time and create new bugs. Quick patches mask underlying issues. This skill enforces root-cause investigation — every error must be traced to its real origin, fixed at the source, and given structural protection.

## The Iron Law

```
NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST
```

If Phase 1 is not complete, you cannot propose a fix. This applies even under time pressure — systematic debugging is faster than guess-and-check thrashing.

## When to use

For ANY technical issue:
- Crashes, restart loops, or exit-code anomalies
- Test failures (unit, integration, end-to-end)
- API or integration errors
- Unexpected persisted state (corrupted config, drift)
- Performance regressions (slow startup, high CPU, memory growth)
- UI misbehavior or layout glitches

**Use this ESPECIALLY when:**
- Under time pressure — emergencies make guessing tempting
- "Just one quick fix" seems obvious
- A previous fix didn't work
- You don't fully understand the issue

## The four phases

You MUST complete each phase before proceeding.

### Phase 1 — Root Cause Investigation

1. **Read error messages carefully.** Stack traces often contain the exact fix. Note line numbers, file paths, error codes. Read the relevant logs (last 50-100 lines) before theorising.

2. **Reproduce consistently.** Can you trigger it reliably? Exact steps? If not reproducible → gather more data, don't guess.

3. **Check recent changes.** `git log -20`, `git diff HEAD~1`. What commit introduced the issue?

4. **Gather evidence across component boundaries.** Real systems have layers — identify WHICH layer fails before diving into any single file. Add targeted debug logging at each boundary. Run once. Analyse.

5. **Trace data flow backward.** When an error is deep in the call stack, find where the bad value originates. Fix at the source, not at the symptom.

### Phase 2 — Pattern Analysis

1. **Find working examples in the same codebase.** If a new feature fails, read an existing feature that does a similar job. Compare line by line.

2. **Read references completely.** Don't skim documentation for the feature you're using — read the whole relevant section.

3. **List every difference between working and broken.** "That can't matter" is usually wrong.

4. **Understand dependencies.** What env vars does this need? What config files? What cwd? What external services?

### Phase 3 — Hypothesis and Testing

1. **Form a single hypothesis.** Write it down: "I think X is the root cause because Y." Be specific.

2. **Test minimally.** Smallest possible change to validate the hypothesis. One variable at a time. Never bundle "while I'm here" changes.

3. **Verify before continuing.** Worked? Move to Phase 4. Didn't work? Form a NEW hypothesis — don't stack fixes.

4. **Say "I don't know"** when you don't. Don't pretend.

### Phase 4 — Implementation

1. **Create a failing test case first.** Add it under the project's test tree. Run it and confirm RED before writing the fix.

2. **Implement a single fix.** Address the root cause. ONE change. No bundled refactoring.

3. **Verify the fix.** Re-run the test; confirm GREEN. Run the full suite to ensure no regressions.

4. **Add structural protection.** Make the class of bug unrepeatable:
   - Validation / guard clause to prevent recurrence
   - Resilient handling for unavoidable external failures (API down, missing file)
   - Log the error at minimum, surface it to the user when the failure blocks them
   - No silent `except: pass` — ever

5. **If fix doesn't work:**
   - Count fixes attempted. If < 3: return to Phase 1 with new evidence.
   - If >= 3: **STOP**. The pattern is architectural — question the design before attempting fix #4.

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
| 4. Implementation | Failing test, fix, verify, add protection | Bug resolved, tests pass, structural guard in place |

> Adapted from https://github.com/obra/superpowers
