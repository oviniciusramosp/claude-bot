# Claude Bot — Development Guide

**IMPORTANT:** This is the DEVELOPMENT CLAUDE.md for the claude-bot project. It contains instructions for working on the bot's code (Python, Swift, shell scripts). For the bot's operational knowledge base (vault, routines, agents, journal), see `vault/CLAUDE.md`.

## Overview

Telegram bot that provides remote access to [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) via Telegram messages. Pure Python (stdlib only), runs as a macOS launchd service.

## Architecture

```
User ↔ Telegram API ↔ claude-fallback-bot.py ↔ Claude Code CLI (subprocess)
```

### Files

| File | Purpose |
|------|---------|
| `claude-fallback-bot.py` | Main bot — Telegram polling, session management, Claude CLI orchestration |
| `claude-bot-menubar.py` | macOS menu bar indicator (requires `rumps`) |
| `claude-bot.sh` | Service manager — install/uninstall/start/stop/restart/status/logs |
| `com.claudebot.bot.plist` | launchd template for the bot (uses `__HOME__`/`__SCRIPT_DIR__` placeholders) |
| `com.claudebot.menubar.plist` | launchd template for the menu bar app |

### Runtime Data

All runtime data is stored in `~/.claude-bot/`:
- `sessions.json` — Session persistence (names, IDs, models, agents, message counts)
- `bot.log` — Application log (rotating, 5MB × 3 backups)
- `launchd-stdout.log` / `launchd-stderr.log` — Process output
- `routines-state/YYYY-MM-DD.json` — Daily routine execution state

When diagnosing bot issues, read `~/.claude-bot/bot.log` (last ~50 lines).

### Key Classes

- **`Session`** (dataclass) — Holds session state: name, Claude session ID, model, workspace, agent, created_at, message_count, total_turns, active_memory (per-session toggle for proactive vault context injection, default `True`)
- **`SessionManager`** — CRUD for sessions, persists to `sessions.json`. `_load()` filters unknown keys so adding new fields is forward-compatible.
- **`ClaudeRunner`** — Spawns Claude CLI as subprocess, handles streaming JSON output, cancellation (SIGINT → SIGTERM → SIGKILL)
- **`ClaudeTelegramBot`** — Main orchestrator: Telegram long-polling, command routing, inline keyboards, message splitting

### How Claude CLI is Invoked

```python
runner.run(
    prompt=prompt,
    model=model,
    session_id=session_id,      # None for fresh sessions (routines always use None)
    workspace=workspace,        # cwd for the subprocess
    system_prompt=SYSTEM_PROMPT # None when minimal_context=True
)
```

The `ClaudeRunner` builds the command with `--print --dangerously-skip-permissions --output-format stream-json`. The `--append-system-prompt` instructs Claude to read the vault (Journal, Tooling, etc.) — it can be omitted via `system_prompt=None` when the routine uses `context: minimal`.

**Default workspace:** `vault/` — the bot operates inside the vault by default. Agents change the cwd to `vault/Agents/{id}/`. Claude CLI loads CLAUDE.md walking up the hierarchy, so:
- Normal session: `vault/CLAUDE.md` (primary) + this file (parent)
- Active agent: `Agents/{id}/CLAUDE.md` + `vault/CLAUDE.md` + this file

## Configuration

This project uses **two `.env` files with distinct purposes** — don't confuse them:

### `~/claude-bot/.env` — Bot operational config

Read by `claude-fallback-bot.py` at startup and by ClaudeBotManager (macOS app). Contains credentials and paths needed for the bot to run:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Authorized Telegram chat ID |
| `CLAUDE_PATH` | No | `/opt/homebrew/bin/claude` | Path to Claude CLI binary |
| `CLAUDE_WORKSPACE` | No | `vault/` | Working directory for Claude sessions |

**Edited via:** ClaudeBotManager → Settings, or directly in the file.

### `vault/.env` — API keys for vault tasks

Read by Claude Code when executing tasks in the vault context (routines, interactive sessions). Contains keys for external services that Claude may need to access:

- `NOTION_API_KEY` — Notion integration
- `FIGMA_TOKEN` — Figma MCP
- Other external API keys as needed

**Does not contain** Telegram credentials or bot paths.

