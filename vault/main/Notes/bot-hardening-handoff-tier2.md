---
title: "bot-hardening-handoff-tier2"
description: "Handoff for the claude-bot hardening work: what v3.80.0/v3.80.1/v3.81.0 changed and must be verified after restart, the Tier 2 backlog (script routines, routine continuity, native compactor), and seven open problems found but not fixed"
type: note
created: 2026-10-16
updated: 2026-10-16
tags: [note, main, claude-bot, handoff, hardening, backlog]
---

[[main/Notes/agent-notes|Notes]]

Handoff written just before the restart that activates three commits. Full
reasoning for the Tier 1/Tier 2 split lives in the originating transcript:
`~/.claude/projects/-Users-viniciusramos-claude-bot-vault-contador-pj--workspace/cf8946db-7862-431c-945e-1a0e9a17f70d.jsonl`

## Shipped — live only after the restart

Three commits, **local, not pushed**:

- `56ce5a0` v3.80.0 — the General topic of a forum chat routes to the vault's
  default agent. An agent can only claim a *named* topic, so General had no
  owner and kept whichever agent its session was last switched to; `/agent new`
  switches the creating context, which left Contador PJ answering in General
  since May.
- `802cbd9` v3.80.1 — the live Reasoning panel renders as one quote instead of a
  stack of broken bubbles with leaked backticks.
- `5060a5b` v3.81.0 — turn integrity: no turn lost to a dead `--resume`, prompt
  moved from argv to stdin, Telegram sends no longer retried after an ambiguous
  failure. Documented under "Turn integrity" in the root `CLAUDE.md`.

### Verify after the restart

1. The General topic answers as **Main** (🤖 signature), not 💼 Contador Pj.
2. The `07apr-0431` session starts with fresh context — its transcript
   (`cf8946db…`) was recorded under `vault/contador-pj/.workspace`, and
   auto-routing resets `session_id` when the agent changes.
3. The Reasoning panel is a single collapsible quote.
4. `~/.claude-bot/bot.log` shows no unexpected `transcript … not found` warnings
   (one per genuinely expired session is correct behaviour, and the user now
   gets a 🧹 notice when it happens).

## Tier 2 backlog

Ordered by value. None of it is started.

1. **LLM-free routine (`script:`)** — let a v1 single-step routine declare a
   script body that runs directly, with no Claude subprocess. Mechanical
   routines (graph rebuild, index regeneration, update checks) pay a full LLM
   turn today for work with no judgement in it. Pipeline v2 already has a typed
   `script` step, so the shape to copy exists; the gap is v1 routines.
2. **Routine continuity** — `context_from` (a run reads the previous run's
   output as its starting context) and `failure_deliver` (a failed routine
   reaches Telegram instead of dying in the log).
3. **Native compactor** — hand the context limit to the Claude CLI's own
   compactor instead of the bot's `/compact` heuristic.

## Open problems found, NOT fixed

1. **`CodexRunner` still passes the prompt in argv** — same exposure class that
   v3.81.0 fixed for `ClaudeRunner` (readable via `ps`, ARG_MAX capped). Left
   alone deliberately: `codex` is not installed on this machine, so its stdin
   flag could not be verified, and guessing it would break the GPT path.
2. **69 pre-existing test failures.** Stable and unrelated to recent work —
   mostly z.AI/GLM tests orphaned by the GLM-removal commit (`cd1477d`) that
   still assert on removed behaviour, plus
   `test_routine_writer_audit::test_every_touching_file_is_reviewed`. They
   deserve a dedicated cleanup pass; until then every change must be verified by
   *comparing failure names* against the baseline, not by expecting green.
3. **`test_bot_integration.py::CallbackHandling` makes a real network call.** A
   ~60s stall that floats between tests in that class depending on which one
   waits for it; total suite time swings between 17s and 88s for this reason
   alone. Verified identical at HEAD and with changes (66.5s either way), so it
   is pre-existing — but it should be mocked.
4. **The shared keychain OAuth is dead** (`claude --print` alone fails with
   "OAuth session expired and could not be refreshed") while the bot is
   healthy, because since v3.76 it injects its own `setup_token` from
   `~/.claude-bot/claude-auth.json` (written 2026-06-20, ~1y life → renew around
   2027-06). Do not diagnose one from the other: a bot 401 now points at that
   token and `/auth` on Telegram is the fix, not `claude auth login`.
5. **`pgrep` hides the bot from bot-spawned sessions** — see
   `pgrep-excludes-caller-ancestors.md`. Affects `claude-bot.sh status`.
6. **The working tree carries uncommitted work from other sessions**
   (`scripts/journal-audit.py`, `scripts/journal-monthly-rollup.py`, three test
   files, many vault files). Stage surgically by path — never `git add -A`, and
   prefer a new test file over appending to a modified one.
7. **OpenClaw is 2026.4.5 locally against 2026.10.3 published** — upgrade not
   attempted.

## Verification method that worked

Only one file differed from HEAD, so the baseline was measured with
`git stash push -- claude-fallback-bot.py`, running the suite, then
`git stash pop` — cheaper than the worktree approach in
`baseline-worktree-regression-check.md` and it leaves other sessions' dirty
files untouched. New tests were then run against HEAD to prove they fail
without the fix: 30 of the 32 in `tests/test_turn_integrity.py` do, and the two
that pass both ways are the ones pinning behaviour that must *not* change.
