#!/bin/bash
# bot-watchdog.sh — Monitors claude-fallback-bot.py and sends Telegram alert if it's down.
# Runs via launchd every 30 seconds. Uses a flag file to avoid repeated notifications.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
FLAG_FILE="$HOME/.claude-bot/.watchdog-notified"
BOT_PROCESS="claude-fallback-bot.py"

# Load .env
if [[ -f "$ENV_FILE" ]]; then
    TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
    TELEGRAM_CHAT_ID=$(grep -E '^TELEGRAM_CHAT_ID=' "$ENV_FILE" | cut -d= -f2- | cut -d, -f1)
else
    exit 1
fi

send_telegram() {
    local text="$1"
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=${text}" \
        -d "parse_mode=Markdown" > /dev/null 2>&1
}

if pgrep -f "$BOT_PROCESS" > /dev/null 2>&1; then
    # Bot is running — clear notification flag if it was set (recovered)
    if [[ -f "$FLAG_FILE" ]]; then
        rm -f "$FLAG_FILE"
        send_telegram "✅ *Claude Bot* voltou a funcionar."
    fi
else
    # Bot is down — restart via launchd and notify (once per downtime)
    if [[ ! -f "$FLAG_FILE" ]]; then
        touch "$FLAG_FILE"
        launchctl start com.vr.claude-bot 2>/dev/null
        send_telegram "🚨 *Claude Bot caiu!* Reiniciando automaticamente..."
    fi
fi