**Why separate?** `vault/` can be synced (iCloud, Git) — mixing Telegram tokens with third-party API keys would be an unnecessary security risk. Bot ops config stays local; workspace keys stay in the vault.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start`, `/help` | Show help |
| `/status` | Session & process info |
| `/sonnet`, `/opus`, `/haiku` | Quick model switch |
| `/model` | Model picker (inline keyboard) |
| `/new [name]` | Create new session |
| `/sessions` | List all sessions |
| `/switch <name>` | Switch session |
| `/delete <name>` | Delete session |
| `/clone <name>` | Clone the current session into a new branch (same Claude thread, fresh turn counter) |
| `/run [name]` | Manually trigger a routine/pipeline |
| `/compact` | Auto-compact context |
| `/cost` | Token usage and cost for current session |
| `/doctor` | Check Claude Code installation health |
| `/lint` | Audit the vault (frontmatter, wikilinks, schedules, stale routines) |
| `/find <expr>` | Query the vault by frontmatter (e.g. `type=routine model=opus`) |
| `/indexes` | Regenerate vault index marker blocks (Routines.md, Skills.md, Agents.md) |
| `/btw <msg>` | Inject message to running Claude process (native); falls back to queue |
| `/delegate <prompt>` | Spawn an isolated subagent (fresh context, 10min hard limit), inject result back into parent session |
| `/stop` | Cancel running task |
| `/timeout <sec>` | Change timeout |
| `/workspace <path>` | Change working directory |
| `/effort <low\|medium\|high>` | Set reasoning effort |
| `/clear` | Reset current session |
| `/important` | Record key points from the current session into today's Journal |
| `/lesson <text>` | Record a manual lesson in `vault/Lessons/` (compound engineering) |
| `/active-memory [on\|off\|status]` | Toggle proactive vault context injection (default: on) |
| `/agent [name\|new\|list]` | Switch/create/list agents (no arg → inline keyboard) |
| `/routine [list\|status]` | Create a routine interactively, or list/status of today's routines |
| `/skill [name]` | Run a vault skill directly |
| `/voice [on\|off]` | Toggle TTS voice responses for all messages |
| `/audio` | Choose transcription language |
| `#voice` (in message) | One-shot voice response (audio only, no text) |

## Development Guidelines

- **No pip dependencies** for the main bot (`claude-fallback-bot.py`). Only stdlib.
- The menu bar app (`claude-bot-menubar.py`) requires `rumps`.
- Telegram API calls use raw `urllib.request` (no `requests` library).
- All Telegram message edits are rate-limited (`STREAM_EDIT_INTERVAL = 3.0s`).
- Long messages are split respecting Markdown code blocks.
- The bot validates `AUTHORIZED_CHAT_ID` on every incoming message — unauthorized messages are silently ignored.
- Plist files use `__HOME__` and `__SCRIPT_DIR__` placeholders — the install script (`claude-bot.sh`) substitutes them via `sed`.

### Error handling — zero silent errors

When encountering an error, **never treat it as a one-off**. Follow this mandatory flow:

1. **Investigate the root cause** — don't fix just the symptom. Trace the error path to the real origin (invalid data, inconsistent state, race condition, etc.)
2. **Fix the root cause** — the fix must eliminate the class of error, not just the observed instance
3. **Add structural protection** — implement validation, guard clause, or check to prevent recurrence. If the error can return due to external factors (API down, missing file, etc.), add resilient handling
4. **Ensure visibility** — every error that cannot be prevented MUST notify the user (via Telegram, log, or both). No `except: pass`, no `try/except` that swallows errors silently. If catching an exception, at minimum log with `logging.error()` and notify on Telegram when possible

**Principle:** The user must know when something went wrong — even if the bot recovers automatically. Silent errors accumulate and create bigger problems later.

## Common Tasks

### Adding a new command

1. Add a `cmd_<name>` method to the `ClaudeTelegramBot` class
2. Register it in the `handler_map` dict inside `_handle_text()` (search `handler_map = {`)
3. Add it to `HELP_TEXT` so `cmd_help()` surfaces it
4. Add a dispatch test in `tests/test_bot_integration.py` and, if the command mutates state, a round-trip test

### Changing default model/timeouts

Edit the constants at the top of `claude-fallback-bot.py`:
- `DEFAULT_MODEL` — default model for new sessions
- `config["timeout"]` — default timeout in seconds
- `STREAM_EDIT_INTERVAL` — seconds between Telegram message edits
- `TYPING_INTERVAL` — seconds between typing indicators

