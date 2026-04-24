#!/usr/bin/env bash
# Restart the bot service safely. Can be called by the bot or Claude Code.
# Reads credentials from ../.env (relative to this script).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$BOT_DIR/.env"
WATCHDOG_FLAG="$HOME/.claude-bot/.watchdog-notified"
PLIST_DST="$HOME/Library/LaunchAgents/com.claudebot.bot.plist"

[[ -f "$ENV_FILE" ]] || { echo "ERROR: $ENV_FILE not found" >&2; exit 1; }

TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
TELEGRAM_CHAT_ID=$(grep -E '^TELEGRAM_CHAT_ID='    "$ENV_FILE" | cut -d= -f2- | cut -d, -f1)

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=$1" \
        -d "parse_mode=Markdown" > /dev/null 2>&1 || true
}

# Give the bot time to send its "Reiniciando..." message before dying
sleep 3

# Touch watchdog flag — suppresses "bot caiu" alarm during the restart window
touch "$WATCHDOG_FLAG" 2>/dev/null || true

launchctl unload "$PLIST_DST" 2>/dev/null || true
sleep 2
launchctl load "$PLIST_DST"

# Poll until the process is up (max ~30s)
for _ in $(seq 1 10); do
    sleep 3
    if pgrep -f "claude-fallback-bot.py" > /dev/null 2>&1; then
        rm -f "$WATCHDOG_FLAG" 2>/dev/null || true
        send_telegram "✅ *Bot reiniciado com sucesso.*"
        exit 0
    fi
done

# Bot didn't come up — clear flag so watchdog can resume normal monitoring
rm -f "$WATCHDOG_FLAG" 2>/dev/null || true
send_telegram "❌ *Falha ao reiniciar o bot.* Verifique: \`~/.claude-bot/bot.log\`"
exit 1
