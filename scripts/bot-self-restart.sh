#!/usr/bin/env bash
# bot-self-restart.sh — Restart the bot service reliably on modern macOS.
#
# Primary path: launchctl kickstart -k (atomic kill+restart, keeps service
# registered in launchd — no unload/load race condition, works on Darwin 24+).
# Fallback: bootout + bootstrap for edge cases where the service is not loaded.
#
# Called by the bot's /restart command and can be run directly by Claude Code.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$BOT_DIR/.env"
WATCHDOG_FLAG="$HOME/.claude-bot/.watchdog-notified"
PLIST_DST="$HOME/Library/LaunchAgents/com.claudebot.bot.plist"
SERVICE_ID="gui/$(id -u)/com.claudebot.bot"

[[ -f "$ENV_FILE" ]] || { echo "ERROR: $ENV_FILE not found" >&2; exit 1; }

TELEGRAM_BOT_TOKEN=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
TELEGRAM_CHAT_ID=$(grep -E '^TELEGRAM_CHAT_ID='    "$ENV_FILE" | cut -d= -f2- | cut -d, -f1)

send_telegram() {
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        -d "chat_id=${TELEGRAM_CHAT_ID}" \
        -d "text=$1" \
        -d "parse_mode=Markdown" > /dev/null 2>&1 || true
}

# Give the bot time to send its "Reiniciando..." message before being killed
sleep 3

# Suppress watchdog alarms during the restart window
touch "$WATCHDOG_FLAG" 2>/dev/null || true

# Record old PID so we can detect when the new process is up
OLD_PID=$(pgrep -f "claude-fallback-bot.py" || echo "0")

# Primary: kickstart -k — atomic kill+restart, works on Darwin 24+.
# launchd sends SIGTERM, waits up to ExitTimeout (20s), then SIGKILL, then starts fresh.
if ! launchctl kickstart -k "$SERVICE_ID" 2>/dev/null; then
    # Service not registered (was manually bootout'd) — bootstrap it first
    launchctl bootout "gui/$(id -u)" "$PLIST_DST" 2>/dev/null || true
    if ! launchctl bootstrap "gui/$(id -u)" "$PLIST_DST" 2>/dev/null; then
        # Last resort: legacy commands (Darwin < 24 compatibility)
        launchctl unload "$PLIST_DST" 2>/dev/null || true
        sleep 1
        launchctl load "$PLIST_DST" 2>/dev/null || true
    fi
fi

# Poll until a NEW process is confirmed running (max ~40s)
for _ in $(seq 1 20); do
    sleep 2
    NEW_PID=$(pgrep -f "claude-fallback-bot.py" || echo "")
    if [[ -n "$NEW_PID" && "$NEW_PID" != "$OLD_PID" ]]; then
        rm -f "$WATCHDOG_FLAG" 2>/dev/null || true
        send_telegram "✅ *Bot reiniciado com sucesso.*"
        exit 0
    fi
done

# Bot didn't come up — clear flag so watchdog resumes normal monitoring
rm -f "$WATCHDOG_FLAG" 2>/dev/null || true
send_telegram "❌ *Falha ao reiniciar o bot.* Verifique: \`~/.claude-bot/bot.log\`"
exit 1
