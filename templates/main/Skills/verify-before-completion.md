---
title: Verify Before Completion
description: Gate function that requires fresh verification evidence before claiming any work is done. No success claims without having just run the verification command in the current context.
type: skill
created: 2026-04-11
updated: 2026-04-11
trigger: "before claiming any task is complete, fixed, passing, or ready — before committing, pushing, or reporting back to the user"
tags: [skill, verification, quality, honesty, testing]
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
| Python tests pass | `./test.sh py` output: 0 failures | Previous run, "should pass", "last time it worked" |
| Swift tests pass | `./test.sh swift` output: 0 failures | Partial check, extrapolation |
| Full suite passes | `./test.sh` output: 0 failures in both | Only Python OR only Swift |
| Bot compiles | `python3 -m py_compile claude-fallback-bot.py` exit 0 | Linter passing, "syntax looks right" |
| Shell script parses | `bash -n script.sh` exit 0 | Visual inspection |
| Routine parses | Load via `parse_frontmatter` + `parse_pipeline_body` in a REPL / test | "Frontmatter looks correct" |
| Bug fixed | Rerun the reproduction steps, see original symptom gone | Code changed, "assumed fixed" |
| Regression test works | Red-Green cycle verified (saw it fail, saw it pass) | Test passes once |
| Routine is scheduled | Check `RoutineScheduler` match OR wait for actual run | "Frontmatter has schedule" |
| ClaudeBotManager rebuilt | `ClaudeBotManager.app/Contents/MacOS/ClaudeBotManager --version` / process restarted | Seeing build-app.sh complete |
| Pipeline DAG valid | Run through `RoutineScheduler`'s cycle detection | "depends_on looks right" |
| Markdown safe for Telegram | Passes `_sanitize_markdown_v2` in a test | "It renders in my editor" |
| `BOT_VERSION` bumped in both files | `grep BOT_VERSION claude-fallback-bot.py` AND `grep CFBundleShortVersionString ClaudeBotManager/Sources/App/Info.plist` match | Bumped one, assumed both |
| Commit clean | `git status` shows clean tree after commit | "Commit created" |
| Vault link works | File exists at the wikilink target path | "Spelling looks right" |

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

### Bot code change
```
Write test → ./test.sh py (targeted, see FAIL) → implement → ./test.sh py (see PASS) → ./test.sh (full suite, see PASS) → claim "fixed"
```
Never: "I changed the function, the test should pass now."

### ClaudeBotManager change
```
Edit Swift → cd ClaudeBotManager && bash build-app.sh → verify app opened and sidebar populated → claim "done"
```
Never: "Swift file edited, will build next time."

### Routine / pipeline change
```
Edit .md → parse via test_routine_scheduler.py or trigger via /run <name> → verify actual output → claim "working"
```
Never: "Frontmatter looks right, should schedule."

### Version bump
```
Edit BOT_VERSION → edit Info.plist → grep both → ./test.sh → commit → git log -1 → claim "bumped"
```
Never: "Bumped one, other will follow."

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
- Reporting back to the user on Telegram

The rule applies to:
- Exact phrases ("done", "fixed", "passing")
- Paraphrases and synonyms ("all set", "good to go", "ship it")
- Implications of success ("no more errors")
- Any communication suggesting completion or correctness

## The bottom line

**No shortcuts for verification.**

Run the command. Read the output. THEN claim the result.

This is non-negotiable — and it is the backstop for the project's "zero silent errors" rule. A silently-skipped verification is the most common way a "fixed" bug silently ships.

## Notes

- When the verification command is too expensive to run in every conversation turn, say so explicitly and note the last time it was run in the current session — don't pretend.
- For changes that only touch the vault, the verification is usually "re-read the affected file and check frontmatter, wikilinks, and index entry" — still run it before claiming done.
- Pair this skill with `Skills/systematic-debugging.md` — Phase 4 of that skill ends with a verification step that this skill enforces.

> Adapted from https://github.com/obra/superpowers
