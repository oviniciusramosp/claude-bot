# Claude Bot

Turn your phone into a remote terminal for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Send messages from Telegram, get streamed responses with full session persistence, and build a personal knowledge vault that grows across every conversation.

```
Phone (Telegram) --> claude-fallback-bot.py --> Claude Code CLI (subprocess)
                          |
                          |-- Session persistence (--resume)
                          |-- Streaming output (JSON stream -> live edits)
                          |-- Reactions showing processing status
                          |-- Knowledge vault (Obsidian-compatible)
                          '-- Scheduled routines (cron-like)
```

**Pure Python stdlib** -- zero pip dependencies for the core bot.

---

## What You Get

- **Remote Claude Code access** from any phone via Telegram
- **Session persistence** -- context carries across messages via Claude's `--resume`
- **Live streaming** -- watch Claude's response build in real-time as Telegram message edits
- **Status reactions** -- emoji reactions on your message show what Claude is doing (thinking, coding, writing)
- **Model switching** -- switch between Sonnet, Opus, and Haiku mid-conversation
- **Knowledge vault** -- Obsidian-compatible vault with daily journal, notes, skills, and routines
- **Scheduled routines** -- cron-like system that runs prompts on a schedule
- **Image analysis** -- send photos from Telegram for Claude to analyze
- **macOS service** -- runs as a daemon with auto-start, crash recovery, and menu bar indicator

---

## Setup Guide

### Prerequisites

- **macOS** (uses launchd for service management)
- **Python 3.8+** (pre-installed on macOS)
- **Claude Code CLI** installed and authenticated
- **Telegram account**

### Step 1: Install Claude Code

