---
title: Test-Driven Development
description: Red-Green-Refactor cycle for any feature or bugfix that touches bot code. Write the test first, watch it fail, then write minimal code to pass. Enforces the project's test contracts.
type: skill
created: 2026-04-11
updated: 2026-04-11
trigger: "when implementing a new feature, bug fix, refactor, or behavior change in claude-fallback-bot.py, ClaudeBotManager, or the scripts/ folder"
tags: [skill, testing, tdd, quality, python, swift]
---

# Test-Driven Development

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** if you didn't watch the test fail, you don't know if it tests the right thing.

This skill complements `CLAUDE.md` section "Adding tests when you change the bot" and the project's zero-silent-errors rule — every new error path needs a test.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

If you wrote code before the test, delete it and start over from the test. No exceptions.

## When to use

Always for:
- New bot commands (add to `test_bot_integration.py::CommandDispatch`)
- New stream-json event handling (`test_claude_runner.py::HandleEvent`)
- New routine/pipeline frontmatter fields (`test_routine_scheduler.py`)
- New persisted field on `Session` / `sessions.json` (update `test_contracts.py::SessionsJsonRoundTrip::test_session_dataclass_has_stable_fields`)
- Bug fixes in any Python module under `tests/` coverage
- New shell scripts (automatically picked up by `test_smoke_compile.py::ShellScriptsSyntaxOk`)
- Swift changes in `ClaudeBotManager/` (add XCTest under `ClaudeBotManager/Tests/ClaudeBotManagerTests/`)

**Ask first** for:
- Throwaway prototypes
- Generated code
- Configuration files

## The Red-Green-Refactor cycle

### RED — write the failing test

Write ONE minimal test that describes the behaviour you want.

Good example (Python, using the project's test harness):

```python
# tests/test_bot_integration.py
def test_effort_command_sets_reasoning(self):
    bot = self._make_bot()
    bot.cmd_effort("high")
    self.assertEqual(bot.config["effort"], "high")
```

Requirements:
- One behaviour per test
- Clear name describing the behaviour, not the code (`test_effort_command_sets_reasoning`, not `test_effort_1`)
- Uses real code — mocks only when unavoidable (e.g. Telegram API, Claude CLI subprocess)
- Imports via `tests._botload.load_bot_module(tmp_home, vault_dir)` — never `import claude_fallback_bot`

### Verify RED — watch it fail

MANDATORY. Run the targeted test:

```bash
./test.sh tests.test_bot_integration
```

Confirm:
- Test fails (not errors)
- Failure message is expected (feature missing, not typos)
- It fails for the right reason

If the test passes without changes, it's testing existing behaviour — rewrite the test. If it errors, fix the typo and re-run until it fails correctly.

### GREEN — minimal code

Write the simplest code that makes the test pass. No features beyond what the test requires. No refactoring other code. No "while I'm here" improvements.

### Verify GREEN

MANDATORY.

```bash
./test.sh tests.test_bot_integration
./test.sh py    # full Python suite to catch regressions
```

Confirm:
- Target test passes
- Other tests still pass
- Output pristine — no warnings, no `ResourceWarning`, no `DeprecationWarning`

### REFACTOR — clean up

After GREEN only:
- Remove duplication
- Improve names
- Extract helpers

Keep tests green. Don't add behaviour during refactor.

### Version bump

Per `CLAUDE.md` versioning rules, if the change touches `claude-fallback-bot.py`, bump `BOT_VERSION` AND `ClaudeBotManager/Sources/App/Info.plist` in the SAME commit as the code + test. Vault-only changes do NOT bump.

## Why test-first matters

Tests written after the code pass immediately — which proves nothing:
- Might test the wrong thing
- Might test the implementation instead of the behaviour
- Might miss edge cases you forgot
- You never saw it catch a bug

Test-first forces you to see the test fail first, proving it actually tests something.

## Common rationalizations

| Excuse | Reality |
|--------|---------|
| "Too simple to test" | Simple code breaks. The test takes 30 seconds. |
| "I'll test after" | Tests passing immediately prove nothing. |
| "I already tested manually" | Ad-hoc testing has no record, cannot re-run. |
| "Deleting hours of work is wasteful" | Sunk cost. Unverified code is technical debt. |
| "Keep as reference, write the test first" | You will adapt it. That's testing-after. Delete means delete. |
| "Test is hard = design is unclear" | Listen to the test. Hard to test = hard to use. |
| "Existing code has no tests" | You are improving it. Add tests for what you touch. |

## Red flags — STOP and start over

- Code written before the test
- Test written after implementation
- Test passes immediately without seeing RED
- Can't explain why the test failed
- "I'll add tests later"
- "Just this once"
- "Keep the existing code as reference"

All mean: delete the code, restart with RED first.

## Python specifics

- No pip dependencies — pure stdlib (`unittest` + `unittest.mock`)
- The bot script is hyphenated and touches `~/.claude-bot/` at import. Use `tests._botload.load_bot_module(tmp_home, vault_dir)` to import it safely
- Close any handlers the harness opens to avoid `ResourceWarning` on teardown
- Real Telegram API calls, real Claude CLI subprocess, and semantic LLM content are NOT tested by design — see `CLAUDE.md` "What is NOT tested"

## Swift specifics

- Tests live under `ClaudeBotManager/Tests/ClaudeBotManagerTests/` using XCTest
- `FrontmatterParserTests.swift` exists to guarantee parity with Python's `parse_frontmatter`
- Run via `./test.sh swift`
- SwiftUI views are covered by previews, not unit tests — don't write UI snapshot tests

## Checklist before marking work complete

- [ ] Every new function/method has a test
- [ ] Watched each test fail before writing the implementation
- [ ] Each test failed for the right reason
- [ ] Wrote minimal code to pass
- [ ] Full suite (`./test.sh`) passes
- [ ] Output pristine (no warnings)
- [ ] `BOT_VERSION` bumped if `claude-fallback-bot.py` changed
- [ ] Commit is a single Conventional Commit combining code + test + version bump

If you can't check every box, you skipped TDD. Start over.

## Notes

- Never fix a bug without writing a failing test that reproduces it first. The test proves the fix AND prevents regression.
- If the test is hard to write, the design is probably wrong. Simplify the interface before adding mocks.
- The CI workflow `.github/workflows/tests.yml` runs on macOS and must stay green — don't merge red.

> Adapted from https://github.com/obra/superpowers
