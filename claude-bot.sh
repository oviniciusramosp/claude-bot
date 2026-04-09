#!/bin/bash
# ──────────────────────────────────────────────────────────────
# claude-bot.sh — Manage the Claude Code Telegram Bot service
# ──────────────────────────────────────────────────────────────
#
# Usage:
#   ./claude-bot.sh install    Install as launchd service (auto-start on login)
#   ./claude-bot.sh uninstall  Remove launchd service
#   ./claude-bot.sh start      Start the bot
#   ./claude-bot.sh stop       Stop the bot
#   ./claude-bot.sh restart    Restart the bot
#   ./claude-bot.sh status     Check if the bot is running
#   ./claude-bot.sh logs       Tail bot logs
#   ./claude-bot.sh errors     Tail error logs
#   ./claude-bot.sh pid        Show process ID

set -euo pipefail

LABEL="com.vr.claude-bot"
LABEL_MENUBAR="com.vr.claude-bot-menubar"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="${SCRIPT_DIR}/com.vr.claude-bot.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
PLIST_MENUBAR_SRC="${SCRIPT_DIR}/com.vr.claude-bot-menubar.plist"
PLIST_MENUBAR_DST="${HOME}/Library/LaunchAgents/${LABEL_MENUBAR}.plist"
BOT_SCRIPT="${SCRIPT_DIR}/claude-fallback-bot.py"
LOG_DIR="${HOME}/.claude-bot"
LOG_FILE="${LOG_DIR}/bot.log"
STDOUT_LOG="${LOG_DIR}/launchd-stdout.log"
STDERR_LOG="${LOG_DIR}/launchd-stderr.log"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

HEAR_BIN="${LOG_DIR}/bin/hear"
HEAR_REPO="sveinbjornt/hear"

# Ensure directories exist
mkdir -p "$LOG_DIR"
mkdir -p "${LOG_DIR}/bin"

is_loaded() {
    launchctl list 2>/dev/null | grep -q "$LABEL"
}

get_pid() {
    launchctl list "$LABEL" 2>/dev/null | grep '"PID"' | awk '{print $NF}' | tr -d ';' || true
    # Fallback
    pgrep -f "claude-fallback-bot.py" 2>/dev/null | head -1 || true
}

