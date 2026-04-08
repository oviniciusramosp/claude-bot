# Development Guide

How to understand, modify, and extend the claude-bot project.

## Project Structure

```
claude-bot/
  claude-fallback-bot.py           # Main bot (Telegram polling, session mgmt, Claude CLI)
  claude-bot-menubar.py            # macOS menu bar indicator (requires rumps)
  claude-bot.sh                    # Service manager (install/start/stop/restart/status/logs)
  com.vr.claude-bot.plist          # launchd template for the bot
  com.vr.claude-bot-menubar.plist  # launchd template for the menu bar app
  CLAUDE.md                        # Development instructions (this project)
  .env                             # Bot operational config (tokens, paths)
  vault/                           # Knowledge base (Obsidian vault)
    CLAUDE.md                      # Runtime/operational instructions
    .env                           # API keys for vault tasks
  ClaudeBotManager/                # Native macOS SwiftUI app
    Sources/
    Package.swift
  docs/                            # Project documentation
```

### Key Files

| File | Purpose |
|------|---------|
| `claude-fallback-bot.py` | The entire bot in one file. Telegram polling, session management, Claude CLI orchestration, routine scheduling, pipeline execution, voice transcription, image handling. |
| `claude-bot.sh` | Shell script to manage the bot as a macOS launchd service. Also handles dependency installation (`install-deps`). |
| `com.vr.claude-bot.plist` | launchd plist template. Uses `__HOME__` and `__SCRIPT_DIR__` placeholders that `claude-bot.sh install` replaces via `sed`. |
| `vault/` | Obsidian knowledge base. Default working directory for Claude Code sessions. See `docs/vault-structure.md`. |
| `ClaudeBotManager/` | SwiftUI macOS app for managing the bot (dashboard, agents, routines, settings, logs). |

### Key Classes

| Class | Responsibility |
|-------|---------------|
| `Session` | Dataclass holding session state: name, Claude session ID, model, workspace, agent, message count. |
| `SessionManager` | CRUD for sessions. Persists to `~/.claude-bot/sessions.json`. |
| `ClaudeRunner` | Spawns Claude CLI as a subprocess. Handles streaming JSON output, tool call logging, cancellation (SIGINT > SIGTERM > SIGKILL). |
| `ClaudeTelegramBot` | Main orchestrator. Telegram long-polling, command routing, inline keyboards, message splitting, routine/pipeline coordination. |
| `RoutineScheduler` | Background thread checking `vault/Routines/` every 60 seconds. Enqueues matching routines. |
| `PipelineExecutor` | DAG-based multi-step orchestration. Runs pipeline steps in parallel waves with shared workspace. |
| `RoutineStateManager` | Tracks daily routine execution state in `~/.claude-bot/routines-state/YYYY-MM-DD.json`. |
| `ThreadContext` | Per-topic/chat execution context. Each Telegram topic gets its own runner and session. |

### Runtime Data

All runtime data lives in `~/.claude-bot/`:

| File | Purpose |
|------|---------|
| `sessions.json` | Session persistence (names, IDs, models, agents) |
| `contexts.json` | Thread context to session mappings |
| `costs.json` | Weekly cost tracking |
| `bot.log` | Application log (rotating, 5 MB x 3 backups) |
| `launchd-stdout.log` | Process stdout |
| `launchd-stderr.log` | Process stderr |
| `routines-state/YYYY-MM-DD.json` | Daily routine execution state |
| `bin/hear` | Bundled hear binary for voice transcription |
| `.control-token` | Auth token for the HTTP control server |

## Development Setup

1. **Clone the repository:**
   ```bash
   git clone <repo-url> ~/claude-bot
   cd ~/claude-bot
   ```

2. **Create the `.env` file:**
   ```bash
   cp .env.example .env  # or create manually
   ```
   Required variables:
   ```env
   TELEGRAM_BOT_TOKEN=your-token-from-botfather
   TELEGRAM_CHAT_ID=your-numeric-chat-id
   ```

