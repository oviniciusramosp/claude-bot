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
HEARTBEAT_FILE="$HOME/.claude-bot/.scheduler-heartbeat"
PLIST_DST="$HOME/Library/LaunchAgents/com.claudebot.bot.plist"
SERVICE_ID="gui/$(id -u)/com.claudebot.bot"
BOT_PROCESS="claude-fallback-bot.py"
STALE_SECS=180  # mirror of SCHEDULER_HEARTBEAT_STALE_SECS in claude-fallback-bot.py

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

# Restart the bot service (kickstart with bootstrap fallback) and notify once
# per downtime window. Used by BOTH the down-bot path and the stuck-scheduler
# path so they share the same recovery mechanism. $1 = Telegram alert text.
restart_bot() {
    if [[ ! -f "$FLAG_FILE" ]]; then
        touch "$FLAG_FILE"
        # Primary: kickstart (service registered but stopped — works on Darwin 24+)
        # Fallback: bootstrap (service not registered, e.g. after a failed restart)
        if ! launchctl kickstart "$SERVICE_ID" 2>/dev/null; then
            launchctl bootstrap "gui/$(id -u)" "$PLIST_DST" 2>/dev/null || true
        fi
        send_telegram "$1"
    fi
}

# mtime age of a file in whole seconds, or empty string if it can't be read.
# Portable across macOS (stat -f %m) and GNU (stat -c %Y) coreutils.
file_age_secs() {
    local f="$1" mtime now
    mtime=$(stat -f %m "$f" 2>/dev/null || stat -c %Y "$f" 2>/dev/null) || return 1
    [[ -z "$mtime" ]] && return 1
    now=$(date +%s)
    echo $(( now - mtime ))
}

if pgrep -f "$BOT_PROCESS" > /dev/null 2>&1; then
    # PRIMARY gate: process exists. Clear notification flag on recovery.
    if [[ -f "$FLAG_FILE" ]]; then
        rm -f "$FLAG_FILE"
        send_telegram "✅ *Claude Bot* voltou a funcionar."
    fi
    # SECONDARY gate: process is alive but the scheduler thread may have died
    # silently. If a heartbeat exists and is stale, treat the bot as unhealthy
    # and restart it through the same path. If the heartbeat file does NOT
    # exist (older bot build mid-upgrade, or before the first tick), behave
    # EXACTLY as before — pgrep-only — so we never false-restart.
    if [[ -f "$HEARTBEAT_FILE" ]]; then
        AGE=$(file_age_secs "$HEARTBEAT_FILE")
        if [[ -n "$AGE" && "$AGE" -gt "$STALE_SECS" ]]; then
            restart_bot "⚠️ *Scheduler travado!* Sem heartbeat há ${AGE}s (processo vivo). Reiniciando o Claude Bot..."
        fi
    fi
else
    # Bot is down — restart once and notify once per downtime window
    restart_bot "🚨 *Claude Bot caiu!* Reiniciando automaticamente..."
fi
