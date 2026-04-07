#!/usr/bin/env python3
"""
Claude Bot — Menu Bar Indicator
================================
macOS menu bar app that monitors and controls the Claude Bot service.
Auto-starts the bot on launch, auto-stops on quit.

Requires: pip3 install rumps
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

# Set process name for Activity Monitor
try:
    from ctypes import cdll, c_char_p
    libc = cdll.LoadLibrary("libc.dylib")
    libc.setprogname(c_char_p(b"Claude Bot"))
except Exception:
    pass

# Hide Python from Dock
try:
    from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSProcessInfo
    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    NSProcessInfo.processInfo().setValue_forKey_("Claude Bot", "processName")
except ImportError:
    pass

import rumps


# ---------------------------------------------------------------------------
# SF Symbol helpers
# ---------------------------------------------------------------------------

def make_sf_symbol(name, size=14, color=None):
    try:
        from AppKit import NSImage, NSImageSymbolConfiguration, NSColor
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_(name, None)
        if img is None:
            return None
        size_cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(size, 0)
        if color:
            ns_color = {
                "green": NSColor.systemGreenColor(),
                "red": NSColor.systemRedColor(),
                "orange": NSColor.systemOrangeColor(),
                "gray": NSColor.systemGrayColor(),
                "blue": NSColor.systemBlueColor(),
                "purple": NSColor.systemPurpleColor(),
            }.get(color)
            if ns_color:
                color_cfg = NSImageSymbolConfiguration.configurationWithHierarchicalColor_(ns_color)
                combined = size_cfg.configurationByApplyingConfiguration_(color_cfg)
                return img.imageWithSymbolConfiguration_(combined)
        return img.imageWithSymbolConfiguration_(size_cfg)
    except Exception:
        return None


def item_with_icon(title, symbol, color=None, size=14, callback=None):
    item = rumps.MenuItem(title, callback=callback)
    img = make_sf_symbol(symbol, size=size, color=color)
    if img:
        item._menuitem.setImage_(img)
    return item


# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

LABEL = "com.vr.claude-bot"
BOT_PROCESS = "claude-fallback-bot.py"
HOME = os.path.expanduser("~")
SCRIPTS_DIR = os.path.join(HOME, "claude-bot")
DATA_DIR = os.path.join(HOME, ".claude-bot")
SESSION_FILE = os.path.join(DATA_DIR, "sessions.json")
COSTS_FILE = os.path.join(DATA_DIR, "costs.json")
LOG_FILE = os.path.join(DATA_DIR, "bot.log")
STDOUT_LOG = os.path.join(DATA_DIR, "launchd-stdout.log")
PLIST_SRC = os.path.join(SCRIPTS_DIR, "com.vr.claude-bot.plist")
PLIST_DST = os.path.join(HOME, f"Library/LaunchAgents/{LABEL}.plist")

VAULT_DIR = os.path.join(SCRIPTS_DIR, "vault")
ROUTINES_DIR = os.path.join(VAULT_DIR, "Routines")
AGENTS_DIR = os.path.join(VAULT_DIR, "Agents")
ROUTINES_STATE_DIR = os.path.join(DATA_DIR, "routines-state")

DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
CONTROL_PORT = 27182


# ---------------------------------------------------------------------------
# Frontmatter parser (local copy)
# ---------------------------------------------------------------------------

def _strip_quotes(s):
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def _parse_yaml_value(val):
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    if val.startswith("[") and val.endswith("]"):
        items = val[1:-1].split(",")
        return [_strip_quotes(i.strip()) for i in items if i.strip()]
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    try:
        return float(val) if "." in val else int(val)
    except ValueError:
        return val


def parse_frontmatter(text):
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end < 0:
        return {}
    result = {}
    current_block = None
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if current_block and line.startswith("  ") and ":" in stripped:
            key, _, val = stripped.partition(":")
            if isinstance(result.get(current_block), dict):
                result[current_block][key.strip()] = _parse_yaml_value(val.strip())
            continue
        if ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            key, val = key.strip(), val.strip()
            if val == "":
                result[key] = {}
                current_block = key
            else:
                result[key] = _parse_yaml_value(val)
                current_block = None
    return result


# ---------------------------------------------------------------------------
# Data readers
# ---------------------------------------------------------------------------

def is_running():
    try:
        return subprocess.run(["pgrep", "-f", BOT_PROCESS],
                              capture_output=True, text=True, timeout=5).returncode == 0
    except Exception:
        return False


def get_pid():
    try:
        r = subprocess.run(["pgrep", "-f", BOT_PROCESS],
                           capture_output=True, text=True, timeout=5)
        pids = r.stdout.strip().split("\n")
        return pids[0] if pids[0] else ""
    except Exception:
        return ""


def get_process_info(pid):
    info = {"memory": "?", "uptime": "?"}
    if not pid:
        return info
    try:
        r = subprocess.run(["ps", "-o", "rss=,etime=", "-p", pid],
                           capture_output=True, text=True, timeout=5)
        parts = r.stdout.strip().split()
        if len(parts) >= 2:
            info["memory"] = f"{int(parts[0]) / 1024:.1f} MB"
            info["uptime"] = parts[1]
    except Exception:
        pass
    return info


def get_session_info():
    info = {"active": "?", "count": 0, "agent": None, "model": "?"}
    try:
        if os.path.exists(SESSION_FILE):
            with open(SESSION_FILE) as f:
                data = json.load(f)
            active = data.get("active_session", "?")
            info["active"] = active
            info["count"] = len(data.get("sessions", {}))
            sessions = data.get("sessions", {})
            if active and active in sessions:
                info["agent"] = sessions[active].get("agent")
                info["model"] = sessions[active].get("model", "?")
    except Exception:
        pass
    return info


def get_agents():
    if not os.path.isdir(AGENTS_DIR):
        return []
    agents = []
    try:
        for d in sorted(os.listdir(AGENTS_DIR)):
            agent_file = os.path.join(AGENTS_DIR, d, "agent.md")
            if os.path.isfile(agent_file):
                with open(agent_file, encoding="utf-8") as f:
                    fm = parse_frontmatter(f.read())
                if fm:
                    fm["_id"] = d
                    agents.append(fm)
    except Exception:
        pass
    return agents


def get_weekly_cost():
    try:
        if not os.path.exists(COSTS_FILE):
            return {"week": "", "total": 0.0, "today": 0.0}
        with open(COSTS_FILE) as f:
            data = json.load(f)
        week_key = time.strftime("%G-W%V")
        week = data.get("weeks", {}).get(week_key, {})
        today = time.strftime("%Y-%m-%d")
        return {
            "week": week_key,
            "total": week.get("total", 0.0),
            "today": week.get("days", {}).get(today, 0.0),
        }
    except Exception:
        return {"week": "", "total": 0.0, "today": 0.0}


def get_today_routines():
    if not os.path.isdir(ROUTINES_DIR):
        return []
    now_day_idx = time.localtime().tm_wday
    today_str = time.strftime("%Y-%m-%d")
    state = {}
    state_file = os.path.join(ROUTINES_STATE_DIR, f"{today_str}.json")
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                state = json.load(f)
        except Exception:
            pass
    routines = []
    try:
        files = sorted(f for f in os.listdir(ROUTINES_DIR) if f.endswith(".md"))
    except Exception:
        return []
    for fname in files:
        try:
            with open(os.path.join(ROUTINES_DIR, fname), encoding="utf-8") as f:
                fm = parse_frontmatter(f.read())
            if not fm or not fm.get("enabled", False):
                continue
            schedule = fm.get("schedule", {})
            if not isinstance(schedule, dict):
                continue
            until = schedule.get("until") or fm.get("until")
            if until and str(until) < today_str:
                continue
            days = schedule.get("days", ["*"])
            if isinstance(days, list) and "*" not in days:
                if not any(DAY_MAP.get(str(d).lower().strip(), -1) == now_day_idx for d in days):
                    continue
            routine_name = fname.replace(".md", "")
            for t in schedule.get("times", []):
                t_str = str(t).strip()
                entry = state.get(routine_name, {}).get(t_str, {})
                routines.append({
                    "name": routine_name,
                    "title": fm.get("title", routine_name),
                    "time": t_str,
                    "status": entry.get("status", "pending"),
                })
        except Exception:
            continue
    routines.sort(key=lambda r: r["time"])
    return routines


# ---------------------------------------------------------------------------
# Control server helpers
# ---------------------------------------------------------------------------

def _control_post(endpoint: str, data: dict) -> bool:
    """POST to the bot's HTTP control server. Returns True on success."""
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"http://127.0.0.1:{CONTROL_PORT}{endpoint}",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Bot lifecycle
# ---------------------------------------------------------------------------