## Versioning and Commits

### Semantic Versioning

The project follows **[Semantic Versioning 2.0.0](https://semver.org/)** (MAJOR.MINOR.PATCH). The version lives in two places — **always update both together**:

1. `claude-fallback-bot.py`, line `BOT_VERSION = "X.Y.Z"` — with a descriptive comment of the change
2. `ClaudeBotManager/Sources/App/Info.plist`, field `CFBundleShortVersionString`

### When to bump (golden rule)

**Every change that affects bot runtime behavior MUST bump the version.** This includes bug fixes, new commands, prompt changes, constant changes, and refactoring that changes behavior. The version identifies what's running — without a bump, there's no way to distinguish builds.

**DO NOT bump** for purely documentation changes (CLAUDE.md, README, code comments) or vault files (skills, routines, journal) that don't alter bot code.

### How to decide the bump type

| Type | When to use | Examples |
|------|------------|----------|
| **PATCH** (+0.0.1) | Bug fix, behavior adjustment, config/constant change, prompt tweak | fix: timeout correction, adjust `STREAM_EDIT_INTERVAL` |
| **MINOR** (+0.1.0) | New feature, new command, user-visible behavior change, structural refactoring | feat: add `/voice`, new inline keyboard handler |
| **MAJOR** (+1.0.0) | Breaking change — alters `sessions.json` format, changes existing command API incompatibly, architecture redesign | SessionManager redesign, data format migration |

**Practical tip:** If in doubt between PATCH and MINOR, ask: "will the user notice the difference?" If yes → MINOR. If no → PATCH.

### Proactive version bump

**Bump the version IN THE SAME commit as the change** — never in a separate commit. The bump is part of the change, not a separate task.

Mandatory sequence for changes to `claude-fallback-bot.py`:
```bash
# 1. Make the code change
# 2. Bump version in both files (same commit)
# 3. Verify syntax
python3 -m py_compile claude-fallback-bot.py
# 4. Commit everything together
git add claude-fallback-bot.py ClaudeBotManager/Sources/App/Info.plist
git commit -m "feat: add /foo command"
```

### Conventional Commits

Follow **[Conventional Commits](https://www.conventionalcommits.org/)** for commit messages:

| Prefix | Use | Implied bump |
|--------|-----|--------------|
| `feat:` | New feature | MINOR |
| `fix:` | Bug fix | PATCH |
| `refactor:` | Code change without external behavior change | PATCH (if runtime) or none |
| `docs:` | Documentation only | none |
| `chore:` | Maintenance, tooling, configs without runtime impact | none |

The commit prefix **implies** the bump type — `feat:` → MINOR, `fix:` → PATCH. Don't use `chore: bump version` as a standalone commit.

### When to commit

**Commit proactively** after each coherent change — don't accumulate unrelated changes in a single commit.

Commit immediately after:
- Any change to `claude-fallback-bot.py` (with version bump)
- Creating or editing a skill, routine, or agent in the vault
- Changes to CLAUDE.md (root or vault)
- Changes to configuration (`.env`, plist, `settings.local.json`)

## Routines

### Frontmatter fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `type` | string | `routine` | `routine` or `pipeline` |
| `schedule.times` | list | — | Times HH:MM (24h) — required unless `interval` is set |
| `schedule.interval` | string | — | Run every N units: `30m`, `4h`, `3d`, `2w` — replaces `times` |
| `schedule.days` | list | `["*"]` | Weekdays or `["*"]` for all (works with `times` and `interval`) |
| `schedule.monthdays` | list | — | Days of month e.g. `[1, 15]` — filter for both clock and interval modes |
| `schedule.until` | string | — | End date YYYY-MM-DD (optional) |
| `model` | string | `sonnet` | Model to use |
| `agent` | string | — | Agent to route execution to |
| `enabled` | bool | `true` | Enable/disable the routine |
| `context` | string | `full` | `minimal` = skip vault system prompt, use only CLAUDE.md |
| `effort` | string | — | Reasoning effort: `low`, `medium`, or `high` (CLI default if omitted) |
| `voice` | bool | `false` | Also send response as audio (TTS) |
| `notify` | string | `final` | Pipeline only: `final\|all\|summary\|none` |

### Minimal vs full context

- **`full`** (default): Claude receives the `SYSTEM_PROMPT` that instructs it to read Journal, Tooling, vault. Good for routines that need vault context.
- **`minimal`**: The `--append-system-prompt` is omitted. Claude runs only with the CLAUDE.md files from the directory hierarchy (automatic by CLI). Saves tokens and is faster for one-off tasks.

### Pipeline notifications

Pipelines notify via `_notify_success` / `_notify_failure`. The step marked with `output: telegram` has its output (content of the `data/{id}.md` file) sent to Telegram. If the step already sends to Telegram via its own API (e.g., publisher), use `output: none` to avoid duplication. The `notify` field controls:
- `final` — sends output of the marked step (or last step) on completion
- `all` — sends progress on each step completion
- `summary` — sends compact summary (X/Y steps in Nm Ns)
- `none` — silent (failures always notify)

### `NO_REPLY` routine

If the output of a routine (not pipeline) is exactly `NO_REPLY`, the bot sends nothing to Telegram. Used for routines that send messages manually or that should run silently.

### Built-in routines (committed to repo)

| Routine | Description |
|---------|-------------|
| `update-check` | Checks daily for Claude Code CLI (brew) or repo (git) updates. Notifies only when there's something to update. |
| `vault-graph-update` | Regenerates the vault's lightweight knowledge graph (`vault/.graphs/graph.json`) from frontmatter and wikilinks. No LLM cost. Runs daily at 4am. Active Memory depends on this graph. |
| `vault-indexes-update` | Auto-regenerates the marker blocks inside `Routines.md`, `Skills.md`, and `Agents.md` so index files stay in sync with actual vault content. |
| `vault-lint` | Daily vault hygiene check — frontmatter completeness, broken wikilinks, schedule sanity, orphan notes, stale routines. Runs `scripts/vault_lint.py`. |
| `journal-audit` | Nightly audit (23:59) that checks all agents' journals for completeness, fixes frontmatter, and fills gaps from the activity log. |

## Voice / TTS

The bot supports voice responses (Text-to-Speech) via macOS `say` + ffmpeg (OGG Opus):

- **`/voice on`** — enables TTS for all subsequent session messages (text + audio)
- **`/voice off`** — disables TTS
- **`#voice` in message** — one-shot TTS (audio only, no text)
- **`voice: true` in frontmatter** — routines/pipelines deliver response as audio

Voice follows the `HEAR_LOCALE` (default `pt-BR` → Luciana voice). The TTS prompt instructs Claude to respond in the configured language, without emojis, short and conversational. Emojis are removed from audio via `_strip_markdown()`.

## Active Memory (v2.34.0+)

Active Memory is a deterministic pre-reply hook inspired by OpenClaw v2026.4.10. Before each interactive Claude turn, the bot scores non-skill nodes from `vault/.graphs/graph.json` against the user's prompt and appends a compact `## Active Memory` block — with short (≤400 char) file excerpts — to the system prompt. No LLM call, ~50 ms typical, 200 ms hard budget, fail-open.

- **Scope:** interactive chat only. Routines and pipelines with `context: minimal` automatically skip it because they pass `system_prompt=None`.
- **Excluded node types:** `skill` (already covered by the skill hint helper below) and `history` (churn-y logs).
- **Per-session toggle:** `/active-memory [on|off|status]` — persists to `sessions.json` via the new `Session.active_memory` field.
- **Global toggle:** `ACTIVE_MEMORY_ENABLED = True` constant at the top of `claude-fallback-bot.py`.
- **Cache:** `_active_memory_graph_cache` dict keyed by absolute graph path, mtime-invalidated so the daily `vault-graph-update` routine transparently refreshes it.
- **Tests:** `tests/test_active_memory.py` — 13 tests covering keyword matching, skill/history exclusion, node/excerpt caps, frontmatter stripping, cache invalidation, missing-graph fail-open, global/per-session gating, and command registration.

## Graph-based skill hints

Separate from Active Memory but complementary: `_select_relevant_skills()` reads the same `vault/.graphs/graph.json` and injects a short `<hint>Relevant skills for this task: …</hint>` prefix into the user prompt on every interactive message. Filters to `type=="skill"` only. Controlled by `SKILL_HINTS_ENABLED = True`. Tests in `tests/test_skill_hints.py`.

The two helpers run in sequence inside `_run_claude_prompt()`:
1. `_find_relevant_skills()` (via `vault_query`) — appends "## Available Skills" block to the system prompt
2. `_active_memory_lookup()` — appends "## Active Memory" block to the system prompt
3. `_select_relevant_skills()` (via graph.json) — prepends `<hint>` to the user prompt

## Lessons (compound engineering)

`vault/Lessons/` captures hard-won knowledge so Claude can scan past failures before starting a similar task. Two entry points:

- **Automatic:** the session consolidator records lessons when the session detects a resolved bug or clear learning
- **Manual:** `/lesson <text>` writes `vault/Lessons/manual-YYYY-MM-DD-HHMM.md` with structured frontmatter (`type: lesson`, `status: recorded`)

The SYSTEM_PROMPT instructs Claude to scan `Lessons/` before similar tasks. Tests in `tests/test_lessons.py`.

## Auto-compact and session rotation

- **Auto-compact**: every `AUTO_COMPACT_INTERVAL` (25) turns, runs `/compact` in background
- **Auto-rotate**: after `AUTO_ROTATE_THRESHOLD` (80) turns, resets session_id (next message starts a new session)
- Applies only to interactive sessions (routines use session_id=None)

## Watchdog

`bot-watchdog.sh` runs via launchd every 60s (`com.claudebot.bot-watchdog.plist`):
- If the bot is not running: restarts via `launchctl start` and notifies on Telegram
- If the bot came back: sends recovery message
- Uses flag file (`~/.claude-bot/.watchdog-notified`) to notify only once per downtime

## ClaudeBotManager

Native macOS app (SwiftUI) in `ClaudeBotManager/`. Menu bar app for managing the bot:
- Dashboard with bot status and sessions
- Agent, routine, and skill management (redesigned UI v2.3)
- Pipeline creation and editing with expandable step editor
- Delete via macOS Trash (recoverable from Finder)
- Minimal context toggle for routines
- Settings editing (.env)
- Log viewer with filters and search

### Build and deploy

The app is distributed as an `.app` bundle (required to preserve macOS permissions between builds):

```bash
# Build + assemble .app + restart — normal usage
cd ClaudeBotManager && bash build-app.sh
```

The `build-app.sh` script:
1. Compiles with `swift build -c release` using Xcode 26 toolchain
2. Assembles `ClaudeBotManager.app/Contents/` with the binary and `Info.plist`
3. Signs with ad-hoc identity (`codesign --sign -`)
4. Kills the previous process and opens the new bundle

**Why .app bundle?** Without a bundle, macOS has no stable identity (`Info.plist=not bound`) and asks for permissions (TCC) on every new build. With the bundle, permissions are bound to `CFBundleIdentifier=com.claudebot.manager`.

The `.app` is generated at `ClaudeBotManager/ClaudeBotManager.app` (gitignored — build artifact).

### Design System (LiquidGlassTheme.swift)

Shared components:

| Component | Description |
|-----------|-------------|
| `GlassCard` | Main container with `.ultraThinMaterial` + 0.5pt border |
| `SectionCard` | GlassCard with header (title + SF Symbol) |
| `SettingRow` | `.callout` label + right-aligned control |
| `ModelBadge` | Color-coded badge by model (opus=purple, haiku=green, others=blue) |
| `StatusDot` | Circle with pulse animation when `isRunning` |
| `UsageBar` | Progress bar colored by percentage |
| `EmptyStateView` | Centered empty state with 48pt icon |
| `FlowLayout` | Wrapping layout for chips and pipeline dependencies |

Spacing scale: `Spacing.xs(4) sm(8) md(12) lg(16) xl(20) xxl(24)`

### Sidebar

Collapsible. Grouped in 3 sections:
- **Overview** — Dashboard
- **Manage** — Agents, Routines, Skills
- **System** — Sessions, Logs, Settings, Changelog

Each item shows a badge with count (Agents, Routines, Skills) or status (Dashboard: "Running", Logs: "⚠ N"). Changelog shows the version (vX.Y.Z).

### Agents

The **Main Agent** is the bot's default agent (no own workspace). It counts as an agent in sidebar counts and Dashboard stat chips. Total agent count is always `appState.agents.count + 1` (custom agents + Main).

## Vault

The `vault/` directory is the bot's persistent knowledge base — an Obsidian graph with Journal, Notes, Skills, Routines, and Agents. See `vault/CLAUDE.md` for complete documentation of the vault structure and rules.

### Setup for new users

The vault's index files (`Agents/Agents.md`, `Routines/Routines.md`, `Journal/Journal.md`) are committed with placeholder content. When setting up the bot for the first time, each user should:

1. Edit the index files to reflect their own agents/routines
2. Create their `vault/.env` with their own API keys (gitignored)
3. Customize `vault/Tooling.md` with their tool preferences

The personal content of indexes (list of agents, routines, journal entries) SHOULD NOT be committed — keep local only.

## Context isolation

Claude Code loads ALL CLAUDE.md files in the directory hierarchy (from cwd to root + `~/.claude/CLAUDE.md`). To ensure the bot uses ONLY this project's instructions:

**`.claude/settings.local.json`** (gitignored):
```json
{
  "claudeMdExcludes": [
    "/Users/YOUR_USERNAME/CLAUDE.md",
    "/Users/YOUR_USERNAME/.claude/CLAUDE.md"
  ]
}
```

This blocks CLAUDE.md from other projects (e.g., OpenClaw) when Claude CLI runs with `cwd` inside this project.

**Dev/runtime separation:** This CLAUDE.md contains DEVELOPMENT instructions. `vault/CLAUDE.md` contains the bot's OPERATIONAL knowledge base. When the bot invokes Claude CLI with `cwd=vault/`, Claude sees primarily vault/CLAUDE.md. This file (from root) loads as parent in the hierarchy, but contains only development info — it doesn't interfere with bot operations.

## Tests

The test suite covers the bot's Python code, scripts, and the Swift `ClaudeBotManager` app. **No pip dependencies** for the Python suite — pure stdlib (`unittest` + `unittest.mock`). Swift tests use XCTest.

### Running tests

```bash
./test.sh           # Python + Swift (full suite)
./test.sh py        # Python only (~380 tests, ~5s)
./test.sh swift     # Swift only (~20 tests)
./test.sh tests.test_session_manager  # one Python module
```

CI runs on every push/PR via `.github/workflows/tests.yml` (macOS runner — required for Swift + macOS-specific calls).

### Layout

```
tests/                              # Python tests (~380 tests, pure stdlib)
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

### Test harness — `tests/_botload.py`

The bot script (`claude-fallback-bot.py`) is hyphenated and touches `~/.claude-bot/` at import time, so we can't `import claude_fallback_bot`. The harness:

1. Forces `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` env vars (so the `.env` loader is bypassed)
2. Points `HOME` at a `tempfile.TemporaryDirectory` so the bot's data files land in a sandbox
3. Imports the script via `importlib.util.spec_from_file_location` as a fresh module
4. Repoints `DATA_DIR`, `VAULT_DIR`, etc. so subsequent operations stay in the tmp tree
5. Closes the rotating-file log handler to avoid `ResourceWarning` leaks

Use `load_bot_module(tmp_home, vault_dir)` from any test that needs the bot module.

### Adding tests when you change the bot

The "zero silent errors" rule means **any new error path needs a test**. When you add a feature:

- **New routine field** → add a test in `test_routine_scheduler.py` covering both presence and absence
- **New command** → add a test in `test_bot_integration.py::CommandDispatch`
- **New persisted field on Session/sessions.json** → update `test_contracts.py::SessionsJsonRoundTrip::test_session_dataclass_has_stable_fields` (this guards against accidental removal)
- **New stream-json event type** → add a case in `test_claude_runner.py::HandleEvent`
- **New shell script** → automatically picked up by `test_smoke_compile.py::ShellScriptsSyntaxOk`

### What is NOT tested (by design)

- Real Telegram API calls (flaky, requires token)
- Real Claude CLI subprocess (slow, expensive, non-deterministic)
- Semantic content of LLM responses
- SwiftUI views (cost too high vs. value — covered by previews)
- Vault markdown content as truth (it's user data, not code)

## Knowledge Graph (Graphify)

The vault has a knowledge graph at `vault/.graphs/graph.json`, generated by the `scripts/vault-graph-builder.py` script (no LLM). For deep on-demand analysis, use `/graphify vault/` which triggers the full Graphify with semantic extraction.

- The `vault-graph-update` routine regenerates the lightweight graph daily at 4am
- The graph maps nodes (files) and edges (wikilinks + related) with confidence labels
- Query the graph before extensive globbing in the vault to find relationships
