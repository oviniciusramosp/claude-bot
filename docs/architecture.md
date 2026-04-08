# System Architecture

## Overview

Claude Bot is a pure-Python Telegram bot that spawns Claude Code CLI as a subprocess, streams its JSON output back to Telegram as live message edits, and persists context across messages using Claude's `--resume` flag. A native macOS SwiftUI app provides menu bar controls and dashboard views.

```
                                 +--------------------+
                                 |  ClaudeBotManager  |
                                 |  (SwiftUI macOS)   |
                                 +--------+-----------+
                                          |
                                    HTTP control API
                                    (localhost:27182)
                                          |
+--------+     HTTPS      +--------------+-------------+     subprocess     +-----------------+
|  User  | <----------->  |  claude-fallback-bot.py    | <----------------> |  Claude Code    |
| (Tele- |   Telegram     |                            |   stream-json     |  CLI            |
|  gram) |   Bot API      |  - Polling loop            |                   |  (--resume)     |
+--------+                |  - Session manager          |                   +-----------------+
                          |  - Routine scheduler        |
                          |  - Pipeline executor        |
                          |  - Control HTTP server      |
                          +--------------+--------------+
                                         |
                                    reads/writes
                                         |
                                +--------v---------+
                                |  vault/           |
                                |  (Obsidian KB)    |
                                |  Journal, Notes,  |
                                |  Skills, Routines |
                                +------------------+
```

## Components

### Bot (Python)

`claude-fallback-bot.py` -- the core process. Pure Python stdlib, zero pip dependencies. Handles Telegram long-polling, message routing, Claude CLI orchestration, session persistence, routine scheduling, and pipeline execution. Runs as a macOS launchd service.

### Manager (SwiftUI)

`ClaudeBotManager/` -- native macOS menu bar app built with SwiftUI. Provides a dashboard showing bot status, active sessions, routine schedules, and settings editing. Communicates with the bot via its HTTP control server on `localhost:27182`.

### Vault (Obsidian)

`vault/` -- an Obsidian-compatible knowledge base. Claude reads it for context and writes to it to preserve knowledge. Contains daily journal entries, durable notes with wikilinks, reusable skills, scheduled routines, and agent definitions.

### CLI (Claude Code)

The bot spawns Claude Code CLI as a child process with `--output-format stream-json` and `--resume <session_id>`. This gives real session persistence (Claude maintains its full conversation context across messages) and structured streaming output that the bot parses line by line.

## Threading Model

The bot uses multiple threads to keep the Telegram polling loop responsive while Claude CLI runs:

| Thread | Name | Purpose |
|--------|------|---------|
| **Main thread** | -- | Telegram long-polling loop. Dispatches each update to a handler thread so polling never blocks. |
| **Handler threads** | (unnamed, daemon) | One per incoming Telegram update. Processes commands, routes messages, handles callbacks. |
| **Runner thread** | (daemon) | Executes `ClaudeRunner.run()` -- spawns the Claude CLI subprocess and reads its stream-json output line by line. |
| **Watchdog thread** | (daemon) | Monitors the runner for inactivity timeouts (no output for 90s), total execution timeout (600s default), and activity timeouts (configurable). Sends SIGINT/SIGTERM/SIGKILL escalation on timeout. |
| **Stream update thread** | Inline in handler | Loops every 1s while the runner is alive, editing the Telegram message with accumulated text, updating emoji reactions, and sending typing indicators. Rate-limited to one edit every 3 seconds. |
| **Routine scheduler** | `routine-scheduler` | Background daemon that wakes every 60 seconds, scans `vault/Routines/` for `.md` files with matching schedules, and enqueues them for execution. |
| **Routine/Pipeline runners** | `routine-<name>`, `pipeline-<name>` | Daemon threads spawned to execute scheduled routines or pipeline steps without blocking the main queue. |
| **Pipeline step threads** | (daemon) | Within a pipeline, each wave of independent steps runs in parallel threads. |
| **Control server** | `control-server` | HTTP server on `localhost:27182` that accepts status queries and stop commands from the Manager app. |

## Data Flow

The lifecycle of a user message from Telegram to Claude and back:

1. **Polling**: The main thread calls `getUpdates` on the Telegram Bot API with a long-poll timeout. Telegram returns a batch of updates.

2. **Dispatch**: For each update, the bot checks authorization (`TELEGRAM_CHAT_ID`), resolves the `ThreadContext` for the chat/topic pair, and spawns a handler thread.

3. **Command routing**: If the message starts with `/`, it is routed to the corresponding command handler. Otherwise, it is treated as a prompt for Claude.

4. **Runner launch**: The bot increments the session turn counter, sends a "Processing..." placeholder message, sets an eye reaction on the user's message, and spawns two threads:
   - **Runner thread**: Builds the CLI command (`claude --print --dangerously-skip-permissions --model <model> --output-format stream-json --verbose --resume <session_id> --append-system-prompt <prompt> -p <message>`), starts the subprocess with `cwd` set to the session workspace, and reads stdout line by line parsing JSON events.
   - **Watchdog thread**: Polls the runner every 5 seconds checking for timeout conditions.