def _ensure_plist():
    if not os.path.exists(PLIST_DST):
        try:
            import shutil
            shutil.copy2(PLIST_SRC, PLIST_DST)
            # Substitute placeholders
            with open(PLIST_DST) as f:
                content = f.read()
            content = content.replace("__HOME__", HOME).replace("__SCRIPT_DIR__", SCRIPTS_DIR)
            with open(PLIST_DST, "w") as f:
                f.write(content)
        except Exception:
            pass


def start_bot():
    _ensure_plist()
    subprocess.run(["launchctl", "load", PLIST_DST], capture_output=True)


def stop_bot():
    subprocess.run(["launchctl", "unload", PLIST_DST], capture_output=True)


# ---------------------------------------------------------------------------
# Menu Bar App
# ---------------------------------------------------------------------------

class ClaudeBotMenuBar(rumps.App):
    def __init__(self):
        super().__init__("Claude Bot", quit_button=None)
        # Auto-start bot
        if not is_running():
            start_bot()
            time.sleep(2)
        self._update_icon()
        self._rebuild_menu()

    def _update_icon(self):
        running = is_running()
        img = make_sf_symbol("circle.fill", size=12, color="green" if running else "red")
        if img:
            try:
                self._status_item.button().setImage_(img)
                self._status_item.button().setTitle_("")
            except Exception:
                self.title = "●"
        else:
            self.title = "●"

    def _rebuild_menu(self):
        running = is_running()
        pid = get_pid() if running else ""
        proc_info = get_process_info(pid) if pid else {}
        sess_info = get_session_info()
        costs = get_weekly_cost()

        self.menu.clear()

        # ── Status ──
        if running:
            uptime = proc_info.get("uptime", "?")
            self.menu.add(item_with_icon(f"Claude Bot — Running ({uptime})", "circle.fill", color="green"))
        else:
            self.menu.add(item_with_icon("Claude Bot — Stopped", "circle.fill", color="red"))

        # ── Session ──
        model = sess_info.get("model", "?")
        self.menu.add(item_with_icon(
            f"Session: {sess_info['active']} ({model})", "text.bubble", color="blue"))

        # Active agent
        agents = get_agents()
        active_agent_id = sess_info.get("agent")
        if active_agent_id:
            for a in agents:
                if a["_id"] == active_agent_id:
                    icon = a.get("icon", "🤖")
                    name = a.get("name", a["_id"])
                    self.menu.add(item_with_icon(f"Agent: {icon} {name}", "person.fill", color="purple"))
                    break

        # ── Cost tracker ──
        if costs["total"] > 0 or costs["today"] > 0:
            self.menu.add(item_with_icon(
                f"Week: ${costs['total']:.2f}  ·  Today: ${costs['today']:.2f}",
                "dollarsign.circle", color="orange"))

        self.menu.add(rumps.separator)

        # ── Routines ──
        routines = get_today_routines()
        if routines:
            _icons = {
                "pending": ("circle", "gray"),
                "running": ("arrow.triangle.2.circlepath", "orange"),
                "completed": ("checkmark.circle.fill", "green"),
                "failed": ("exclamationmark.circle.fill", "red"),
            }
            self.menu.add(item_with_icon(f"Routines — {time.strftime('%d %b')}", "calendar.badge.clock", color="blue"))
            for r in routines:
                sym, col = _icons.get(r["status"], ("circle", "gray"))
                header = item_with_icon(f"  {r['time']}  {r['title']}", sym, color=col)
                # Run Now action
                def _make_run_cb(name, time_slot):
                    def _cb(_):
                        _control_post("/routine/run", {"name": name, "time_slot": time_slot})
                    return _cb
                run_item = item_with_icon("    ▶ Run Now", "play.circle", color="green",
                                         callback=_make_run_cb(r["name"], r["time"]))
                header.update({run_item.title: run_item})
                # Stop action — only useful when running
                if r["status"] == "running":
                    def _make_stop_cb(name):
                        def _cb(_):
                            _control_post("/routine/stop", {"name": name})
                        return _cb
                    stop_item = item_with_icon("    ⏹ Stop", "stop.circle", color="red",
                                              callback=_make_stop_cb(r["name"]))
                    header.update({stop_item.title: stop_item})
                self.menu.add(header)
            self.menu.add(rumps.separator)

        # ── Agents list ──
        if agents:
            self.menu.add(item_with_icon("Agents", "person.3.fill", color="purple"))
            for a in agents:
                icon = a.get("icon", "🤖")
                name = a.get("name", a["_id"])
                is_active = a["_id"] == active_agent_id
                marker = " ◀" if is_active else ""
                col = "purple" if is_active else "gray"
                self.menu.add(item_with_icon(f"  {icon} {name}{marker}", "person.crop.circle", color=col))
            self.menu.add(rumps.separator)

        # ── Controls ──
        if running:
            self.menu.add(item_with_icon("Restart Bot", "arrow.clockwise", callback=self.restart_bot))
            self.menu.add(item_with_icon("Stop Bot", "stop.fill", color="red", callback=self.stop_bot_action))
        else:
            self.menu.add(item_with_icon("Start Bot", "play.fill", color="green", callback=self.start_bot_action))

        self.menu.add(rumps.separator)

        # ── Files ──
        self.menu.add(item_with_icon("Open Logs", "doc.text.magnifyingglass", callback=self.open_logs))
        self.menu.add(item_with_icon("Open Vault", "folder", callback=self.open_vault))
        self.menu.add(item_with_icon("Show in Finder", "magnifyingglass", callback=self.show_in_finder))

        self.menu.add(rumps.separator)
        self.menu.add(item_with_icon("Quit Claude Bot", "power", color="red", callback=self.quit_app))

    @rumps.timer(10)
    def refresh(self, _):
        self._update_icon()
        self._rebuild_menu()

    def start_bot_action(self, _):
        start_bot()
        time.sleep(2)
        self._update_icon()
        self._rebuild_menu()
        if is_running():
            rumps.notification("Claude Bot", "Started", "Bot is now running.")
        else:
            rumps.notification("Claude Bot", "Error", "Bot failed to start. Check logs.")

    def stop_bot_action(self, _):
        stop_bot()
        time.sleep(2)
        self._update_icon()
        self._rebuild_menu()
        rumps.notification("Claude Bot", "Stopped", "Bot has been stopped.")

    def restart_bot(self, _):
        stop_bot()
        time.sleep(2)
        start_bot()
        time.sleep(2)
        self._update_icon()
        self._rebuild_menu()
        if is_running():
            rumps.notification("Claude Bot", "Restarted", "Bot is running again.")
        else:
            rumps.notification("Claude Bot", "Error", "Bot failed to restart.")

    def open_logs(self, _):
        if os.path.exists(STDOUT_LOG):
            subprocess.run(["open", STDOUT_LOG])
        elif os.path.exists(LOG_FILE):
            subprocess.run(["open", LOG_FILE])

    def open_vault(self, _):
        if os.path.isdir(VAULT_DIR):
            subprocess.run(["open", VAULT_DIR])

    def show_in_finder(self, _):
        subprocess.run(["open", SCRIPTS_DIR])

    def quit_app(self, _):
        # Auto-stop bot on quit
        if is_running():
            stop_bot()
        rumps.quit_application()


if __name__ == "__main__":
    ClaudeBotMenuBar().run()