3. **Verify Claude Code CLI is installed:**
   ```bash
   which claude
   # Default expected path: /opt/homebrew/bin/claude
   ```

4. **Run directly (for development):**
   ```bash
   python3 claude-fallback-bot.py
   ```

5. **Or install as a launchd service:**
   ```bash
   ./claude-bot.sh install
   ./claude-bot.sh start
   ```

6. **Install voice dependencies (optional):**
   ```bash
   ./claude-bot.sh install-deps
   ```

## Adding a Command

Step-by-step to add a new Telegram command:

### 1. Add a handler method

Add a method to the `ClaudeTelegramBot` class:

```python
def _cmd_mycommand(self, args: str = "") -> None:
    """Handle /mycommand."""
    self.send_message("Hello from /mycommand!")
```

### 2. Register the command

Find the command routing in `_handle_command()` and add your command. Commands are matched by the text after `/`:

```python
elif cmd == "mycommand":
    self._cmd_mycommand(args)
```

### 3. Add help text

Update the help message in `_cmd_start()` to include your command description.

### 4. Register with Telegram autocomplete

Add to the `_register_commands()` method:

```python
{"command": "mycommand", "description": "Description for autocomplete"},
```

### 5. Verify syntax

```bash
python3 -m py_compile claude-fallback-bot.py
```

## Adding a Routine

Create a `.md` file in `vault/Routines/`:

```yaml
---
title: My Routine
description: What this routine does and when it runs.
type: routine
created: 2026-04-08
updated: 2026-04-08
tags: [routine, category]
schedule:
  times: ["09:00"]
  days: [mon, tue, wed, thu, fri]
model: sonnet
enabled: true
---

[[Routines]]

Your prompt here. This text is sent to Claude Code CLI when the routine triggers.
```

Then update `vault/Routines/Routines.md` to include the new routine in the index.

### Adding a Pipeline

Pipelines are multi-step routines. Create:

1. **Main file** at `vault/Routines/{name}.md`:
   ```yaml
   ---
   title: My Pipeline
   description: Multi-step orchestrated task.
   type: pipeline
   created: 2026-04-08
   updated: 2026-04-08
   tags: [pipeline]
   schedule:
     times: ["08:00"]
     days: ["*"]
   model: sonnet
   enabled: true
   notify: final
   ---

   [[Routines]]
   ```

   Then add a fenced pipeline block:

   ````
   ```pipeline
   steps:
     - id: step-one
       name: "First Step"
       model: haiku
       prompt_file: steps/step-one.md

     - id: step-two
       name: "Second Step"
       model: sonnet
       depends_on: [step-one]
       prompt_file: steps/step-two.md
       output: telegram
   ```
   ````

2. **Step prompt files** at `vault/Routines/{name}/steps/`:
   ```bash
   mkdir -p vault/Routines/{name}/steps
   ```
   Each step file contains the prompt text for that step.

## Adding an Agent

Create a directory in `vault/Agents/` with 3 required files:

```bash
mkdir -p vault/Agents/my-agent/Journal
```

### 1. `agent.md` -- Metadata (parsed by bot)

```yaml
---
title: My Agent
description: What this agent specializes in.
type: agent
name: My Agent
personality: Tone and style description
model: sonnet
icon: "emoji"
---
```

Body is empty.

### 2. `CLAUDE.md` -- Instructions for Claude Code

No frontmatter. No wikilinks. Just plain instructions:

```markdown
# My Agent emoji

## Personality
Description of tone and style.

## Instructions
- Record conversations in Journal/YYYY-MM-DD.md
- Specific instructions here

## Specializations
- Area of focus
```

### 3. `{agent-id}.md` -- Obsidian graph hub

```markdown
[[my-agent/Journal|Journal]]
[[agent]]
[[CLAUDE]]
```

### 4. Update the Agents index

