# Configuration Reference

This document covers all configuration options for the Claude Bot Telegram service, including environment files, bot constants, launchd settings, and Claude Code integration.

## Environment Files

The project uses **two separate `.env` files** with distinct purposes. They are kept separate for security: `vault/` may be synced (iCloud, Git), so mixing Telegram tokens with third-party API keys would be an unnecessary risk.

### `~/claude-bot/.env` -- Bot Operations

Read by `claude-fallback-bot.py` at startup and by the ClaudeBotManager macOS app. Contains credentials and paths required for the bot to function.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | -- | Bot token from Telegram's @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | -- | Comma-separated list of authorized Telegram chat IDs |
| `CLAUDE_PATH` | No | `/opt/homebrew/bin/claude` | Absolute path to the Claude CLI binary |
| `CLAUDE_WORKSPACE` | No | `<project>/vault/` | Default working directory for Claude sessions |
| `FFMPEG_PATH` | No | `/opt/homebrew/bin/ffmpeg` | Path to ffmpeg binary (for voice transcription) |
| `HEAR_PATH` | No | (empty) | Path to the `hear` speech-to-text binary |
| `HEAR_LOCALE` | No | `pt-BR` | Locale for voice transcription |

The bot first checks environment variables, then falls back to reading this file. Environment variables take precedence over file values.

### `vault/.env` -- API Keys for Vault Tasks

Read by Claude Code when executing tasks within the vault context (routines, interactive sessions). Contains keys for external services.

Typical variables:
- `NOTION_API_KEY` -- Notion integration token
- `FIGMA_TOKEN` -- Figma MCP access token
- Other third-party API keys as needed

This file does **not** contain Telegram credentials or bot paths.

## Bot Constants

These constants are defined at the top of `claude-fallback-bot.py` and control core bot behavior.

### Timeouts and Intervals

| Constant | Value | Description |
|----------|-------|-------------|
| `DEFAULT_TIMEOUT` | `600` | Default timeout for Claude CLI execution (seconds) |
| `STREAM_EDIT_INTERVAL` | `3.0` | Minimum seconds between Telegram message edits (rate limiting) |
| `TYPING_INTERVAL` | `4.0` | Seconds between sending typing indicators to Telegram |
| `PIPELINE_WORKSPACE_MAX_AGE` | `86400` | Max age (24h) for pipeline temp workspaces before cleanup |

### Message Limits

