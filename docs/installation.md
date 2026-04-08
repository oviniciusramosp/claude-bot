# Installation Guide

## Prerequisites

Before installing Claude Bot, make sure you have:

- **macOS** -- the bot uses launchd for service management and native speech recognition for voice transcription. It will not run on Linux or Windows.
- **Python 3.8+** -- pre-installed on macOS. The bot uses only the standard library (no pip dependencies).
- **Claude Code CLI** -- installed and authenticated. Follow the [official getting started guide](https://docs.anthropic.com/en/docs/claude-code/getting-started). Verify with:
  ```bash
  claude --version
  claude -p "Hello, world"
  ```
- **Telegram bot token** -- create a bot via [@BotFather](https://t.me/BotFather) on Telegram. You will need the bot token it provides.
- **Your Telegram chat ID** -- message [@userinfobot](https://t.me/userinfobot) on Telegram to get your numeric chat ID.

### Optional Dependencies

- **ffmpeg** -- required for voice message transcription (converts Telegram's OGG/Opus audio to WAV). Install with:
  ```bash
  brew install ffmpeg
  ```
- **[hear](https://github.com/sveinbjornt/hear)** -- a lightweight CLI wrapping Apple's SFSpeechRecognizer. Automatically downloaded during install to `~/.claude-bot/bin/hear`.

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/claude-bot.git ~/claude-bot
cd ~/claude-bot
cp .env.example .env
# Edit .env with your Telegram bot token and chat ID
./claude-bot.sh install
./claude-bot.sh status
```

Then open Telegram and send a message to your bot.

## Step-by-Step Installation

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/claude-bot.git ~/claude-bot
cd ~/claude-bot
```

### 2. Create the Configuration File

Copy the example and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your values:

```bash
# Required
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_CHAT_ID=987654321

# Optional -- uncomment and edit if needed
# CLAUDE_PATH=/opt/homebrew/bin/claude
# CLAUDE_WORKSPACE=/Users/yourname/claude-bot/vault
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | -- | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | Yes | -- | Your numeric Telegram chat ID. Comma-separated for multiple (e.g., private chat + group). |
| `CLAUDE_PATH` | No | `/opt/homebrew/bin/claude` | Path to the Claude Code CLI binary |
| `CLAUDE_WORKSPACE` | No | `<project>/vault/` | Default working directory for Claude sessions |

### 3. Install as a Service

```bash
./claude-bot.sh install
```

This command will:
1. Check for voice transcription dependencies (ffmpeg, hear) and install `hear` if missing.
2. Copy the launchd plist to `~/Library/LaunchAgents/` with path substitution.
3. Load the service via launchctl.

The bot will now:
- Start automatically on login.
- Restart automatically if it crashes.
- Log to `~/.claude-bot/`.

### 4. Verify the Installation

```bash
./claude-bot.sh status
```

You should see output showing the service as `LOADED` and the process as `RUNNING`, along with memory usage and uptime.

### 5. Test It

Open Telegram, find your bot, and send any message. Claude should respond within a few seconds. You will see emoji reactions on your message as Claude processes it (eyes for received, thinking face for thinking, lightning for tool use, pencil for writing).

## Optional: Audio Support

Voice message transcription requires ffmpeg and hear. Both are handled by the installer, but you can also manage them separately:

```bash
# Install/check dependencies only (without reinstalling the service)
./claude-bot.sh install-deps
```

For voice transcription to work, you also need macOS Dictation enabled:

1. Open **System Settings** > **Keyboard** > **Dictation**.
2. Toggle Dictation **On**.

After setup, send a voice message on Telegram and the bot will transcribe it and send the text to Claude.

You can change the transcription language with the `/audio` command in Telegram, or set a default in `.env`:

```bash
HEAR_LOCALE=en-US
```

## Optional: macOS Manager App

The ClaudeBotManager is a native SwiftUI menu bar app that shows bot status, active sessions, routine schedules, and allows editing settings.

```bash
cd ~/claude-bot/ClaudeBotManager
swift build
```

The built binary will be in `.build/debug/ClaudeBotManager`. You can also install it as a launchd service:

```bash
cd ~/claude-bot
./claude-bot.sh menubar install
```

### Menu Bar Indicator (Lightweight Alternative)

A simpler Python-based menu bar indicator is also available. It requires the `rumps` library:

```bash
pip3 install rumps
./claude-bot.sh menubar install
```

## Service Management

Once installed, use `claude-bot.sh` to manage the service:

| Command | Description |
|---------|-------------|
| `./claude-bot.sh start` | Start the bot (installs service if needed) |
| `./claude-bot.sh stop` | Stop the bot |
| `./claude-bot.sh restart` | Restart the bot |
| `./claude-bot.sh status` | Show process info, memory, uptime, and active session |
| `./claude-bot.sh logs` | Tail application and stdout logs |
| `./claude-bot.sh errors` | Tail stderr logs |
| `./claude-bot.sh pid` | Print the process ID |

## Uninstalling

To remove the launchd service:

```bash
./claude-bot.sh uninstall
```

This unloads the service and removes the plist from `~/Library/LaunchAgents/`. It does not delete the bot files, configuration, or runtime data.

To also remove the menu bar indicator:

```bash
./claude-bot.sh menubar uninstall
```

To fully clean up runtime data:

```bash
rm -rf ~/.claude-bot/
```
