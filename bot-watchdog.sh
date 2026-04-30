#!/bin/bash
# bot-watchdog.sh — Monitors claude-fallback-bot.py and restarts it if down.
# Runs via launchd every 60s. Sends a Telegram alert once per downtime window.
#
# Disable: touch ~/.claude-bot/.watchdog-disabled  (or /watchdog off in Telegram)
# Enable:  rm ~/.claude-bot/.watchdog-disabled      (or /watchdog on  in Telegram)

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
FLAG_FILE="$HOME/.claude-bot/.watchdog-notified"
DISABLE_FILE="$HOME/.claude-bot/.watchdog-disabled"
PLIST_DST="$HOME/Library/LaunchAgents/com.claudebot.bot.plist"
SERVICE_ID="gui/$(id -u)/com.claudebot.bot"
BOT_PROCESS="claude-fallback-bot.py"

# Disabled — exit silently (e.g. during planned maintenance or manual restart)
[[ -f "$DISABLE_FILE" ]] && exit 0

if [[ ! -f "$ENV_FILE" ]]; then
    exit 1
fi

TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
TELEGRAM_CHAT_ID=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | cut -d= -f2- | cut -d, -f1)

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=$1" \
        -d "parse_mode=Markdown" > /dev/null 2>&1 || true
}

if pgrep -f "$BOT_PROCESS" > /dev/null 2>&1; then
    # Bot is running — clear notification flag on recovery
    if [[ -f "$FLAG_FILE" ]]; then
        rm -f "$FLAG_FILE"
        send_telegram "✅ *Claude Bot* voltou a funcionar."
    fi
else
    # Bot is down — restart once and notify once per downtime window
    if [[ ! -f "$FLAG_FILE" ]]; then
        touch "$FLAG_FILE"
        # Primary: kickstart (service registered but stopped — works on Darwin 24+)
        # Fallback: bootstrap (service not registered, e.g. after a failed restart)
        if ! launchctl kickstart "$SERVICE_ID" 2>/dev/null; then
            launchctl bootstrap "gui/$(id -u)" "$PLIST_DST" 2>/dev/null || true
        fi
        send_telegram "🚨 *Claude Bot caiu!* Reiniciando automaticamente..."
    fi
fi