5. **Streaming**: While the runner thread is alive, the handler thread loops every 1 second:
   - Reads `runner.accumulated_text` and edits the Telegram placeholder message (rate-limited to every 3 seconds).
   - Updates the emoji reaction based on `runner.activity_type` (thinking, tool use, writing).
   - Sends typing indicators every 4 seconds.

6. **Finalization**: When the runner thread exits:
   - The final response text is sent/edited into Telegram, split into multiple messages if it exceeds 4000 characters (respecting Markdown code block boundaries).
   - The Claude session ID captured from the stream output is saved to the session for future `--resume` calls.
   - The emoji reaction is removed.
   - Any queued pending messages for this context are processed next.

## Key Classes

### Session (dataclass)

Holds the state of a single conversation: name, Claude session ID (for `--resume`), model name, workspace path, active agent, creation timestamp, and message/turn counters.

### SessionManager

CRUD for sessions. Loads from and persists to `~/.claude-bot/sessions.json`. Tracks the active session and cumulative turn count across all sessions.

### ClaudeRunner

Spawns Claude Code CLI as a subprocess and processes its `stream-json` output. Maintains running state, accumulated text, tool call log, cost tracking, captured session ID, and error information. Supports cancellation via SIGINT -> SIGTERM -> SIGKILL escalation.

### ThreadContext (dataclass)

Per-topic/chat execution context. Each Telegram topic (or private chat) gets its own instance. Holds the chat ID, thread ID, runner reference, session binding, pending message queue, and stream state (current message ID, last edit time, reaction state).

### PipelineExecutor

Executes a pipeline of steps as a DAG with a shared temporary workspace. Steps are organized into waves -- each wave contains steps whose dependencies are all satisfied. Steps within a wave run in parallel threads. Supports retries, output passing between steps, and status reporting.

### RoutineScheduler

Background thread that wakes every 60 seconds and scans `vault/Routines/` for Markdown files with `schedule` frontmatter. Compares against today's execution state to determine which routines are due. Enqueues matching routines and pipelines for execution.

### RoutineStateManager

Tracks daily routine execution state in `~/.claude-bot/routines-state/YYYY-MM-DD.json`. Records when each routine started, completed, or failed. Prevents duplicate execution within the same schedule window.

### ClaudeTelegramBot

The main orchestrator class. Initializes all subsystems (sessions, routine scheduler, control server, voice tools), runs the Telegram long-polling loop, routes commands and messages, manages thread contexts, and coordinates the runner/watchdog/stream lifecycle.

## File Layout

### Project Files

```
claude-bot/
  claude-fallback-bot.py           Core bot (Python stdlib only)
  claude-bot-menubar.py            Menu bar indicator (requires rumps)
  claude-bot.sh                    Service manager (install/start/stop/status)
  com.vr.claude-bot.plist          launchd template (bot)
  com.vr.claude-bot-menubar.plist  launchd template (menu bar)
  .env                             Bot configuration (gitignored)
  .env.example                     Template for .env
  CLAUDE.md                        Development instructions for Claude Code
  ClaudeBotManager/                SwiftUI macOS app source
  vault/                           Obsidian knowledge vault
  docs/                            Documentation (this directory)
```

### Runtime Data (~/.claude-bot/)

```
~/.claude-bot/
  sessions.json              Session persistence (names, IDs, models, agents)
  contexts.json              Thread context-to-session mappings
  bot.log                    Application log (rotating, 5MB x 3 backups)
  launchd-stdout.log         Process stdout from launchd
  launchd-stderr.log         Process stderr from launchd
  routines-state/            Daily routine execution tracking
    YYYY-MM-DD.json          One file per day with routine run records
  bin/                       Downloaded binaries
    hear                     macOS speech recognition CLI
  .control-token             Auth token for the HTTP control server
```

### Vault Paths

```
vault/
  CLAUDE.md                  Operational instructions for Claude (runtime)
  .env                       API keys for vault tasks (gitignored)
  Tooling.md                 Tool preferences
  Journal/                   Daily logs (YYYY-MM-DD.md), append-only
  Notes/                     Durable knowledge with wikilinks
  Skills/                    Reusable task definitions
  Routines/                  Scheduled prompt definitions
  Agents/                    Agent definitions (each with CLAUDE.md + Journal/)
  Images/                    Stored images organized by theme
```

### Configuration Files

| File | Purpose |
|------|---------|
| `.env` (project root) | Bot operational config: Telegram token, chat ID, CLI paths |
| `vault/.env` | API keys for vault tasks: Notion, Figma, etc. |
| `.claude/settings.local.json` | Claude Code context isolation (excludes parent CLAUDE.md files) |