Follow the [official guide](https://docs.anthropic.com/en/docs/claude-code/getting-started) to install and authenticate Claude Code.

Verify it works:
```bash
claude --version
claude -p "Hello, world"
```

### Step 2: Create your Telegram Bot

1. Open Telegram and message [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the prompts
3. Save the **bot token** (looks like `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)
4. Message your new bot once (so a chat exists)
5. Get your **chat ID** by messaging [@userinfobot](https://t.me/userinfobot)

### Step 3: Clone and Configure

```bash
git clone https://github.com/YOUR_USERNAME/claude-bot.git ~/claude-bot
cd ~/claude-bot
cp .env.example .env
```

Edit `.env` with your values:
```bash
TELEGRAM_BOT_TOKEN=your-bot-token-from-botfather
TELEGRAM_CHAT_ID=your-chat-id
```

Optional settings:
```bash
# Path to Claude CLI (auto-detected on most systems)
# CLAUDE_PATH=/opt/homebrew/bin/claude

# Default working directory for Claude sessions
# CLAUDE_WORKSPACE=/Users/yourname
```

### Step 4: Install as a Service

```bash
./claude-bot.sh install
```

This will:
- Install the bot as a launchd service
- Auto-start on login
- Auto-restart on crash
- Log to `~/.claude-bot/`

Check it's running:
```bash
./claude-bot.sh status
```

### Step 5: Message Your Bot

Open Telegram, find your bot, and send any message. Claude will respond.

---

## Commands

### Sessions
| Command | Description |
|---------|-------------|
| `/new [name]` | New session (auto-consolidates current one to Journal) |
| `/switch <name>` | Switch session (auto-consolidates first) |
| `/sessions` | List all sessions |
| `/delete <name>` | Delete a session |
| `/clear` | Reset session (drops session ID) |
| `/compact` | Compact session context |

### Model
| Command | Description |
|---------|-------------|
| `/sonnet` `/opus` `/haiku` | Quick model switch |
| `/model` | Model picker (inline keyboard) |
| `/effort <low\|medium\|high>` | Reasoning effort level |

### Control
| Command | Description |
|---------|-------------|
| `/stop` | Cancel running task |
| `/status` | Session and process info |
| `/timeout <sec>` | Activity timeout (default: 600s) |
| `/workspace <path>` | Change working directory |

### Journal & Routines
| Command | Description |
|---------|-------------|
| `/important` | Register key points from this session in today's Journal |
| `/routine` | Create a new scheduled routine (interactive) |
| `/routine list` | List today's routines |
| `/routine status` | Execution status of today's routines |

**Text** -- any non-command message goes to Claude as a prompt.
**Photos** -- images are downloaded and passed to Claude for analysis.

### Status Reactions

When you send a message, the bot sets emoji reactions on it to show processing status:

| Reaction | Meaning |
|----------|---------|
| 👀 | Message received |
| 🤔 | Claude is thinking |
| 👨‍💻 | Claude is using tools (running code, reading files) |
| 📝 | Claude is writing text |
| *(removed)* | Response complete |

---

## Knowledge Vault

The `vault/` directory is an [Obsidian](https://obsidian.md)-compatible knowledge vault. Claude reads it for context and writes to it to preserve knowledge across sessions.

### Structure

```
vault/
|-- Journal/        Daily conversation logs (YYYY-MM-DD.md), append-only
|-- Notes/          Durable knowledge, wikilinked for graph navigation
|-- Skills/         Reusable task definitions for recurring workflows
|-- Routines/       Scheduled prompts (cron-like execution)
|-- Images/         User-requested image storage, organized by theme
|-- Tooling.md      Tool preferences (which tool for each task type)
|-- .env            Project credentials (gitignored)
'-- README.md       Vault index and rules
```

### How It Works

- Every `.md` file has YAML frontmatter with `title`, `description`, `type`, `created`, `tags`
- Claude scans frontmatter first (the `description` field) before reading full files
- Journal is append-only -- sessions auto-consolidate on `/new`, `/switch`, or `/important`
- Notes use `[[wikilinks]]` to form a navigable knowledge graph
- Open the vault in Obsidian to explore connections via Graph View

### Personalizing Your Vault

After cloning, customize these files for your workflow:

1. **`vault/Tooling.md`** -- Edit with your preferred tools (MCP servers, CLI tools, etc.)
2. **`vault/.env`** -- Add API keys and tokens your routines/skills need
3. **`vault/Skills/`** -- Create skills for your recurring tasks (a `create-routine` skill is included)

The vault content (Journal, Notes, Skills, Routines, Images) is gitignored -- your personal knowledge stays local.

---

## Routines (Scheduled Tasks)

Create `.md` files in `vault/Routines/` to run prompts on a schedule:

```yaml
---
title: Morning Report
description: Generates a daily summary every morning.
type: routine
created: 2026-04-07
updated: 2026-04-07
tags: [routine, daily]
schedule:
  times: ["09:00"]
  days: [mon, tue, wed, thu, fri]
  until: "2026-12-31"
model: sonnet
enabled: true
---

Generate a morning summary of...
```

- The scheduler checks every 60 seconds
- Routines run in the bot's session queue (won't block user messages)
- Every execution is logged to the Journal
- Use `/routine` in Telegram to create routines interactively
- The menu bar shows today's routines with status icons

---

## Service Management

```bash
./claude-bot.sh start       # Start the bot
./claude-bot.sh stop        # Stop the bot
./claude-bot.sh restart     # Restart the bot
./claude-bot.sh status      # Process info, memory, active session
./claude-bot.sh logs        # Tail application logs
./claude-bot.sh uninstall   # Remove launchd service
```

### Menu Bar Indicator (Optional)

Shows a green/red dot in the macOS menu bar with bot status, session info, and today's routines.

```bash
pip3 install rumps
./claude-bot.sh menubar install
```

---

## CLAUDE.md -- Teaching Claude About Your Vault

The `CLAUDE.md` file contains instructions that Claude Code reads automatically when working in this project. It tells Claude:

- How to navigate the vault (scan frontmatter before reading full files)
- The rules for writing to the vault (frontmatter required, append-only journal, wikilinks)
- How to create and execute skills and routines
- Where to find credentials and tool preferences

When Claude runs via the bot, the system prompt also references the vault paths. You don't need to modify `CLAUDE.md` unless you want to add project-specific instructions.

### Context Isolation

Claude Code loads ALL `CLAUDE.md` files from the working directory up to the root. If you have CLAUDE.md files from other projects (e.g., in `~/` or `~/.claude/`), they will be loaded alongside this project's instructions, which can cause confusion.

To isolate the bot, create `.claude/settings.local.json` (gitignored):

```json
{
  "claudeMdExcludes": [
    "/Users/YOUR_USERNAME/CLAUDE.md",
    "/Users/YOUR_USERNAME/.claude/CLAUDE.md"
  ]
}
```

This blocks parent CLAUDE.md files when Claude CLI runs with `cwd=~/claude-bot/`. Other projects are not affected.

---

## Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | -- | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | -- | Your Telegram chat ID |
| `CLAUDE_PATH` | No | `/opt/homebrew/bin/claude` | Path to Claude CLI |
| `CLAUDE_WORKSPACE` | No | `$HOME` | Default working directory |

---

## Project Structure

```
claude-bot/
|-- claude-fallback-bot.py            Core bot (stdlib only)
|-- claude-bot-menubar.py             Menu bar indicator (requires rumps)
|-- claude-bot.sh                     Service manager
|-- com.vr.claude-bot.plist           launchd template (bot)
|-- com.vr.claude-bot-menubar.plist   launchd template (menu bar)
|-- .env.example                      Environment variable template
|-- CLAUDE.md                         Instructions for Claude Code
|-- README.md                         This file
'-- vault/                            Obsidian knowledge vault
```

Runtime data: `~/.claude-bot/` (sessions, logs, routine state).

---

## Security

- The bot **only responds to your `TELEGRAM_CHAT_ID`** -- all other messages are silently ignored
- No secrets in the repository -- `.env` and `vault/.env` are gitignored
- Claude runs with `--dangerously-skip-permissions` (no interactive permission prompts)
- Everything runs locally -- Claude processing never leaves your machine

---

## License

MIT