install_hear() {
    if [[ -f "$HEAR_BIN" ]]; then
        echo -e "  hear: ${GREEN}already installed${NC} ($HEAR_BIN)"
        return 0
    fi

    echo -e "  hear: ${YELLOW}downloading...${NC}"

    # Get latest release download URL from GitHub API
    local api_url="https://api.github.com/repos/${HEAR_REPO}/releases/latest"
    local release_json
    release_json=$(curl -sL -H "Accept: application/vnd.github.v3+json" "$api_url" 2>/dev/null) || {
        echo -e "  hear: ${RED}failed to fetch release info${NC}"
        return 1
    }

    # Find the binary asset URL (look for 'hear' binary or any hear*.zip)
    local download_url
    download_url=$(echo "$release_json" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for a in data.get('assets', []):
    name = a.get('name', '')
    if name == 'hear' or name.startswith('hear') and name.endswith('.zip'):
        print(a['browser_download_url'])
        break
" 2>/dev/null)

    if [[ -z "$download_url" ]]; then
        echo -e "  hear: ${RED}no binary found in latest release${NC}"
        echo -e "  Download manually from: https://github.com/${HEAR_REPO}/releases"
        return 1
    fi

    local asset_name="${download_url##*/}"

    if [[ "$asset_name" == "hear" ]]; then
        curl -sL -o "$HEAR_BIN" "$download_url" || { echo -e "  hear: ${RED}download failed${NC}"; return 1; }
    elif [[ "$asset_name" == *.zip ]]; then
        local tmp_dir
        tmp_dir=$(mktemp -d)
        curl -sL -o "${tmp_dir}/${asset_name}" "$download_url" || { echo -e "  hear: ${RED}download failed${NC}"; rm -rf "$tmp_dir"; return 1; }
        unzip -qo "${tmp_dir}/${asset_name}" -d "$tmp_dir" 2>/dev/null
        local found
        found=$(find "$tmp_dir" -name "hear" -type f ! -name "*.zip" | head -1)
        if [[ -n "$found" ]]; then
            cp "$found" "$HEAR_BIN"
        else
            echo -e "  hear: ${RED}binary not found inside zip${NC}"
            rm -rf "$tmp_dir"
            return 1
        fi
        rm -rf "$tmp_dir"
    fi

    chmod +x "$HEAR_BIN"
    echo -e "  hear: ${GREEN}installed${NC} ($HEAR_BIN)"
    return 0
}

install_deps() {
    echo -e "${CYAN}Checking dependencies...${NC}"

    # ffmpeg
    if [[ -x "/opt/homebrew/bin/ffmpeg" ]] || command -v ffmpeg &>/dev/null; then
        local ffmpeg_path
        ffmpeg_path=$([[ -x "/opt/homebrew/bin/ffmpeg" ]] && echo "/opt/homebrew/bin/ffmpeg" || command -v ffmpeg)
        echo -e "  ffmpeg: ${GREEN}found${NC} ($ffmpeg_path)"
    else
        if command -v brew &>/dev/null; then
            echo -e "  ffmpeg: ${YELLOW}not found — installing via brew...${NC}"
            brew install ffmpeg --quiet
            if [[ -x "/opt/homebrew/bin/ffmpeg" ]] || command -v ffmpeg &>/dev/null; then
                echo -e "  ffmpeg: ${GREEN}installed${NC}"
            else
                echo -e "  ffmpeg: ${RED}brew install failed — install manually: brew install ffmpeg${NC}"
            fi
        else
            echo -e "  ffmpeg: ${RED}not found and Homebrew not available — install manually: brew install ffmpeg${NC}"
        fi
    fi

    # hear
    install_hear

    # graphify (knowledge graph builder for vault)
    local graphify_bin
    graphify_bin=$(python3 -c "import site; print(site.getusersitepackages().replace('/lib/python', '/bin/graphify').rsplit('/lib/', 1)[0])" 2>/dev/null || echo "")
    if python3 -c "import graphifyy" &>/dev/null; then
        local graphify_path
        graphify_path=$(command -v graphify 2>/dev/null || echo "${HOME}/Library/Python/$(python3 -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')/bin/graphify")
        echo -e "  graphify: ${GREEN}found${NC} ($graphify_path)"
    else
        echo -e "  graphify: ${YELLOW}not found — installing...${NC}"
        pip3 install --user --break-system-packages graphifyy 2>/dev/null || pip3 install --user graphifyy 2>/dev/null || {
            echo -e "  graphify: ${YELLOW}pip install failed — trying from source...${NC}"
            local tmp_dir
            tmp_dir=$(mktemp -d)
            git clone --depth 1 https://github.com/safishamsi/graphify.git "$tmp_dir/graphify" 2>/dev/null
            pip3 install --user --break-system-packages -e "$tmp_dir/graphify" 2>/dev/null || pip3 install --user -e "$tmp_dir/graphify" 2>/dev/null || {
                echo -e "  graphify: ${RED}install failed — install manually: pip3 install --user graphifyy${NC}"
                rm -rf "$tmp_dir"
            }
        }
        if python3 -c "import graphifyy" &>/dev/null; then
            echo -e "  graphify: ${GREEN}installed${NC}"
        fi
    fi

    echo ""
}

case "${1:-help}" in
    install)
        echo -e "${CYAN}Installing Claude Bot service...${NC}"

        # Install dependencies
        install_deps

        # Validate files exist
        if [[ ! -f "$PLIST_SRC" ]]; then
            echo -e "${RED}Error: plist not found at ${PLIST_SRC}${NC}"
            exit 1
        fi
        if [[ ! -f "$BOT_SCRIPT" ]]; then
            echo -e "${RED}Error: bot script not found at ${BOT_SCRIPT}${NC}"
            exit 1
        fi

        # Unload if already loaded
        if is_loaded; then
            echo "Unloading existing service..."
            launchctl unload "$PLIST_DST" 2>/dev/null || true
        fi

        # Copy plist with path substitution
        sed -e "s|__HOME__|${HOME}|g" -e "s|__SCRIPT_DIR__|${SCRIPT_DIR}|g" "$PLIST_SRC" > "$PLIST_DST"
        echo "Plist installed to: $PLIST_DST"

        # Load
        launchctl load "$PLIST_DST"
        sleep 1

        if is_loaded; then
            echo -e "${GREEN}Service installed and running.${NC}"
            echo ""
            echo "The bot will:"
            echo "  - Start automatically on login"
            echo "  - Restart automatically if it crashes"
            echo "  - Log to ${LOG_DIR}/"
            echo ""
            echo "Use './claude-bot.sh status' to check."
        else
            echo -e "${RED}Service loaded but may not be running. Check logs:${NC}"
            echo "  tail -f ${STDERR_LOG}"
        fi
        ;;

    uninstall)
        echo -e "${CYAN}Uninstalling Claude Bot service...${NC}"
        if is_loaded; then
            launchctl unload "$PLIST_DST" 2>/dev/null || true
        fi
        rm -f "$PLIST_DST"
        echo -e "${GREEN}Service uninstalled.${NC}"
        ;;

    start)
        if is_loaded; then
            echo -e "${YELLOW}Service already loaded. Restarting...${NC}"
            launchctl unload "$PLIST_DST" 2>/dev/null || true
            sleep 1
        fi

        if [[ ! -f "$PLIST_DST" ]]; then
            echo -e "${YELLOW}Service not installed. Installing first...${NC}"
            sed -e "s|__HOME__|${HOME}|g" -e "s|__SCRIPT_DIR__|${SCRIPT_DIR}|g" "$PLIST_SRC" > "$PLIST_DST"
        fi

        launchctl load "$PLIST_DST"
        sleep 1

        if is_loaded; then
            echo -e "${GREEN}Bot started.${NC}"
        else
            echo -e "${RED}Failed to start. Check: tail -f ${STDERR_LOG}${NC}"
        fi
        ;;

    stop)
        if is_loaded; then
            launchctl unload "$PLIST_DST" 2>/dev/null || true
            echo -e "${GREEN}Bot stopped.${NC}"
        else
            echo -e "${YELLOW}Bot is not running.${NC}"
        fi
        ;;

    restart)
        echo -e "${CYAN}Restarting bot...${NC}"
        if is_loaded; then
            launchctl unload "$PLIST_DST" 2>/dev/null || true
            sleep 2
        fi
        if [[ ! -f "$PLIST_DST" ]]; then
            sed -e "s|__HOME__|${HOME}|g" -e "s|__SCRIPT_DIR__|${SCRIPT_DIR}|g" "$PLIST_SRC" > "$PLIST_DST"
        fi
        launchctl load "$PLIST_DST"
        sleep 1
        if is_loaded; then
            echo -e "${GREEN}Bot restarted.${NC}"
        else
            echo -e "${RED}Failed to restart. Check: tail -f ${STDERR_LOG}${NC}"
        fi
        ;;

    status)
        echo -e "${CYAN}Claude Bot Status${NC}"
        echo "────────────────────────────"

        if is_loaded; then
            echo -e "Service:  ${GREEN}LOADED${NC}"
        else
            echo -e "Service:  ${RED}NOT LOADED${NC}"
        fi

        PID=$(pgrep -f "claude-fallback-bot.py" 2>/dev/null | head -1 || true)
        if [[ -n "$PID" ]]; then
            echo -e "Process:  ${GREEN}RUNNING${NC} (PID: ${PID})"

            # Memory usage
            MEM=$(ps -o rss= -p "$PID" 2>/dev/null | awk '{printf "%.1f", $1/1024}' || echo "?")
            echo "Memory:   ${MEM} MB"

            # Uptime
            ELAPSED=$(ps -o etime= -p "$PID" 2>/dev/null | xargs || echo "?")
            echo "Uptime:   ${ELAPSED}"
        else
            echo -e "Process:  ${RED}NOT RUNNING${NC}"
        fi

        # Session info
        SESSION_FILE="${HOME}/.claude-bot/sessions.json"
        if [[ -f "$SESSION_FILE" ]]; then
            SESSIONS=$(python3 -c "
import json
with open('${SESSION_FILE}') as f:
    d = json.load(f)
print(f\"Sessions: {len(d.get('sessions', {}))}  |  Active: {d.get('active_session', '?')}\")
" 2>/dev/null || echo "Could not read session data")
            echo "$SESSIONS"
        fi

        echo "────────────────────────────"
        echo "Logs: ${LOG_FILE}"
        echo ""

        # Last few log lines
        if [[ -f "$STDOUT_LOG" ]]; then
            echo -e "${CYAN}Last 5 log lines:${NC}"
            tail -5 "$STDOUT_LOG" 2>/dev/null || true
        fi
        ;;

    logs)
        echo -e "${CYAN}Tailing bot logs (Ctrl+C to stop)...${NC}"
        tail -f "$STDOUT_LOG" "$LOG_FILE" 2>/dev/null
        ;;

    errors)
        echo -e "${CYAN}Tailing error logs (Ctrl+C to stop)...${NC}"
        tail -f "$STDERR_LOG" 2>/dev/null
        ;;

    pid)
        PID=$(pgrep -f "claude-fallback-bot.py" 2>/dev/null | head -1 || true)
        if [[ -n "$PID" ]]; then
            echo "$PID"
        else
            echo "Not running"
            exit 1
        fi
        ;;

    menubar)
        echo -e "${CYAN}Menu bar indicator...${NC}"
        case "${2:-start}" in
            install)
                sed -e "s|__HOME__|${HOME}|g" -e "s|__SCRIPT_DIR__|${SCRIPT_DIR}|g" "$PLIST_MENUBAR_SRC" > "$PLIST_MENUBAR_DST"
                launchctl load "$PLIST_MENUBAR_DST"
                echo -e "${GREEN}Menu bar indicator installed and started.${NC}"
                ;;
            start)
                if [[ ! -f "$PLIST_MENUBAR_DST" ]]; then
                    sed -e "s|__HOME__|${HOME}|g" -e "s|__SCRIPT_DIR__|${SCRIPT_DIR}|g" "$PLIST_MENUBAR_SRC" > "$PLIST_MENUBAR_DST"
                fi
                launchctl load "$PLIST_MENUBAR_DST" 2>/dev/null || true
                echo -e "${GREEN}Menu bar indicator started.${NC}"
                ;;
            stop)
                launchctl unload "$PLIST_MENUBAR_DST" 2>/dev/null || true
                echo -e "${GREEN}Menu bar indicator stopped.${NC}"
                ;;
            uninstall)
                launchctl unload "$PLIST_MENUBAR_DST" 2>/dev/null || true
                rm -f "$PLIST_MENUBAR_DST"
                echo -e "${GREEN}Menu bar indicator uninstalled.${NC}"
                ;;
            *)
                echo "Usage: $(basename "$0") menubar [install|start|stop|uninstall]"
                ;;
        esac
        ;;

    install-deps)
        install_deps
        ;;

    help|*)
        echo "Claude Code Telegram Bot Manager"
        echo ""
        echo "Usage: $(basename "$0") <command>"
        echo ""
        echo "Commands:"
        echo "  install          Install bot as launchd service (auto-start on login)"
        echo "  install-deps     Install/check voice transcription dependencies"
        echo "  uninstall        Remove bot launchd service"
        echo "  start            Start the bot"
        echo "  stop             Stop the bot"
        echo "  restart          Restart the bot"
        echo "  status           Check status (process, memory, sessions)"
        echo "  logs             Tail all logs"
        echo "  errors           Tail error logs"
        echo "  pid              Show process ID"
        echo "  menubar install  Install menu bar indicator (auto-start on login)"
        echo "  menubar stop     Stop menu bar indicator"
        echo "  menubar uninstall Remove menu bar indicator"
        ;;
esac