| Constant | Value | Description |
|----------|-------|-------------|
| `MAX_MESSAGE_LENGTH` | `4000` | Maximum characters per Telegram message (Telegram's limit is 4096; 4000 provides a safety margin) |

### Network

| Constant | Value | Description |
|----------|-------|-------------|
| `CONTROL_PORT` | `27182` | Port for the local HTTP control server (localhost only) |

### Paths

| Constant | Value | Description |
|----------|-------|-------------|
| `DATA_DIR` | `~/.claude-bot/` | Runtime data directory |
| `SESSIONS_FILE` | `~/.claude-bot/sessions.json` | Session persistence file |
| `CONTEXTS_FILE` | `~/.claude-bot/contexts.json` | Context-to-session mappings |
| `LOG_FILE` | `~/.claude-bot/bot.log` | Application log (rotating, 5MB x 3 backups) |
| `VAULT_DIR` | `<project>/vault/` | Vault knowledge base directory |
| `ROUTINES_DIR` | `<project>/vault/Routines/` | Routine definitions directory |
| `AGENTS_DIR` | `<project>/vault/Agents/` | Agent definitions directory |
| `ROUTINES_STATE_DIR` | `~/.claude-bot/routines-state/` | Daily routine execution state |
| `TEMP_IMAGES_DIR` | `/tmp/claude-bot-images/` | Temporary storage for received images |
| `TEMP_AUDIO_DIR` | `/tmp/claude-bot-audio/` | Temporary storage for voice messages |
| `CONTROL_TOKEN_FILE` | `~/.claude-bot/.control-token` | Bearer token for control server auth |

### Default Model

The default model for new sessions is `"sonnet"`, set in the `Session` dataclass. Users can switch models per-session with `/sonnet`, `/opus`, `/haiku`, or the `/model` keyboard.

## launchd Configuration

The bot runs as a macOS launchd user agent. The plist template (`com.vr.claude-bot.plist`) uses placeholder tokens that the install script substitutes via `sed`.

### Placeholders

| Placeholder | Replaced With |
|-------------|---------------|
| `__HOME__` | User's home directory |
| `__SCRIPT_DIR__` | Directory containing the bot script |

### Key launchd Options

```xml
<key>RunAtLoad</key>
<true/>
```
The bot starts automatically when the user logs in.

```xml
<key>KeepAlive</key>
<dict>
    <key>SuccessfulExit</key>
    <false/>
</dict>
```
launchd restarts the bot only if it exits with a non-zero status. A clean shutdown (exit 0) does not trigger a restart.

```xml
<key>ThrottleInterval</key>
<integer>30</integer>
```
Minimum 30 seconds between restart attempts, preventing rapid restart loops if the bot keeps crashing.

```xml
<key>SoftResourceLimits</key>
<dict>
    <key>NumberOfFiles</key>
    <integer>1024</integer>
</dict>
```
Raises the open file descriptor limit to 1024 (macOS default is 256), needed because the bot spawns subprocesses and maintains network connections.

### Log Files

launchd captures process stdout/stderr separately from the application log:

- `~/.claude-bot/launchd-stdout.log` -- Process standard output
- `~/.claude-bot/launchd-stderr.log` -- Process standard error
- `~/.claude-bot/bot.log` -- Application-level log (rotating, 5MB x 3 backups)

### Service Management

Use `claude-bot.sh` to manage the service:

```bash
./claude-bot.sh install    # Install plist and start
./claude-bot.sh uninstall  # Stop and remove plist
./claude-bot.sh start      # Start the bot
./claude-bot.sh stop       # Stop the bot
./claude-bot.sh restart    # Restart
./claude-bot.sh status     # Show running status
./claude-bot.sh logs       # Tail application log
```

## Claude Code Settings

### `.claude/settings.local.json`

This file (gitignored) controls Claude Code permissions and CLAUDE.md loading behavior when the bot invokes the CLI.

#### Permissions

The `permissions.allow` array whitelists specific tool invocations that Claude Code can execute without prompting:

```json
{
  "permissions": {
    "allow": [
      "Bash(python3 -m py_compile claude-fallback-bot.py)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "WebSearch",
      "WebFetch(domain:github.com)",
      "Bash(swift build:*)"
    ]
  }
}
```

#### CLAUDE.md Exclusions

The `claudeMdExcludes` array prevents Claude Code from loading CLAUDE.md files from parent directories that belong to other projects:

```json
{
  "claudeMdExcludes": [
    "/Users/USERNAME/CLAUDE.md",
    "/Users/USERNAME/.claude/CLAUDE.md"
  ]
}
```

This ensures the bot's Claude CLI sessions only load instructions from this project's hierarchy (`CLAUDE.md` at project root and `vault/CLAUDE.md`), not from the user's home directory or global Claude config.

### CLAUDE.md Hierarchy

When Claude CLI runs with a given `cwd`, it loads all `CLAUDE.md` files walking up the directory tree:

- **Normal session** (`cwd=vault/`): loads `vault/CLAUDE.md` (primary) + project root `CLAUDE.md` (parent)
- **Agent session** (`cwd=vault/Agents/{id}/`): loads agent's `CLAUDE.md` + `vault/CLAUDE.md` + root `CLAUDE.md`

The root `CLAUDE.md` contains development instructions. The `vault/CLAUDE.md` contains operational instructions for the bot's knowledge base.

## Manager App Settings

The ClaudeBotManager (SwiftUI macOS menu bar app in `ClaudeBotManager/`) provides a GUI for managing bot configuration:

- **Settings panel**: reads and writes `~/claude-bot/.env` for bot operation variables
- **Dashboard**: shows bot status, active sessions, and recent activity
- **Agents**: browse, create, and edit agent definitions
- **Routines**: manage routine schedules and pipelines
- **Logs**: view `~/.claude-bot/bot.log` in real time

The Manager app reads the same `.env` file as the bot. Changes made through the app's Settings UI take effect on next bot restart.
