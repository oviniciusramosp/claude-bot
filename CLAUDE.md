# Claude Bot — Development Guide

**IMPORTANT:** This is the DEVELOPMENT CLAUDE.md for the claude-bot project. It contains instructions for working on the bot's code (Python, Swift, shell scripts). For the bot's operational knowledge base (vault, routines, agents, journal), see `vault/CLAUDE.md`.

Topic-specific rules live in `.claude/rules/` and auto-load when Claude reads matching files:
- `testing.md` — test suite layout, harness, how to add tests (when touching `tests/**`)
- `vault-runtime-features.md` — routines, voice, active memory, advisor, lessons (when touching `claude-fallback-bot.py`)
- `multi-provider-models.md` — z.AI GLM gateway details (when touching `claude-fallback-bot.py`)
- `macos-manager.md` — ClaudeBotManager app, build, design system (when touching `ClaudeBotManager/**`)
- `migration-v31.md` — vault v3.1 migration script (when touching `scripts/migrate_vault_per_agent.py`)

## Overview

Telegram bot that provides remote access to [Claude Code CLI](https://code.claude.com/docs) via Telegram messages. Pure Python (stdlib only), runs as a macOS launchd service.

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

- **`Session`** (dataclass) — name, Claude session ID, model, workspace, agent, created_at, message_count, total_turns, active_memory (per-session toggle, default `True`)
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

### v3.1 flat per-agent vault layout

Default workspace: `vault/main/` — the bot operates as the Main agent by default. Every session has an explicit `agent` string (defaults to `"main"`) and cwd is always `vault/<agent>/`.

```
vault/
├── CLAUDE.md        # universal rules + wikilinks to each agent hub
├── README.md        # root hub
├── Tooling.md       # shared
├── main/
│   ├── agent-main.md   # metadata (frontmatter) + hub wikilinks (body)
│   ├── CLAUDE.md       # personality/instructions (not a graph node)
│   └── Skills/, Routines/, Journal/, Reactions/, Lessons/, Notes/, workspace/
├── crypto-bro/      # same structure, isolated
└── parmeirense/
```

**Isolamento total:** no inheritance between agents. When a session is on crypto-bro, only `crypto-bro/Skills/`, `Routines/`, `Journal/`, etc. are discoverable.

**Agent detection.** A top-level directory counts as an agent if and only if it contains `agent-<dirname>.md`. That's the single source of truth — `iter_agent_ids()` (Python) and `iterAgentIds()` (Swift) use this rule. Reserved vault names (`README.md`, `CLAUDE.md`, `Tooling.md`, `Images`, `.graphs`, `.obsidian`) are never agents.

## Configuration

The project uses **two `.env` files with distinct purposes**:

### `~/claude-bot/.env` — Bot operational config

Read by `claude-fallback-bot.py` at startup and by ClaudeBotManager. Contains credentials and paths:

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | — | Telegram bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | — | Authorized Telegram chat ID |
| `CLAUDE_PATH` | No | `/opt/homebrew/bin/claude` | Path to Claude CLI binary |
| `CLAUDE_WORKSPACE` | No | `vault/main/` | Working directory for Main sessions |
| `ZAI_API_KEY` | No | — | z.AI API key — required for any `glm-*` model. See `.claude/rules/multi-provider-models.md` |
| `ZAI_BASE_URL` | No | `https://api.z.ai/api/anthropic` | z.AI's Anthropic-compatible gateway |
| `ADVISOR_MODEL` | No | `opus` | Model used by `scripts/advisor.sh` when escalating |
| `MODEL_FALLBACK_CHAIN` | No | `opus,glm-5.1,sonnet,glm-4.7,haiku` | Fallback order when a model fails. Configurable via macOS app. |

Edited via: ClaudeBotManager → Settings, or directly.

### `vault/.env` — API keys for vault tasks

Read by Claude Code when executing tasks in the vault context. Contains keys for external services (Notion, Figma, etc.). **Does not contain** Telegram credentials or bot paths.

**Why separate?** `vault/` can be synced (iCloud, Git) — mixing Telegram tokens with third-party keys would be a security risk. Bot ops config stays local; workspace keys stay in the vault.

## Bot Commands

| Command | Description |
|---------|-------------|
| `/start`, `/help` | Show help |
| `/status` | Session & process info |
| `/sonnet`, `/opus`, `/haiku` | Quick model switch (Anthropic) |
| `/glm` | Quick switch to `glm-4.7` (z.AI) — requires `ZAI_API_KEY` |
| `/model` | Model picker (inline keyboard; GLM row shown only when `ZAI_API_KEY` is set) |
| `/new [name]` | Create new session |
| `/sessions` | List all sessions |
| `/switch <name>` | Switch session |
| `/delete <name>` | Delete session |
| `/clone <name>` | Clone the current session into a new branch |
| `/run [name]` | Manually trigger a routine/pipeline |
| `/compact` | Auto-compact context |
| `/cost` | Token usage and cost for current session |
| `/doctor` | Check Claude Code installation health |
| `/lint` | Audit the vault |
| `/find <expr>` | Query the vault by frontmatter |
| `/indexes` | Regenerate vault index marker blocks |
| `/btw <msg>` | Inject message to running Claude process |
| `/delegate <prompt>` | Spawn an isolated subagent (fresh context, 10min hard limit) |
| `/stop` | Cancel running task |
| `/timeout <sec>` | Change timeout |
| `/workspace <path>` | Change working directory |
| `/effort <low\|medium\|high>` | Set reasoning effort |
| `/clear` | Reset current session |
| `/important` | Record key points from the current session into today's Journal |
| `/lesson <text>` | Record a manual lesson in `<agent>/Lessons/` |
| `/active-memory [on\|off\|status]` | Toggle proactive vault context injection |
| `/agent [name\|new\|list]` | Switch/create/list agents |
| `/routine [list\|status]` | Create a routine interactively, or list/status |
| `/skill [name]` | Run a vault skill directly |
| `/voice [on\|off]` | Toggle TTS voice responses |
| `/audio` | Choose transcription language |
| `#voice` (in message) | One-shot voice response (audio only) |

## Development Guidelines

- **No pip dependencies** for the main bot (`claude-fallback-bot.py`). Only stdlib.
- The menu bar app (`claude-bot-menubar.py`) requires `rumps`.
- Telegram API calls use raw `urllib.request` (no `requests` library).
- All Telegram message edits are rate-limited (`STREAM_EDIT_INTERVAL = 3.0s`).
- Long messages are split respecting Markdown code blocks.
- The bot validates `AUTHORIZED_CHAT_ID` on every incoming message — unauthorized messages are silently ignored.
- Plist files use `__HOME__` and `__SCRIPT_DIR__` placeholders — the install script (`claude-bot.sh`) substitutes them via `sed`.

<important if="writing or modifying bot code">

## Error handling — zero silent errors

When encountering an error, **never treat it as a one-off**. Follow this mandatory flow:

1. **Investigate the root cause** — don't fix just the symptom. Trace the error path to the real origin (invalid data, inconsistent state, race condition, etc.)
2. **Fix the root cause** — the fix must eliminate the class of error, not just the observed instance
3. **Add structural protection** — implement validation, guard clause, or check to prevent recurrence. If the error can return due to external factors (API down, missing file, etc.), add resilient handling
4. **Ensure visibility** — every error that cannot be prevented MUST notify the user (via Telegram, log, or both). No `except: pass`, no `try/except` that swallows errors silently. If catching an exception, at minimum log with `logging.error()` and notify on Telegram when possible

**Principle:** The user must know when something went wrong — even if the bot recovers automatically. Silent errors accumulate and create bigger problems later.

</important>

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

<important if="committing code">

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

</important>

## Vault

The `vault/` directory is the bot's persistent knowledge base — an Obsidian graph with Journal, Notes, Skills, Routines, and Agents. See `vault/CLAUDE.md` for complete documentation of the vault structure and rules.

### Setup for new users

The vault's index files (`Agents/Agents.md`, `Routines/Routines.md`, `Journal/Journal.md`) are committed with placeholder content. First-time setup:

1. Edit the index files to reflect your own agents/routines
2. Create your `vault/.env` with your own API keys (gitignored)
3. Customize `vault/Tooling.md` with your tool preferences

Personal content of indexes SHOULD NOT be committed — keep local only.

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
