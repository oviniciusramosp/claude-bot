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

LABEL="com.claudebot.bot"
LABEL_MENUBAR="com.claudebot.menubar"
LABEL_WEB="com.claudebot.web"
# Legacy labels (used to detect and migrate old installations)
LEGACY_LABEL="com.vr.claude-bot"
LEGACY_LABEL_MENUBAR="com.vr.claude-bot-menubar"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="${SCRIPT_DIR}/com.claudebot.bot.plist"
PLIST_DST="${HOME}/Library/LaunchAgents/${LABEL}.plist"
PLIST_MENUBAR_SRC="${SCRIPT_DIR}/com.claudebot.menubar.plist"
PLIST_MENUBAR_DST="${HOME}/Library/LaunchAgents/${LABEL_MENUBAR}.plist"
PLIST_WEB_SRC="${SCRIPT_DIR}/com.claudebot.web.plist"
PLIST_WEB_DST="${HOME}/Library/LaunchAgents/${LABEL_WEB}.plist"
BOT_SCRIPT="${SCRIPT_DIR}/claude-fallback-bot.py"
WEB_SCRIPT="${SCRIPT_DIR}/claude-bot-web.py"
LOG_DIR="${HOME}/.claude-bot"
LOG_FILE="${LOG_DIR}/bot.log"
STDOUT_LOG="${LOG_DIR}/launchd-stdout.log"
STDERR_LOG="${LOG_DIR}/launchd-stderr.log"
WEB_STDOUT_LOG="${LOG_DIR}/web-stdout.log"
WEB_STDERR_LOG="${LOG_DIR}/web-stderr.log"

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

is_web_loaded() {
    launchctl list "$LABEL_WEB" 2>/dev/null | grep -q "PID"
}

_install_web() {
    if [[ ! -f "$PLIST_WEB_SRC" ]]; then
        echo -e "  web dashboard: ${YELLOW}plist not found at ${PLIST_WEB_SRC} — skipping${NC}"
        return
    fi
    if [[ ! -f "$WEB_SCRIPT" ]]; then
        echo -e "  web dashboard: ${YELLOW}script not found at ${WEB_SCRIPT} — skipping${NC}"
        return
    fi
    if is_web_loaded; then
        launchctl unload "$PLIST_WEB_DST" 2>/dev/null || true
    fi
    sed -e "s|__HOME__|${HOME}|g" -e "s|__SCRIPT_DIR__|${SCRIPT_DIR}|g" "$PLIST_WEB_SRC" > "$PLIST_WEB_DST"
    launchctl load "$PLIST_WEB_DST"
    if is_web_loaded; then
        echo -e "  web dashboard: ${GREEN}started${NC} (http://localhost:27184)"
    else
        echo -e "  web dashboard: ${RED}failed to start — check ${WEB_STDERR_LOG}${NC}"
    fi
}

_stop_web() {
    if is_web_loaded; then
        launchctl unload "$PLIST_WEB_DST" 2>/dev/null || true
    fi
}

