---
paths:
  - "tests/**/*.py"
  - "test.sh"
  - ".github/workflows/*.yml"
  - "ClaudeBotManager/Tests/**/*.swift"
---

# Testing — claude-bot

The test suite covers the bot's Python code, scripts, and the Swift `ClaudeBotManager` app. **No pip dependencies** for the Python suite — pure stdlib (`unittest` + `unittest.mock`). Swift tests use XCTest.

## Running tests

```bash
./test.sh           # Python + Swift (full suite)
./test.sh py        # Python only (~450 tests, ~7s)
./test.sh swift     # Swift only (~20 tests)
./test.sh tests.test_session_manager  # one Python module
```

CI runs on every push/PR via `.github/workflows/tests.yml` (macOS runner — required for Swift + macOS-specific calls).

## Layout

```
tests/                              # Python tests (~450 tests, pure stdlib)
  _botload.py                       # imports claude-fallback-bot.py under a tmp HOME
  test_smoke_import.py              # bot module loads cleanly
  test_smoke_compile.py             # all .py + .sh files compile / parse
  test_frontmatter.py               # parse_frontmatter, _parse_yaml_value, parse_pipeline_body
  test_session_manager.py           # SessionManager CRUD + persistence + eviction
  test_message_helpers.py           # _split_message, _strip_markdown, _sanitize_markdown_v2
  test_costs.py                     # _track_cost / get_weekly_cost
  test_routine_state.py             # RoutineStateManager (pipeline states + cleanup)
  test_routine_scheduler.py         # RoutineScheduler matching + DAG cycle detection
  test_error_classification.py      # classify_error / get_recovery_plan / _translate_error
  test_reactions_and_danger.py      # load_reaction + DANGEROUS_PATTERNS
  test_bot_integration.py           # ClaudeTelegramBot with mocked Telegram API
  test_claude_runner.py             # ClaudeRunner._handle_event (stream-json)
  test_context_isolation.py         # frozen-context / journal-mtime detection
  test_contracts.py                 # sessions.json, plists, real routines, BOT_VERSION
  test_hot_cache.py                 # vault hot-file cache
  test_journal_audit.py             # scripts/journal-audit.py
  test_vault_graph_builder.py       # scripts/vault-graph-builder.py
  test_vault_indexes.py             # vault index auto-regeneration
  test_vault_lint.py                # scripts/vault_lint.py
  test_vault_query.py               # scripts/vault_query.py (frontmatter query engine)
  test_skill_hints.py               # graph-based _select_relevant_skills
  test_lessons.py                   # /lesson command + record_manual_lesson
  test_active_memory.py             # Active Memory lookup, cache, gating (v2.34.0)

ClaudeBotManager/Tests/ClaudeBotManagerTests/
  FrontmatterParserTests.swift      # Swift parser parity with Python
  SessionServiceTests.swift         # sessions.json decoder
  VaultServiceRoutineTests.swift    # routine save/load round-trip
```

## Test harness — `tests/_botload.py`

The bot script (`claude-fallback-bot.py`) is hyphenated and touches `~/.claude-bot/` at import time, so we can't `import claude_fallback_bot`. The harness:

1. Forces `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` env vars (so the `.env` loader is bypassed)
2. Points `HOME` at a `tempfile.TemporaryDirectory` so the bot's data files land in a sandbox
3. Imports the script via `importlib.util.spec_from_file_location` as a fresh module
4. Repoints `DATA_DIR`, `VAULT_DIR`, etc. so subsequent operations stay in the tmp tree
5. Closes the rotating-file log handler to avoid `ResourceWarning` leaks

Use `load_bot_module(tmp_home, vault_dir)` from any test that needs the bot module.

## Adding tests when you change the bot

The "zero silent errors" rule means **any new error path needs a test**. When you add a feature:

- **New routine field** → add a test in `test_routine_scheduler.py` covering both presence and absence
- **New command** → add a test in `test_bot_integration.py::CommandDispatch`
- **New persisted field on Session/sessions.json** → update `test_contracts.py::SessionsJsonRoundTrip::test_session_dataclass_has_stable_fields` (this guards against accidental removal)
- **New stream-json event type** → add a case in `test_claude_runner.py::HandleEvent`
- **New shell script** → automatically picked up by `test_smoke_compile.py::ShellScriptsSyntaxOk`

## What is NOT tested (by design)

- Real Telegram API calls (flaky, requires token)
- Real Claude CLI subprocess (slow, expensive, non-deterministic)
- Semantic content of LLM responses
- SwiftUI views (cost too high vs. value — covered by previews)
- Vault markdown content as truth (it's user data, not code)
