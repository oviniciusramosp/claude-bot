#!/usr/bin/env python3
"""
claude-bot-web.py — Mobile-friendly web dashboard for claude-bot.

Standalone stdlib-only Python HTTP server that replicates ClaudeBotManager
functionality (Dashboard, Agents, Routines, Settings) as a responsive web app.

Reads vault files and ~/.claude-bot/ state directly.
Proxies control commands to the bot's control server on port 27182.
Serves a vanilla JS SPA (Alpine.js + Tailwind CSS from CDN).

Usage:
    python3 claude-bot-web.py [--port PORT]

Tunnel (pick one):
    cloudflared tunnel --url http://localhost:27184
    tailscale funnel 27184
    ssh -R 8080:localhost:27184 user@vps
"""

from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Import frontmatter parser from scripts/
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "scripts"))
from vault_frontmatter import (  # noqa: E402
    get_frontmatter_and_body,
    parse_frontmatter,
    serialize_frontmatter,
    write_frontmatter_file,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WEB_PORT = 27184
CONTROL_PORT = 27182
VAULT_DIR = SCRIPT_DIR / "vault"
HOME_DIR = Path.home()
BOT_DATA_DIR = HOME_DIR / ".claude-bot"
BOT_ENV_FILE = HOME_DIR / "claude-bot" / ".env"
VAULT_ENV_FILE = VAULT_DIR / ".env"
CONTROL_TOKEN_FILE = BOT_DATA_DIR / ".control-token"
SESSIONS_FILE = BOT_DATA_DIR / "sessions.json"
COSTS_FILE = BOT_DATA_DIR / "costs.json"
ROUTINES_STATE_DIR = BOT_DATA_DIR / "routines-state"
BOT_LOG_FILE = BOT_DATA_DIR / "bot.log"
WEB_DIR = SCRIPT_DIR / "web"

RESERVED_VAULT_NAMES = {
    "README.md", "CLAUDE.md", "Tooling.md", ".env", ".graphs",
    ".obsidian", ".claude", "Images", "__pycache__", "Agents",
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

AGENT_ORDERED_KEYS = [
    "title", "description", "type", "created", "updated", "tags",
    "name", "model", "icon", "color", "default", "personality",
    "chat_id", "thread_id", "source", "source_id",
]

ROUTINE_ORDERED_KEYS = [
    "title", "description", "type", "created", "updated", "tags",
    "schedule", "model", "enabled", "notify", "context",
]

AGENT_SUBDIRS = [
    "Skills", "Routines", "Reactions", "Lessons", "Notes",
    ".workspace", "Journal", "Journal/.activity",
]

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class AuthManager:
    MAX_ATTEMPTS = 5
    ATTEMPT_WINDOW = 60  # seconds
    SESSION_TTL = 86400  # 24 hours

    def __init__(self):
        self._boot_secret = secrets.token_bytes(32)
        self._sessions: Dict[str, float] = {}  # session_id -> expiry
        self._login_attempts: Dict[str, List[float]] = {}  # ip -> [timestamps]
        self._pin = self._load_or_generate_pin()

    def _load_or_generate_pin(self) -> str:
        env = _parse_env_file(BOT_ENV_FILE)
        pin = env.get("WEB_PIN", "").strip()
        if pin:
            return pin
        pin = f"{secrets.randbelow(1000000):06d}"
        # Append to .env
        try:
            with open(BOT_ENV_FILE, "a") as f:
                f.write(f"\nWEB_PIN={pin}\n")
        except Exception:
            pass
        return pin

    def check_pin(self, pin: str, ip: str) -> Optional[str]:
        now = time.time()
        attempts = self._login_attempts.get(ip, [])
        attempts = [t for t in attempts if now - t < self.ATTEMPT_WINDOW]
        self._login_attempts[ip] = attempts
        if len(attempts) >= self.MAX_ATTEMPTS:
            return None
        attempts.append(now)
        self._login_attempts[ip] = attempts
        if not hmac.compare_digest(pin, self._pin):
            return None
        sid = secrets.token_hex(16)
        self._sessions[sid] = now + self.SESSION_TTL
        return self._sign_session(sid)

    def validate_session(self, cookie_header: str) -> bool:
        if not cookie_header:
            return False
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return False
        morsel = cookie.get("session")
        if not morsel:
            return False
        token = morsel.value
        parts = token.rsplit(".", 1)
        if len(parts) != 2:
            return False
        sid, sig = parts
        expected = hmac.new(
            self._boot_secret, sid.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return False
        expiry = self._sessions.get(sid)
        if not expiry or time.time() > expiry:
            self._sessions.pop(sid, None)
            return False
        return True

    def logout(self, cookie_header: str):
        if not cookie_header:
            return
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except Exception:
            return
        morsel = cookie.get("session")
        if not morsel:
            return
        parts = morsel.value.rsplit(".", 1)
        if len(parts) == 2:
            self._sessions.pop(parts[0], None)

    def _sign_session(self, sid: str) -> str:
        sig = hmac.new(
            self._boot_secret, sid.encode(), hashlib.sha256
        ).hexdigest()
        return f"{sid}.{sig}"

    def cleanup(self):
        now = time.time()
        expired = [k for k, v in self._sessions.items() if now > v]
        for k in expired:
            del self._sessions[k]


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def iter_agent_ids() -> List[str]:
    agents = []
    if not VAULT_DIR.is_dir():
        return agents
    for entry in sorted(VAULT_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith(".") or entry.name in RESERVED_VAULT_NAMES:
            continue
        hub = entry / f"agent-{entry.name}.md"
        if hub.is_file():
            agents.append(entry.name)
    return agents


def load_agents() -> List[Dict[str, Any]]:
    agents = []
    for aid in iter_agent_ids():
        hub_file = VAULT_DIR / aid / f"agent-{aid}.md"
        fm, _ = get_frontmatter_and_body(hub_file)
        claude_md = VAULT_DIR / aid / "CLAUDE.md"
        personality = ""
        if claude_md.is_file():
            try:
                personality = claude_md.read_text(encoding="utf-8")
            except Exception:
                pass
        agents.append({
            "id": aid,
            "name": fm.get("name", aid),
            "icon": fm.get("icon", ""),
            "description": fm.get("description", ""),
            "model": fm.get("model", "sonnet"),
            "color": fm.get("color", "grey"),
            "tags": fm.get("tags", []),
            "isDefault": fm.get("default", False),
            "personality": personality,
            "created": str(fm.get("created", "")),
            "updated": str(fm.get("updated", "")),
            "chatId": str(fm.get("chat_id", "")),
            "threadId": str(fm.get("thread_id", "")),
        })
    return agents


def load_routines() -> List[Dict[str, Any]]:
    routines = []
    for aid in iter_agent_ids():
        routines_dir = VAULT_DIR / aid / "Routines"
        if not routines_dir.is_dir():
            continue
        for f in sorted(routines_dir.iterdir()):
            if not f.is_file() or f.suffix != ".md":
                continue
            if f.name.startswith("agent-"):
                continue
            fm, body = get_frontmatter_and_body(f)
            if not fm:
                continue
            schedule = fm.get("schedule", {})
            if not isinstance(schedule, dict):
                schedule = {}
            rtype = fm.get("type", "routine")
            step_count = body.count("- id:") if rtype == "pipeline" else 0
            routines.append({
                "id": f.stem,
                "title": fm.get("title", f.stem),
                "description": fm.get("description", ""),
                "type": rtype,
                "model": fm.get("model", "sonnet"),
                "enabled": fm.get("enabled", True),
                "schedule": {
                    "times": schedule.get("times", []),
                    "days": schedule.get("days", ["*"]),
                    "interval": schedule.get("interval"),
                    "monthdays": schedule.get("monthdays", []),
                    "until": schedule.get("until"),
                },
                "ownerAgentId": aid,
                "tags": fm.get("tags", []),
                "created": str(fm.get("created", "")),
                "updated": str(fm.get("updated", "")),
                "stepCount": step_count,
                "notify": fm.get("notify", "final"),
                "minimalContext": fm.get("context") == "minimal",
                "promptBody": body,
            })
    return routines


def load_routines_state(date_str: str = None) -> Dict:
    if date_str is None:
        date_str = date.today().isoformat()
    state_file = ROUTINES_STATE_DIR / f"{date_str}.json"
    if state_file.is_file():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _parse_env_file(path: Path) -> Dict[str, str]:
    result = {}
    if not path.is_file():
        return result
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            # Strip surrounding quotes
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                val = val[1:-1]
            result[key] = val
    except Exception:
        pass
    return result


def load_settings() -> Dict:
    bot_env = _parse_env_file(BOT_ENV_FILE)
    vault_env = _parse_env_file(VAULT_ENV_FILE)
    sensitive = {"TOKEN", "KEY", "SECRET", "PASSWORD", "PIN"}
    masked_bot = {}
    for k, v in bot_env.items():
        if any(s in k.upper() for s in sensitive):
            masked_bot[k] = v[:4] + "..." + v[-4:] if len(v) > 8 else "****"
        else:
            masked_bot[k] = v
    masked_vault = {}
    for k, v in vault_env.items():
        if any(s in k.upper() for s in sensitive):
            masked_vault[k] = v[:4] + "..." + v[-4:] if len(v) > 8 else "****"
        else:
            masked_vault[k] = v
    return {"bot": masked_bot, "vault": masked_vault}


def _get_claude_token() -> str:
    """Read Claude OAuth access token from macOS keychain."""
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", "claude", "-a", "claude", "-w"],
            capture_output=True, timeout=5,
        )
        raw = proc.stdout.decode("utf-8", errors="replace").strip()
        if not raw:
            return ""
        try:
            obj = json.loads(raw)
            return obj.get("claudeAiOauth", {}).get("accessToken", "")
        except Exception:
            return raw
    except Exception:
        return ""


def _count_routines() -> int:
    count = 0
    for aid in iter_agent_ids():
        d = VAULT_DIR / aid / "Routines"
        if d.is_dir():
            count += sum(1 for f in d.iterdir()
                         if f.suffix == ".md" and f.name != "agent-routines.md")
    return count


def _count_skills() -> int:
    count = 0
    for aid in iter_agent_ids():
        d = VAULT_DIR / aid / "Skills"
        if d.is_dir():
            count += sum(1 for f in d.iterdir()
                         if f.suffix == ".md" and f.name != "agent-skills.md")
    return count


def load_usage() -> Dict:
    """Aggregate Claude + ZAI usage data + vault counts for the dashboard.
    Prefers usage-cache.json written by the macOS app (authoritative, fresh).
    Falls back to direct API calls when the cache is absent or stale (>10min)."""
    from datetime import timedelta
    from urllib.parse import urlparse as _up, urlunparse as _uu, parse_qsl

    # --- Try macOS app cache first ---
    cache_file = BOT_DATA_DIR / "usage-cache.json"
    if cache_file.is_file():
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            updated_at = cached.get("updatedAt")
            if updated_at:
                from email.utils import parsedate_to_datetime
                try:
                    age = (datetime.now().astimezone() - datetime.fromisoformat(updated_at)).total_seconds()
                except Exception:
                    age = 9999
                if age < 600:  # fresh if written within 10 minutes
                    # Merge with live vault counts (always fresh)
                    counts = {
                        "agents": len(iter_agent_ids()) + 1,
                        "routines": _count_routines(),
                        "skills": _count_skills(),
                    }
                    cached["counts"] = counts
                    return cached
        except Exception:
            pass

    result: Dict = {
        "claude": {
            "available": False,
            "weeklyPercent": 0,
            "weeklyResetsAt": None,
            "planName": None,
            "rateTier": None,
        },
        "zai": {
            "configured": False,
            "available": False,
            "weeklyPercent": 0,
            "sessionPercent": 0,
            "weeklyCostUSD": 0,
            "todayCostUSD": 0,
            "planLevel": None,
            "weeklyResetsAt": None,
        },
        "counts": {
            "agents": len(iter_agent_ids()) + 1,  # +1 for main
            "routines": _count_routines(),
            "skills": _count_skills(),
        },
    }

    # --- Claude usage ---
    token = _get_claude_token()
    if token:
        headers = {
            "Authorization": f"Bearer {token}",
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            req = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                sd = data.get("seven_day") or {}
                pct = sd.get("percent", 0) or 0
                result["claude"]["available"] = True
                result["claude"]["weeklyPercent"] = round(pct * 100 if pct <= 1.0 else pct, 1)
                result["claude"]["weeklyResetsAt"] = sd.get("resets_at")
        except Exception:
            pass
        try:
            req = urllib.request.Request("https://api.anthropic.com/api/oauth/claude_cli/roles", headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                result["claude"]["planName"] = data.get("organization_name")
                result["claude"]["rateTier"] = str(data.get("rate_limit_tier") or "")
        except Exception:
            pass

    # --- ZAI usage ---
    bot_env = _parse_env_file(BOT_ENV_FILE)
    zai_key = bot_env.get("ZAI_API_KEY", "").strip()
    zai_base = bot_env.get("ZAI_BASE_URL", "https://api.z.ai/api/anthropic").strip()

    if zai_key:
        result["zai"]["configured"] = True

        # Local costs from costs.json
        costs_file = BOT_DATA_DIR / "costs.json"
        if costs_file.is_file():
            try:
                costs_data = json.loads(costs_file.read_text(encoding="utf-8"))
                today_str = date.today().isoformat()
                week_total = 0.0
                today_total = 0.0
                for i in range(7):
                    day = (date.today() - timedelta(days=i)).isoformat()
                    day_costs = costs_data.get(day, {})
                    zai_day = day_costs.get("zai", {})
                    day_cost = float(zai_day.get("total") or zai_day.get("cost") or 0)
                    week_total += day_cost
                    if day == today_str:
                        today_total = day_cost
                result["zai"]["weeklyCostUSD"] = round(week_total, 4)
                result["zai"]["todayCostUSD"] = round(today_total, 4)
            except Exception:
                pass

        # ZAI quota API
        try:
            parsed_base = _up(zai_base)
            quota_url = _uu((parsed_base.scheme, parsed_base.netloc,
                              "/api/monitor/usage/quota/limit", "", "", ""))
            req = urllib.request.Request(quota_url, headers={
                "Authorization": zai_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                result["zai"]["available"] = True
                pct_w = float(data.get("weeklyPercent") or data.get("weekly_percent") or 0)
                pct_s = float(data.get("sessionPercent") or data.get("session_percent") or 0)
                result["zai"]["weeklyPercent"] = round(pct_w * 100 if pct_w <= 1.0 else pct_w, 1)
                result["zai"]["sessionPercent"] = round(pct_s * 100 if pct_s <= 1.0 else pct_s, 1)
                result["zai"]["planLevel"] = (data.get("level") or data.get("planLevel")
                                               or data.get("plan_level"))
                result["zai"]["weeklyResetsAt"] = (data.get("weeklyResetsAt")
                                                    or data.get("weekly_resets_at"))
        except Exception:
            pass

    return result


# ---------------------------------------------------------------------------
# Data saving
# ---------------------------------------------------------------------------


def save_agent(agent_data: Dict[str, Any]) -> bool:
    aid = agent_data.get("id", "")
    if not aid:
        return False
    agent_dir = VAULT_DIR / aid
    is_new = not agent_dir.is_dir()

    if is_new:
        agent_dir.mkdir(parents=True, exist_ok=True)
        for subdir in AGENT_SUBDIRS:
            (agent_dir / subdir).mkdir(parents=True, exist_ok=True)

    # Build frontmatter
    hub_file = agent_dir / f"agent-{aid}.md"
    today = date.today().isoformat()
    fm: Dict[str, Any] = {}
    fm["title"] = agent_data.get("name", aid)
    fm["description"] = agent_data.get("description", "")
    fm["type"] = "agent"
    fm["created"] = agent_data.get("created", today)
    fm["updated"] = today
    fm["tags"] = agent_data.get("tags", ["agent", "hub"])
    fm["name"] = agent_data.get("name", aid)
    fm["model"] = agent_data.get("model", "sonnet")
    fm["icon"] = agent_data.get("icon", "")
    fm["color"] = agent_data.get("color", "grey")
    fm["default"] = agent_data.get("isDefault", False)
    if agent_data.get("chatId"):
        fm["chat_id"] = agent_data["chatId"]
    if agent_data.get("threadId"):
        fm["thread_id"] = agent_data["threadId"]

    # Hub body: wikilinks
    body = f"## {fm['name']}\n\n"
    body += f"- [[agent-skills|Skills]]\n"
    body += f"- [[agent-routines|Routines]]\n"
    body += f"- [[agent-reactions|Reactions]]\n"

    write_frontmatter_file(hub_file, fm, body, AGENT_ORDERED_KEYS)

    # Write CLAUDE.md
    personality = agent_data.get("personality", "")
    claude_md = agent_dir / "CLAUDE.md"
    claude_md.write_text(personality, encoding="utf-8")

    return True


def save_routine(agent_id: str, routine_data: Dict[str, Any]) -> bool:
    rid = routine_data.get("id", "")
    if not rid or not agent_id:
        return False
    routines_dir = VAULT_DIR / agent_id / "Routines"
    routines_dir.mkdir(parents=True, exist_ok=True)

    filepath = routines_dir / f"{rid}.md"
    today = date.today().isoformat()

    schedule = routine_data.get("schedule", {})
    fm: Dict[str, Any] = {}
    fm["title"] = routine_data.get("title", rid)
    fm["description"] = routine_data.get("description", "")
    fm["type"] = routine_data.get("type", "routine")
    fm["created"] = routine_data.get("created", today)
    fm["updated"] = today
    fm["tags"] = routine_data.get("tags", [fm["type"]])
    fm["schedule"] = {}
    if schedule.get("days"):
        fm["schedule"]["days"] = schedule["days"]
    if schedule.get("times"):
        fm["schedule"]["times"] = schedule["times"]
    if schedule.get("interval"):
        fm["schedule"]["interval"] = schedule["interval"]
    if schedule.get("monthdays"):
        fm["schedule"]["monthdays"] = schedule["monthdays"]
    if schedule.get("until"):
        fm["schedule"]["until"] = schedule["until"]
    fm["model"] = routine_data.get("model", "sonnet")
    fm["enabled"] = routine_data.get("enabled", True)
    if routine_data.get("notify"):
        fm["notify"] = routine_data["notify"]
    if routine_data.get("minimalContext"):
        fm["context"] = "minimal"

    body = routine_data.get("promptBody", "")
    write_frontmatter_file(filepath, fm, body, ROUTINE_ORDERED_KEYS)
    return True


def save_env_file(path: Path, updates: Dict[str, str]) -> bool:
    """Update .env file preserving comments and structure."""
    try:
        lines = []
        existing_keys = set()
        if path.is_file():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        lines.append(f"{key}={updates[key]}")
                        existing_keys.add(key)
                        continue
                lines.append(line)
        # Append new keys
        for k, v in updates.items():
            if k not in existing_keys:
                lines.append(f"{k}={v}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Control server proxy
# ---------------------------------------------------------------------------


def proxy_to_control(method: str, path: str, body: Dict = None) -> Tuple[int, Dict]:
    token = ""
    if CONTROL_TOKEN_FILE.is_file():
        try:
            token = CONTROL_TOKEN_FILE.read_text().strip()
        except Exception:
            pass
    url = f"http://127.0.0.1:{CONTROL_PORT}{path}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Bot-Token"] = token
    try:
        if method == "GET":
            req = urllib.request.Request(url, headers=headers)
        else:
            data = json.dumps(body or {}).encode()
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            body_text = e.read().decode()
            return e.code, json.loads(body_text)
        except Exception:
            return e.code, {"error": str(e.reason)}
    except Exception as e:
        return 503, {"error": str(e)}


# ---------------------------------------------------------------------------
# Bot process control (launchctl)
# ---------------------------------------------------------------------------

LAUNCHD_LABEL = "com.claudebot.bot"


def _launchctl(cmd: str) -> Tuple[bool, str]:
    try:
        r = subprocess.run(
            ["launchctl", cmd, f"gui/{os.getuid()}/{LAUNCHD_LABEL}"],
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0, r.stderr.strip() or r.stdout.strip()
    except Exception as e:
        return False, str(e)


def bot_start() -> Tuple[bool, str]:
    return _launchctl("kickstart")


def bot_stop() -> Tuple[bool, str]:
    return _launchctl("kill")


def bot_restart() -> Tuple[bool, str]:
    ok, msg = bot_stop()
    time.sleep(1)
    return bot_start()


# ---------------------------------------------------------------------------
# HTTP Handler
# ---------------------------------------------------------------------------


def make_handler(auth: AuthManager):
    class Handler(http.server.BaseHTTPRequestHandler):

        def _respond(self, status: int, data: Any):
            body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)

        def _read_body(self) -> Dict:
            length = int(self.headers.get("Content-Length", 0))
            if length == 0:
                return {}
            try:
                return json.loads(self.rfile.read(length))
            except Exception:
                return {}

        def _check_auth(self) -> bool:
            return auth.validate_session(self.headers.get("Cookie", ""))

        def _client_ip(self) -> str:
            return self.headers.get("X-Forwarded-For", self.client_address[0]).split(",")[0].strip()

        def _set_session_cookie(self, token: str):
            self.send_header(
                "Set-Cookie",
                f"session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=86400",
            )

        def _clear_session_cookie(self):
            self.send_header(
                "Set-Cookie",
                "session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0",
            )

        # -- Routing --

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path

            # Public endpoints
            if path == "/health":
                return self._respond(200, {"status": "ok", "service": "web"})

            # API endpoints (auth required)
            if path.startswith("/api/"):
                if not self._check_auth():
                    return self._respond(401, {"error": "unauthorized"})
                return self._route_api_get(path, parsed.query)

            # Static files
            return self._serve_static(path)

        def do_POST(self):
            path = urlparse(self.path).path
            body = self._read_body()

            if path == "/api/login":
                return self._handle_login(body)

            if not self._check_auth():
                return self._respond(401, {"error": "unauthorized"})

            if path == "/api/logout":
                return self._handle_logout()

            return self._route_api_post(path, body)

        def do_PUT(self):
            path = urlparse(self.path).path
            body = self._read_body()

            if not self._check_auth():
                return self._respond(401, {"error": "unauthorized"})

            return self._route_api_put(path, body)

        def do_DELETE(self):
            path = urlparse(self.path).path

            if not self._check_auth():
                return self._respond(401, {"error": "unauthorized"})

            return self._route_api_delete(path)

        # -- API GET routes --

        def _route_api_get(self, path: str, query: str):
            if path == "/api/status":
                return self._handle_status()
            if path == "/api/usage":
                return self._respond(200, load_usage())
            if path == "/api/agents":
                return self._respond(200, load_agents())
            if path.startswith("/api/agents/"):
                aid = path.split("/")[3] if len(path.split("/")) > 3 else ""
                return self._handle_agent_get(aid)
            if path == "/api/routines":
                return self._respond(200, load_routines())
            if path.startswith("/api/routines-state"):
                params = parse_qs(query)
                d = params.get("date", [None])[0]
                return self._respond(200, load_routines_state(d))
            if path == "/api/settings":
                return self._respond(200, load_settings())
            return self._respond(404, {"error": "not found"})

        def _route_api_post(self, path: str, body: Dict):
            # Bot controls
            if path == "/api/bot/start":
                ok, msg = bot_start()
                return self._respond(200 if ok else 500, {"ok": ok, "message": msg})
            if path == "/api/bot/stop":
                ok, msg = bot_stop()
                return self._respond(200 if ok else 500, {"ok": ok, "message": msg})
            if path == "/api/bot/restart":
                ok, msg = bot_restart()
                return self._respond(200 if ok else 500, {"ok": ok, "message": msg})

            # Create agent
            if path == "/api/agents":
                ok = save_agent(body)
                return self._respond(200 if ok else 400, {"ok": ok})

            # Create routine: /api/routines/:agent
            parts = path.split("/")
            if len(parts) == 4 and parts[1] == "api" and parts[2] == "routines":
                ok = save_routine(parts[3], body)
                return self._respond(200 if ok else 400, {"ok": ok})

            # Run routine: /api/routines/:agent/:id/run
            if len(parts) == 6 and parts[5] == "run":
                return self._handle_routine_run(parts[4])

            # Stop routine: /api/routines/:agent/:id/stop
            if len(parts) == 6 and parts[5] == "stop":
                return self._handle_routine_stop(parts[4])

            return self._respond(404, {"error": "not found"})

        def _route_api_put(self, path: str, body: Dict):
            parts = path.split("/")

            # Update agent: /api/agents/:id
            if len(parts) == 4 and parts[2] == "agents":
                body["id"] = parts[3]
                ok = save_agent(body)
                return self._respond(200 if ok else 400, {"ok": ok})

            # Update routine: /api/routines/:agent/:id
            if len(parts) == 5 and parts[2] == "routines":
                body["id"] = parts[4]
                ok = save_routine(parts[3], body)
                return self._respond(200 if ok else 400, {"ok": ok})

            # Update settings
            if path == "/api/settings":
                return self._handle_settings_save(body)

            return self._respond(404, {"error": "not found"})

        def _route_api_delete(self, path: str):
            parts = path.split("/")

            # Delete agent: /api/agents/:id
            if len(parts) == 4 and parts[2] == "agents":
                return self._handle_agent_delete(parts[3])

            # Delete routine: /api/routines/:agent/:id
            if len(parts) == 5 and parts[2] == "routines":
                return self._handle_routine_delete(parts[3], parts[4])

            return self._respond(404, {"error": "not found"})

        # -- Handlers --

        def _handle_login(self, body: Dict):
            pin = body.get("pin", "")
            ip = self._client_ip()
            token = auth.check_pin(str(pin), ip)
            if token:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self._set_session_cookie(token)
                resp = json.dumps({"ok": True}).encode()
                self.send_header("Content-Length", len(resp))
                self.end_headers()
                self.wfile.write(resp)
            else:
                self._respond(401, {"ok": False, "error": "Invalid PIN or rate limited"})

        def _handle_logout(self):
            auth.logout(self.headers.get("Cookie", ""))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._clear_session_cookie()
            resp = json.dumps({"ok": True}).encode()
            self.send_header("Content-Length", len(resp))
            self.end_headers()
            self.wfile.write(resp)

        def _handle_status(self):
            status, data = proxy_to_control("GET", "/health")
            if status == 200:
                return self._respond(200, data)
            return self._respond(200, {
                "status": "stopped",
                "uptime_seconds": 0,
                "active_sessions": 0,
                "active_runners": 0,
                "scheduler_alive": False,
            })

        def _handle_agent_get(self, aid: str):
            for agent in load_agents():
                if agent["id"] == aid:
                    return self._respond(200, agent)
            return self._respond(404, {"error": "agent not found"})

        def _handle_agent_delete(self, aid: str):
            if aid == "main":
                return self._respond(400, {"error": "cannot delete main agent"})
            agent_dir = VAULT_DIR / aid
            if not agent_dir.is_dir():
                return self._respond(404, {"error": "agent not found"})
            # Move to Trash via macOS
            try:
                subprocess.run(
                    ["osascript", "-e",
                     f'tell application "Finder" to delete POSIX file "{agent_dir}"'],
                    timeout=10, capture_output=True,
                )
                return self._respond(200, {"ok": True})
            except Exception as e:
                return self._respond(500, {"error": str(e)})

        def _handle_routine_run(self, routine_id: str):
            status, data = proxy_to_control("POST", "/routine/run", {
                "name": routine_id,
                "time_slot": "now",
            })
            return self._respond(status, data)

        def _handle_routine_stop(self, routine_id: str):
            status, data = proxy_to_control("POST", "/routine/stop", {
                "name": routine_id,
            })
            return self._respond(status, data)

        def _handle_routine_delete(self, agent_id: str, routine_id: str):
            filepath = VAULT_DIR / agent_id / "Routines" / f"{routine_id}.md"
            if not filepath.is_file():
                return self._respond(404, {"error": "routine not found"})
            try:
                subprocess.run(
                    ["osascript", "-e",
                     f'tell application "Finder" to delete POSIX file "{filepath}"'],
                    timeout=10, capture_output=True,
                )
                # Also try to delete step dir if pipeline
                step_dir = filepath.parent / routine_id
                if step_dir.is_dir():
                    subprocess.run(
                        ["osascript", "-e",
                         f'tell application "Finder" to delete POSIX file "{step_dir}"'],
                        timeout=10, capture_output=True,
                    )
                return self._respond(200, {"ok": True})
            except Exception as e:
                return self._respond(500, {"error": str(e)})

        def _handle_settings_save(self, body: Dict):
            section = body.get("section", "")
            data = body.get("data", {})
            if section == "bot":
                ok = save_env_file(BOT_ENV_FILE, data)
            elif section == "vault":
                ok = save_env_file(VAULT_ENV_FILE, data)
            else:
                return self._respond(400, {"error": "invalid section"})
            return self._respond(200 if ok else 500, {"ok": ok})

        # -- Static file serving --

        def _serve_static(self, path: str):
            if path == "/" or path == "":
                path = "/index.html"

            # Security: prevent path traversal
            try:
                file_path = (WEB_DIR / path.lstrip("/")).resolve()
                if not str(file_path).startswith(str(WEB_DIR.resolve())):
                    return self._respond(403, {"error": "forbidden"})
            except Exception:
                return self._respond(400, {"error": "bad path"})

            if file_path.is_file():
                ext = file_path.suffix.lower()
                content_type = CONTENT_TYPES.get(ext, "application/octet-stream")
                content = file_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", len(content))
                self.send_header("Cache-Control", "no-cache" if ext in (".html", ".js", ".css") else "max-age=3600")
                self.end_headers()
                self.wfile.write(content)
            else:
                # SPA fallback
                index = WEB_DIR / "index.html"
                if index.is_file():
                    content = index.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", len(content))
                    self.send_header("Cache-Control", "no-cache")
                    self.end_headers()
                    self.wfile.write(content)
                else:
                    self._respond(404, {"error": "not found"})

        def log_message(self, format, *args):
            pass  # Suppress default HTTP logging

    return Handler


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    import argparse
    parser = argparse.ArgumentParser(description="claude-bot web dashboard")
    parser.add_argument("--port", type=int, default=WEB_PORT)
    args = parser.parse_args()

    auth_mgr = AuthManager()
    handler = make_handler(auth_mgr)

    # Periodic session cleanup
    def cleanup_loop():
        while True:
            time.sleep(300)
            auth_mgr.cleanup()

    t = threading.Thread(target=cleanup_loop, daemon=True)
    t.start()

    server = http.server.ThreadingHTTPServer(("0.0.0.0", args.port), handler)
    print(f"claude-bot web dashboard")
    print(f"  URL:  http://localhost:{args.port}")
    print(f"  PIN:  {auth_mgr._pin}")
    print(f"  Web:  {WEB_DIR}")
    print(f"Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()


if __name__ == "__main__":
    main()