_uninstall_web() {
    _stop_web
    rm -f "$PLIST_WEB_DST"
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

    # Detect Homebrew prefix (Apple Silicon: /opt/homebrew, Intel: /usr/local)
    local brew_prefix=""
    if command -v brew &>/dev/null; then
        brew_prefix=$(brew --prefix 2>/dev/null || echo "")
    elif [[ -x "/opt/homebrew/bin/brew" ]]; then
        brew_prefix="/opt/homebrew"
    elif [[ -x "/usr/local/bin/brew" ]]; then
        brew_prefix="/usr/local"
    fi

    # ffmpeg (check brew prefix first, then PATH)
    local ffmpeg_path=""
    if [[ -n "$brew_prefix" ]] && [[ -x "${brew_prefix}/bin/ffmpeg" ]]; then
        ffmpeg_path="${brew_prefix}/bin/ffmpeg"
    elif command -v ffmpeg &>/dev/null; then
        ffmpeg_path=$(command -v ffmpeg)
    fi

    if [[ -n "$ffmpeg_path" ]]; then
        echo -e "  ffmpeg: ${GREEN}found${NC} ($ffmpeg_path)"
    else
        if [[ -n "$brew_prefix" ]]; then
            echo -e "  ffmpeg: ${YELLOW}not found — installing via brew...${NC}"
            brew install ffmpeg --quiet
            if [[ -x "${brew_prefix}/bin/ffmpeg" ]] || command -v ffmpeg &>/dev/null; then
                echo -e "  ffmpeg: ${GREEN}installed${NC}"
            else
                echo -e "  ffmpeg: ${RED}brew install failed — install manually: brew install ffmpeg${NC}"
            fi
        else
            echo -e "  ffmpeg: ${RED}not found and Homebrew not available${NC}"
            echo -e "    Install Homebrew first: ${CYAN}https://brew.sh${NC}"
            echo -e "    Then run: ${CYAN}brew install ffmpeg${NC}"
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

init_vault_templates() {
    # Copy vault index templates on first run (only if the real file doesn't exist)
    local vault_dir="${SCRIPT_DIR}/vault"
    for template_path in "${vault_dir}/Routines/Routines.md.template" "${vault_dir}/Agents/Agents.md.template"; do
        [[ -f "$template_path" ]] || continue
        local target="${template_path%.template}"
        if [[ ! -f "$target" ]]; then
            cp "$template_path" "$target"
            echo -e "  vault: ${GREEN}initialized${NC} $(basename "$target")"
        fi
    done
}

case "${1:-help}" in
    install)
        echo -e "${CYAN}Installing Claude Bot service...${NC}"

        # Install dependencies
        install_deps

        # Initialize vault index files from templates (first-run only)
        init_vault_templates

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

        # Migrate from legacy bundle id (com.vr.claude-bot) if present
        LEGACY_PLIST_DST="${HOME}/Library/LaunchAgents/${LEGACY_LABEL}.plist"
        if [[ -f "$LEGACY_PLIST_DST" ]]; then
            echo -e "${YELLOW}Detected legacy service (${LEGACY_LABEL}) — migrating...${NC}"
            launchctl unload "$LEGACY_PLIST_DST" 2>/dev/null || true
            rm -f "$LEGACY_PLIST_DST"
        fi
        LEGACY_PLIST_MENUBAR_DST="${HOME}/Library/LaunchAgents/${LEGACY_LABEL_MENUBAR}.plist"
        if [[ -f "$LEGACY_PLIST_MENUBAR_DST" ]]; then
            launchctl unload "$LEGACY_PLIST_MENUBAR_DST" 2>/dev/null || true
            rm -f "$LEGACY_PLIST_MENUBAR_DST"
        fi

        # Copy plist with path substitution
        sed -e "s|__HOME__|${HOME}|g" -e "s|__SCRIPT_DIR__|${SCRIPT_DIR}|g" "$PLIST_SRC" > "$PLIST_DST"
        echo "Plist installed to: $PLIST_DST"

        # Load
        launchctl load "$PLIST_DST"
        sleep 1

        if is_loaded; then
            echo -e "${GREEN}Bot service installed and running.${NC}"
        else
            echo -e "${RED}Bot service loaded but may not be running. Check logs:${NC}"
            echo "  tail -f ${STDERR_LOG}"
        fi

        # Install web dashboard
        echo "Installing web dashboard..."
        _install_web

        echo ""
        echo "Both services will:"
        echo "  - Start automatically on login"
        echo "  - Restart automatically if they crash"
        echo "  - Log to ${LOG_DIR}/"
        echo ""
        echo "Use './claude-bot.sh status' to check."
        ;;

    uninstall)
        echo -e "${CYAN}Uninstalling Claude Bot services...${NC}"
        if is_loaded; then
            launchctl unload "$PLIST_DST" 2>/dev/null || true
        fi
        rm -f "$PLIST_DST"
        _uninstall_web
        echo -e "${GREEN}All services uninstalled.${NC}"
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

        # Also start web dashboard
        _install_web
        ;;

    stop)
        if is_loaded; then
            launchctl unload "$PLIST_DST" 2>/dev/null || true
            echo -e "${GREEN}Bot stopped.${NC}"
        else
            echo -e "${YELLOW}Bot is not running.${NC}"
        fi
        _stop_web
        echo -e "${GREEN}Web dashboard stopped.${NC}"
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

        # Also restart web dashboard
        _stop_web
        sleep 1
        _install_web
        ;;

    status)
        echo -e "${CYAN}Claude Bot Status${NC}"
        echo "────────────────────────────"

        # Bot
        if is_loaded; then
            echo -e "Bot service:  ${GREEN}LOADED${NC}"
        else
            echo -e "Bot service:  ${RED}NOT LOADED${NC}"
        fi

        PID=$(pgrep -f "claude-fallback-bot.py" 2>/dev/null | head -1 || true)
        if [[ -n "$PID" ]]; then
            echo -e "Bot process:  ${GREEN}RUNNING${NC} (PID: ${PID})"
            MEM=$(ps -o rss= -p "$PID" 2>/dev/null | awk '{printf "%.1f", $1/1024}' || echo "?")
            echo "Memory:       ${MEM} MB"
            ELAPSED=$(ps -o etime= -p "$PID" 2>/dev/null | xargs || echo "?")
            echo "Uptime:       ${ELAPSED}"
        else
            echo -e "Bot process:  ${RED}NOT RUNNING${NC}"
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

        echo ""

        # Web dashboard
        if is_web_loaded; then
            echo -e "Web service:  ${GREEN}LOADED${NC}"
        else
            echo -e "Web service:  ${RED}NOT LOADED${NC}"
        fi

        WEB_PID=$(pgrep -f "claude-bot-web.py" 2>/dev/null | head -1 || true)
        if [[ -n "$WEB_PID" ]]; then
            echo -e "Web process:  ${GREEN}RUNNING${NC} (PID: ${WEB_PID}) — http://localhost:27184"
        else
            echo -e "Web process:  ${RED}NOT RUNNING${NC}"
        fi

        echo "────────────────────────────"
        echo "Logs: ${LOG_FILE}"
        echo "Web:  ${WEB_STDOUT_LOG}"
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
        echo "  install          Install bot + web dashboard as launchd services (auto-start on login)"
        echo "  install-deps     Install/check voice transcription dependencies"
        echo "  uninstall        Remove all launchd services"
        echo "  start            Start bot + web dashboard"
        echo "  stop             Stop bot + web dashboard"
        echo "  restart          Restart bot + web dashboard"
        echo "  status           Check status (process, memory, sessions, web)"
        echo "  logs             Tail all logs"
        echo "  errors           Tail error logs"
        echo "  pid              Show process ID"
        echo "  menubar install  Install menu bar indicator (auto-start on login)"
        echo "  menubar stop     Stop menu bar indicator"
        echo "  menubar uninstall Remove menu bar indicator"
        ;;
esac
