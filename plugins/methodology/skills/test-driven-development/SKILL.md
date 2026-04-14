---
name: test-driven-development
description: Red-Green-Refactor cycle for any feature or bugfix. Write the test first, watch it fail, then write minimal code to pass. Enforces test-first discipline and proves every test actually catches something.
when_to_use: "implementing a new feature, writing a bug fix, refactoring, adding behavior, TDD, unit test, integration test"
---

# Test-Driven Development

Write the test first. Watch it fail. Write minimal code to pass.

**Core principle:** if you didn't watch the test fail, you don't know if it tests the right thing.

## The Iron Law

```
NO PRODUCTION CODE WITHOUT A FAILING TEST FIRST
```

If you wrote code before the test, delete it and start over from the test. No exceptions.

## When to use

Always for:
- New functions, methods, or classes with testable behavior
- New API endpoints or commands
- Bug fixes (test reproduces the bug first)
- Behavior changes to existing code
- Edge-case handling

**Ask first** for:
- Throwaway prototypes
- Generated code
- Configuration files

## The Red-Green-Refactor cycle

### RED — write the failing test

Write ONE minimal test that describes the behaviour you want.

Requirements:
- One behaviour per test
- Clear name describing the behaviour, not the code (e.g. `test_login_rejects_empty_password`, not `test_login_1`)
- Uses real code — mocks only when unavoidable (external APIs, network, filesystem)

### Verify RED — watch it fail

MANDATORY. Run the targeted test and confirm:
- Test fails (not errors from typos)
- Failure message is expected (feature missing, not syntax problem)
- It fails for the right reason

If the test passes without changes, it's testing existing behaviour — rewrite the test. If it errors, fix the typo and re-run until it fails correctly.

### GREEN — minimal code

Write the simplest code that makes the test pass. No features beyond what the test requires. No refactoring other code. No "while I'm here" improvements.

### Verify GREEN

MANDATORY.
- Target test passes
- Full suite passes (catch regressions)
- Output pristine — no warnings, no deprecation notices, no leaked resources

### REFACTOR — clean up

After GREEN only:
- Remove duplication
- Improve names
- Extract helpers

Keep tests green. Don't add behaviour during refactor.

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

## Checklist before marking work complete

- [ ] Every new function/method has a test
- [ ] Watched each test fail before writing the implementation
- [ ] Each test failed for the right reason
- [ ] Wrote minimal code to pass
- [ ] Full suite passes
- [ ] Output pristine (no warnings)
- [ ] Commit combines code + test as a single coherent change

If you can't check every box, you skipped TDD. Start over.

## Notes

- Never fix a bug without writing a failing test that reproduces it first. The test proves the fix AND prevents regression.
- If the test is hard to write, the design is probably wrong. Simplify the interface before adding mocks.

> Adapted from https://github.com/obra/superpowers