Add to `vault/Agents/Agents.md`:
```markdown
- [[my-agent]] -- Description
```

## Testing

The project has no automated test suite. Testing is done manually:

### Syntax Check

Always verify syntax before committing:

```bash
python3 -m py_compile claude-fallback-bot.py
```

### Manual Testing via Telegram

1. Run the bot locally: `python3 claude-fallback-bot.py`
2. Send messages via Telegram to verify behavior.
3. Use `/status` to check session state.
4. Check logs: `tail -f ~/.claude-bot/bot.log`

### Testing Routines

- Set a routine's time to the current minute.
- Watch logs for the scheduler picking it up.
- Check `~/.claude-bot/routines-state/$(date +%Y-%m-%d).json` for execution state.

### Testing Pipelines

- Same approach, but also check `/tmp/claude-pipeline-*` for workspace state.
- Failed pipelines leave their workspace for debugging; successful ones clean up.

## Versioning

The project uses **Semantic Versioning** (MAJOR.MINOR.PATCH). The version lives in **two places** -- always update both together:

1. `claude-fallback-bot.py`, line `BOT_VERSION = "X.Y.Z"`
2. `ClaudeBotManager/Sources/App/Info.plist`, field `CFBundleShortVersionString`

### Bump Criteria

| Change | Version Bump | Example |
|--------|-------------|---------|
| Bug fix, prompt tweak, config change | PATCH | 2.0.0 -> 2.0.1 |
| New feature, behavior change, structural refactor | MINOR | 2.0.0 -> 2.1.0 |
| Breaking change to bot API, session/workspace redesign | MAJOR | 2.0.0 -> 3.0.0 |

## Commit Conventions

### When to Commit

Commit proactively after each coherent change. Do not batch unrelated changes.

Commit immediately after:
- Any change to `claude-fallback-bot.py`
- Creation or edit of a skill, routine, or agent in the vault
- Changes to `CLAUDE.md` (root or vault)
- Config changes (`.env`, plist, `settings.local.json`)

### Commit Message Format

```
type: concise description
```

| Type | Use For |
|------|---------|
| `feat` | New feature (`feat: add /foo command`) |
| `fix` | Bug fix (`fix: correct timeout in agent sessions`) |
| `refactor` | Restructuring without behavior change |
| `chore` | Maintenance (`chore: bump version 2.0.0 -> 2.1.0`) |

### Standard Sequence

```bash
# 1. Bump version if needed (both places)
# 2. Verify syntax
python3 -m py_compile claude-fallback-bot.py

# 3. Stage specific files
git add claude-fallback-bot.py vault/CLAUDE.md CLAUDE.md

# 4. Commit
git commit -m "feat: add /mycommand for ..."
```

## Key Constraints

These are hard constraints that must be respected in all changes:

- **No pip dependencies** for `claude-fallback-bot.py`. Only Python stdlib. The menu bar app (`claude-bot-menubar.py`) is the sole exception (requires `rumps`).
- **Telegram API via stdlib**: All HTTP calls use `urllib.request`. No `requests` library.
- **Rate limiting**: Telegram message edits are throttled to `STREAM_EDIT_INTERVAL` (3.0 seconds). Typing indicators are sent every `TYPING_INTERVAL` (4.0 seconds).
- **Message splitting**: Long messages (over 4000 chars) are split respecting Markdown code block boundaries.
- **Authorization check**: Every incoming message is validated against `authorized_ids`. Unauthorized messages are silently ignored.
- **Plist placeholders**: The `.plist` files use `__HOME__` and `__SCRIPT_DIR__` placeholders. The install script substitutes them with `sed`.
- **Vault as default workspace**: The bot runs Claude Code with `cwd=vault/` by default. Agents override this to `vault/Agents/{id}/`.
- **Context isolation**: The `.claude/settings.local.json` file should exclude external `CLAUDE.md` files to prevent instruction leakage from other projects.
