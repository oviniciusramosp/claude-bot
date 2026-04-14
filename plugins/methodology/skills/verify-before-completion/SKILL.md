---
name: verify-before-completion
description: Gate function that requires fresh verification evidence before claiming any work is done. No success claims without having just run the verification command in the current context. Use before committing, pushing, or reporting any work as complete.
when_to_use: "before claiming any task is complete, fixed, passing, or ready — before committing, pushing, creating a PR, or reporting back"
---

# Verify Before Completion

Claiming work is complete without verification is dishonesty, not efficiency. Evidence before claims, always.

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in the current context, you cannot claim it passes. Previous runs, "should pass", and "looks correct" are all insufficient.

## The gate function

Before claiming any status or expressing satisfaction:

1. **Identify** — what command proves this claim?
2. **Run** — execute the full command, fresh, complete
3. **Read** — the full output, check exit code, count failures
4. **Verify** — does the output confirm the claim?
   - If NO: state the actual status with evidence
   - If YES: state the claim WITH evidence
5. **Only then** make the claim

Skipping any step = lying, not verifying.

## Common claims and their required evidence

| Claim | Required evidence | Not sufficient |
|-------|-------------------|----------------|
| Tests pass | Fresh `test` command output: 0 failures | Previous run, "should pass", "last time it worked" |
| Full suite passes | Run ALL test targets, 0 failures each | Only one target passing |
| Code compiles | Fresh compile/type-check output, exit 0 | Linter passing, "syntax looks right" |
| Build succeeds | Fresh build output, no errors | Visual inspection |
| Bug fixed | Rerun the reproduction steps, see original symptom gone | Code changed, "assumed fixed" |
| Regression test works | Red-Green cycle verified (saw it fail, saw it pass) | Test passes once |
| Lint clean | Fresh lint output, 0 warnings | "Looks clean to me" |
| Commit clean | `git status` shows clean tree after commit | "Commit created" |
| No side effects | Run the affected features once each | "Change is local" |

## Red flags — STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!")
- About to commit / push / open a PR without verification
- Trusting an agent's success report without checking
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting the work over
- ANY wording implying success without having run verification

## Rationalization prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | Run the verification command. |
| "I'm confident" | Confidence is not evidence. |
| "Just this once" | No exceptions. |
| "Linter passed" | Linter is not the compiler. |
| "Agent said success" | Verify independently via git diff or a fresh test run. |
| "I'm tired" | Exhaustion is not an excuse. |
| "Partial check is enough" | Partial proves nothing. |
| "I changed one line, obviously safe" | Two-line bugs ship every day. |

## Key patterns

### Code change
```
Write test → run (see FAIL) → implement → run (see PASS) → full suite (see PASS) → claim "fixed"
```
Never: "I changed the function, the test should pass now."

### Build / compile
```
Edit source → build (see SUCCESS) → run resulting artifact → verify behavior → claim "done"
```
Never: "Source file edited, will build next time."

### Bug reproduction
```
Reproduce original symptom → apply fix → re-run reproduction → verify symptom gone → claim "fixed"
```
Never: "I think the fix addresses it."

### Regression test (red-green cycle)
```
Write test → run (FAIL with expected message) → revert fix → run (MUST FAIL) → restore fix → run (PASS) → claim "regression test works"
```
Never: "I wrote a regression test" without seeing both RED and GREEN.

### Agent delegation
```
Agent reports success → git diff → verify the expected files changed → read the actual diff → rerun relevant tests → claim "applied"
```
Never: trust the agent's report at face value.

## When to apply

ALWAYS before:
- Any variation of success / completion claims
- Any expression of satisfaction
- Any positive statement about work state
- Committing, pushing, PR creation, task hand-off
- Moving to the next task
- Delegating to a sub-agent
- Reporting back to the user

The rule applies to:
- Exact phrases ("done", "fixed", "passing")
- Paraphrases and synonyms ("all set", "good to go", "ship it")
- Implications of success ("no more errors")
- Any communication suggesting completion or correctness

## The bottom line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is the backstop for any zero-silent-errors policy. A silently-skipped verification is the most common way a "fixed" bug silently ships.

## Notes

- When the verification command is too expensive to run in every conversation turn, say so explicitly and note the last time it was run in the current session — don't pretend.
- Pair this skill with `systematic-debugging` — Phase 4 of that skill ends with a verification step that this skill enforces.

> Adapted from https://github.com/obra/superpowers
