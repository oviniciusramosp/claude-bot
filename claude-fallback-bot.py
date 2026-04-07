#!/usr/bin/env python3
"""
Telegram bot that provides remote access to Claude Code CLI.
Architecture: User <-> Telegram API <-> this script <-> Claude Code CLI (subprocess)
Only uses Python stdlib — no pip dependencies.
"""

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# Load from .env file if env vars not set
_env_file = Path(__file__).resolve().parent / ".env"
if _env_file.is_file() and (not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID):
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            _k, _v = _k.strip(), _v.strip()
            if _k == "TELEGRAM_BOT_TOKEN" and not TELEGRAM_BOT_TOKEN:
                TELEGRAM_BOT_TOKEN = _v
            elif _k == "TELEGRAM_CHAT_ID" and not TELEGRAM_CHAT_ID:
                TELEGRAM_CHAT_ID = _v
            elif _k == "CLAUDE_PATH":
                os.environ.setdefault("CLAUDE_PATH", _v)
            elif _k == "CLAUDE_WORKSPACE":
                os.environ.setdefault("CLAUDE_WORKSPACE", _v)
CLAUDE_PATH = os.environ.get("CLAUDE_PATH", "/opt/homebrew/bin/claude")
CLAUDE_WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", str(Path(__file__).resolve().parent))

DATA_DIR = Path.home() / ".claude-bot"
SESSIONS_FILE = DATA_DIR / "sessions.json"
LOG_FILE = DATA_DIR / "bot.log"

VAULT_DIR = Path(__file__).resolve().parent / "vault"
ROUTINES_DIR = VAULT_DIR / "Routines"
AGENTS_DIR = VAULT_DIR / "Agents"
ROUTINES_STATE_DIR = DATA_DIR / "routines-state"
TEMP_IMAGES_DIR = Path("/tmp/claude-bot-images")

DEFAULT_TIMEOUT = 600
STREAM_EDIT_INTERVAL = 3.0
TYPING_INTERVAL = 4.0
MAX_MESSAGE_LENGTH = 4000

SYSTEM_PROMPT = (
    "You are being accessed via a Telegram bot as a remote fallback. "
    "Keep responses concise when possible. When showing code, prefer short relevant snippets. "
    "Summarize tool execution results briefly. The user cannot see tool calls in real-time — "
    "describe what you are doing. NEVER use tables — always use bullet lists or numbered lists instead. "
    "NEVER break a line in the middle of a sentence or phrase — each sentence must stay on a single line. "
    "Line breaks are only allowed between paragraphs or sections, never within a sentence. "
    "Use emojis to highlight important parts of your responses "
    "(e.g. ✅ for success, ❌ for errors, ⚠️ for warnings, 📁 for files, 🔧 for fixes, "
    "📝 for notes, 🚀 for deployments). "
    f"This project has a knowledge vault at {VAULT_DIR}/. "
    f"Check {VAULT_DIR}/Journal/ for recent context. "
    f"After significant conversations, append a summary to {VAULT_DIR}/Journal/YYYY-MM-DD.md (use today's date). "
    f"Read {VAULT_DIR}/Tooling.md for tool preferences. "
    f"Read {VAULT_DIR}/.env for project credentials when needed. "
    "All vault .md files MUST have YAML frontmatter (title, description, type, created/updated, tags). "
    "Use the description field to scan files before reading them fully. "
    f"Routines are defined in {VAULT_DIR}/Routines/ — each .md has a schedule in frontmatter. "
    "Journal entries are append-only — never overwrite existing content."
)

HELP_TEXT = """🤖 *Claude Code Telegram Bot*

*Comandos disponíveis:*

📋 *Sessões*
• `/new [nome]` — Nova sessão (auto-nome se omitido)
• `/sessions` — Listar sessões
• `/switch <nome>` — Trocar sessão
• `/delete <nome>` — Apagar sessão
• `/clear` — Resetar sessão atual
• `/compact` — Compactar contexto

⚙️ *Modelo*
• `/sonnet` — Usar Sonnet
• `/opus` — Usar Opus
• `/haiku` — Usar Haiku
• `/model` — Escolher modelo (teclado)

🔧 *Controle*
• `/stop` — Cancelar execução atual
• `/status` — Info da sessão e processo
• `/timeout <seg>` — Alterar timeout (padrão 600s)
• `/workspace <path>` — Alterar diretório de trabalho
• `/effort <low|medium|high>` — Nível de esforço de raciocínio
• `/btw <msg>` — Enviar após conclusão atual

📓 *Journal*
• `/important` — Registrar pontos importantes da sessão no diário

🔁 *Rotinas*
• `/routine` — Criar nova rotina (interativo)
• `/routine list` — Listar rotinas de hoje
• `/routine status` — Status de execução das rotinas

🤖 *Agentes*
• `/agent` — Escolher agente (teclado)
• `/agent <nome>` — Trocar para agente
• `/agent new` — Criar novo agente
• `/agent list` — Listar agentes

💬 Qualquer outra mensagem é enviada como prompt ao Claude.
📷 Envie fotos diretamente — o Claude irá analisá-las."""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

DATA_DIR.mkdir(parents=True, exist_ok=True)
ROUTINES_STATE_DIR.mkdir(parents=True, exist_ok=True)
TEMP_IMAGES_DIR.mkdir(parents=True, exist_ok=True)

logger = logging.getLogger("claude-bot")
logger.setLevel(logging.DEBUG)

_fmt = logging.Formatter("[%(asctime)s] %(levelname)-7s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

_fh = RotatingFileHandler(str(LOG_FILE), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(_fmt)
logger.addHandler(_fh)

_sh = logging.StreamHandler(sys.stdout)
_sh.setLevel(logging.INFO)
_sh.setFormatter(_fmt)
logger.addHandler(_sh)

# ---------------------------------------------------------------------------
# Frontmatter parser (stdlib only — no pyyaml)
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> Dict[str, Any]:
    """Parse YAML frontmatter from a markdown file. Handles scalars, flow lists, and one nested block (schedule:)."""
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
    result: Dict[str, Any] = {}
    current_block: Optional[str] = None
    for line in lines[1:end]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Detect indented sub-key (for schedule: block)
        if current_block and line.startswith("  ") and ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if isinstance(result.get(current_block), dict):
                result[current_block][key] = _parse_yaml_value(val)
            continue
        # Top-level key
        if ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                # Start of a block (e.g., schedule:)
                result[key] = {}
                current_block = key
            else:
                result[key] = _parse_yaml_value(val)
                current_block = None
    return result


def _parse_yaml_value(val: str) -> Any:
    """Parse a single YAML value: bool, number, quoted string, flow list, or plain string."""
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    # Flow list: [a, b, c]
    if val.startswith("[") and val.endswith("]"):
        items = val[1:-1].split(",")
        return [_strip_quotes(i.strip()) for i in items if i.strip()]
    # Quoted string
    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    # Try number
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        pass
    return val


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and ((s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")):
        return s[1:-1]
    return s


def get_frontmatter_and_body(filepath: Path) -> tuple:
    """Return (frontmatter_dict, body_text) from a markdown file."""
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return {}, ""
    fm = parse_frontmatter(text)
    # Extract body (everything after second ---)
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end >= 0:
            body = "\n".join(lines[end + 1:]).strip()
            return fm, body
    return fm, text.strip()


# ---------------------------------------------------------------------------
# Routine data structures
# ---------------------------------------------------------------------------

DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass
class RoutineTask:
    name: str
    prompt: str
    model: str
    time_slot: str
    agent: Optional[str] = None


class RoutineStateManager:
    """Tracks daily routine execution state in ~/.claude-bot/routines-state/YYYY-MM-DD.json."""

    def __init__(self) -> None:
        ROUTINES_STATE_DIR.mkdir(parents=True, exist_ok=True)

    def _state_file(self) -> Path:
        return ROUTINES_STATE_DIR / f"{time.strftime('%Y-%m-%d')}.json"

    def _load(self) -> Dict:
        sf = self._state_file()
        if sf.exists():
            try:
                return json.loads(sf.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save(self, data: Dict) -> None:
        sf = self._state_file()
        sf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def is_executed(self, routine_name: str, time_slot: str) -> bool:
        data = self._load()
        entry = data.get(routine_name, {}).get(time_slot, {})
        return entry.get("status") in ("completed", "running", "failed")

    def set_status(self, routine_name: str, time_slot: str, status: str, error: Optional[str] = None) -> None:
        data = self._load()
        if routine_name not in data:
            data[routine_name] = {}
        entry = data[routine_name].get(time_slot, {})
        entry["status"] = status
        if status == "running":
            entry["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        elif status in ("completed", "failed"):
            entry["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if error:
            entry["error"] = error
        data[routine_name][time_slot] = entry
        self._save(data)

    def get_today_state(self) -> Dict:
        return self._load()


class RoutineScheduler:
    """Background thread that checks vault/Routines/ every 60s and enqueues matching routines."""

    def __init__(self, state: RoutineStateManager, enqueue_fn) -> None:
        self.state = state
        self._enqueue = enqueue_fn
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="routine-scheduler")

    def start(self) -> None:
        self._thread.start()
        logger.info("Routine scheduler started.")

    def stop(self) -> None:
        self._stop_event.set()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._check_routines()
            except Exception as exc:
                logger.error("Routine scheduler error: %s", exc, exc_info=True)
            self._stop_event.wait(60)

    def _check_routines(self) -> None:
        if not ROUTINES_DIR.is_dir():
            return
        now_time = time.strftime("%H:%M")
        now_day_idx = time.localtime().tm_wday  # 0=Monday
        today_str = time.strftime("%Y-%m-%d")

        for md_file in sorted(ROUTINES_DIR.glob("*.md")):
            try:
                fm, body = get_frontmatter_and_body(md_file)
                if not fm or not body:
                    continue
                if not fm.get("enabled", False):
                    continue
                schedule = fm.get("schedule", {})
                if not isinstance(schedule, dict):
                    continue
                # Check expiry
                until = schedule.get("until") or fm.get("until")
                if until and str(until) < today_str:
                    continue
                # Check day
                days = schedule.get("days", ["*"])
                if isinstance(days, list) and "*" not in days:
                    if not any(DAY_MAP.get(d.lower().strip(), -1) == now_day_idx for d in days):
                        continue
                # Check time
                times = schedule.get("times", [])
                if not isinstance(times, list):
                    continue
                routine_name = md_file.stem
                model = str(fm.get("model", "sonnet"))
                for t in times:
                    t_str = str(t).strip()
                    if t_str == now_time and not self.state.is_executed(routine_name, t_str):
                        logger.info("Routine matched: %s at %s", routine_name, t_str)
                        self.state.set_status(routine_name, t_str, "running")
                        task = RoutineTask(
                            name=routine_name,
                            prompt=body,
                            model=model,
                            time_slot=t_str,
                            agent=fm.get("agent"),
                        )
                        self._enqueue(task)
            except Exception as exc:
                logger.error("Error checking routine %s: %s", md_file.name, exc)

    def list_today_routines(self) -> List[Dict]:
        """List all routines scheduled for today with their status."""
        if not ROUTINES_DIR.is_dir():
            return []
        now_day_idx = time.localtime().tm_wday
        today_str = time.strftime("%Y-%m-%d")
        state = self.state.get_today_state()
        routines = []

        for md_file in sorted(ROUTINES_DIR.glob("*.md")):
            try:
                fm, _ = get_frontmatter_and_body(md_file)
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
                    if not any(DAY_MAP.get(d.lower().strip(), -1) == now_day_idx for d in days):
                        continue
                times = schedule.get("times", [])
                routine_name = md_file.stem
                for t in times:
                    t_str = str(t).strip()
                    entry = state.get(routine_name, {}).get(t_str, {})
                    status = entry.get("status", "pending")
                    routines.append({
                        "name": routine_name,
                        "title": fm.get("title", routine_name),
                        "time": t_str,
                        "model": fm.get("model", "sonnet"),
                        "status": status,
                        "error": entry.get("error"),
                    })
            except Exception:
                continue

        routines.sort(key=lambda r: r["time"])
        return routines


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

COSTS_FILE = DATA_DIR / "costs.json"


def _track_cost(cost_usd: float) -> None:
    """Append cost to weekly tracker in ~/.claude-bot/costs.json."""
    try:
        data = {}
        if COSTS_FILE.exists():
            data = json.loads(COSTS_FILE.read_text(encoding="utf-8"))
        today = time.strftime("%Y-%m-%d")
        # ISO week key: "2026-W15"
        week_key = time.strftime("%G-W%V")
        if "weeks" not in data:
            data["weeks"] = {}
        week = data["weeks"].setdefault(week_key, {"total": 0.0, "days": {}})
        week["total"] = round(week["total"] + cost_usd, 6)
        day = week["days"].setdefault(today, 0.0)
        week["days"][today] = round(day + cost_usd, 6)
        data["current_week"] = week_key
        # Prune old weeks (keep last 4)
        weeks = sorted(data["weeks"].keys())
        while len(weeks) > 4:
            del data["weeks"][weeks.pop(0)]
        COSTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_weekly_cost() -> dict:
    """Read current week cost data. Returns {week: str, total: float, today: float}."""
    try:
        if not COSTS_FILE.exists():
            return {"week": "", "total": 0.0, "today": 0.0}
        data = json.loads(COSTS_FILE.read_text(encoding="utf-8"))
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


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


@dataclass
class Session:
    name: str
    session_id: Optional[str] = None
    model: str = "sonnet"
    workspace: str = CLAUDE_WORKSPACE
    agent: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    message_count: int = 0
    total_turns: int = 0


class SessionManager:
    def __init__(self) -> None:
        self.sessions: Dict[str, Session] = {}
        self.active_session: Optional[str] = None
        self.cumulative_turns: int = 0
        self._load()

    # -- persistence --

    def _load(self) -> None:
        if not SESSIONS_FILE.exists():
            return
        try:
            data = json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
            _valid_fields = {f.name for f in Session.__dataclass_fields__.values()}
            for name, sdata in data.get("sessions", {}).items():
                filtered = {k: v for k, v in sdata.items() if k in _valid_fields}
                self.sessions[name] = Session(**filtered)
            self.active_session = data.get("active_session")
            self.cumulative_turns = data.get("cumulative_turns", 0)
            logger.info("Loaded %d sessions from disk", len(self.sessions))
        except Exception as exc:
            logger.error("Failed to load sessions: %s", exc)

    def save(self) -> None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "sessions": {n: asdict(s) for n, s in self.sessions.items()},
            "active_session": self.active_session,
            "cumulative_turns": self.cumulative_turns,
        }
        tmp = SESSIONS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(SESSIONS_FILE)

    # -- CRUD --

    def create(self, name: str) -> Session:
        s = Session(name=name)
        self.sessions[name] = s
        self.active_session = name
        self.save()
        return s

    def switch(self, name: str) -> Optional[Session]:
        if name not in self.sessions:
            return None
        self.active_session = name
        self.save()
        return self.sessions[name]

    def delete(self, name: str) -> bool:
        if name not in self.sessions:
            return False
        del self.sessions[name]
        if self.active_session == name:
            self.active_session = next(iter(self.sessions), None)
        self.save()
        return True

    def list(self) -> List[Session]:
        return list(self.sessions.values())

    def get_active(self) -> Optional[Session]:
        if self.active_session and self.active_session in self.sessions:
            return self.sessions[self.active_session]
        return None

    def ensure_active(self) -> Session:
        s = self.get_active()
        if s is None:
            name = time.strftime("%d%b-%H%M").lower()
            s = self.create(name)
        return s


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------

def _translate_error(raw: str) -> str:
    """Convert raw stderr/error text into a friendly Portuguese message."""
    sl = raw.lower()

    if "overloaded" in sl:
        return (
            "❌ *API da Anthropic sobrecarregada*\n"
            "Os servidores da Anthropic estão recebendo muitas requisições agora. "
            "Aguarde alguns minutos e tente de novo."
        )
    if "rate limit" in sl or "429" in sl:
        return (
            "❌ *Limite de requisições atingido (429)*\n"
            "Você enviou muitas requisições em pouco tempo. "
            "Aguarde 1–2 minutos antes de tentar novamente."
        )
    if "authentication" in sl or "401" in sl or "invalid api key" in sl or "x-api-key" in sl:
        return (
            "❌ *Erro de autenticação (401)*\n"
            "A API key do Claude parece inválida ou expirada. "
            "Verifique sua chave em console.anthropic.com."
        )
    if "permission" in sl or "403" in sl:
        return (
            "❌ *Sem permissão para este recurso (403)*\n"
            "Sua conta não tem acesso a este modelo ou endpoint. "
            "Verifique se sua API key tem os planos necessários."
        )
    if "not found" in sl or "404" in sl:
        return (
            "❌ *Modelo ou recurso não encontrado (404)*\n"
            "O modelo solicitado não existe ou foi descontinuado. "
            "Troque o modelo com /sonnet ou /haiku."
        )
    if "timeout" in sl or "timed out" in sl:
        return (
            "❌ *Timeout na requisição*\n"
            "A API da Anthropic demorou demais para responder. "
            "Tente enviar a mensagem novamente."
        )
    if "connection" in sl or "network" in sl or "unreachable" in sl or "name or service not known" in sl:
        return (
            "❌ *Erro de conexão com a API*\n"
            "O Mac mini não conseguiu alcançar a Anthropic. "
            "Verifique a conexão de internet."
        )
    if "context length" in sl or "too many tokens" in sl or "maximum context" in sl:
        return (
            "❌ *Contexto muito longo*\n"
            "A sessão acumulou tokens demais. "
            "Use /compact para compactar ou /clear para resetar."
        )
    if "credit" in sl or "billing" in sl or "quota" in sl or "insufficient" in sl:
        return (
            "❌ *Limite de crédito ou cota atingida*\n"
            "Sua conta Anthropic ficou sem créditos ou atingiu a cota do plano. "
            "Verifique seu billing em console.anthropic.com."
        )
    if "no such file" in sl or "command not found" in sl or "not found" in sl:
        return (
            "❌ *Claude CLI não encontrado*\n"
            f"Caminho configurado: `{CLAUDE_PATH}`\n"
            "O executável do Claude não está nesse caminho. "
            "Verifique com `which claude` no terminal."
        )

    # Nenhum padrão reconhecido — mostra o erro bruto truncado
    snippet = raw[:400].strip()
    return f"❌ *Erro do Claude CLI*\n```\n{snippet}\n```"


# ---------------------------------------------------------------------------
# Claude Runner
# ---------------------------------------------------------------------------


class ClaudeRunner:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.running = False
        self.last_activity: float = 0.0
        self.start_time: float = 0.0
        self.accumulated_text: str = ""
        self.result_text: str = ""
        self.tool_log: List[str] = []  # running log of tool calls
        self.cost_usd: float = 0.0
        self.total_cost_usd: float = 0.0
        self.captured_session_id: Optional[str] = None
        self.error_text: str = ""
        self.stderr_text: str = ""
        self.exit_code: Optional[int] = None
        self.activity_type: str = ""  # "thinking", "tool", "text"
        self._lock = threading.Lock()

    def run(
        self,
        prompt: str,
        model: str = "sonnet",
        session_id: Optional[str] = None,
        workspace: str = CLAUDE_WORKSPACE,
        max_budget: Optional[float] = None,
        effort: Optional[str] = None,
    ) -> None:
        cmd = [
            CLAUDE_PATH,
            "--print",
            "--dangerously-skip-permissions",
            "--model", model,
            "--output-format", "stream-json",
            "--verbose",
        ]
        if session_id:
            cmd += ["--resume", session_id]
        if max_budget:
            cmd += ["--max-budget-usd", str(max_budget)]
        if effort:
            cmd += ["--reasoning-effort", effort]
        cmd += [
            "--append-system-prompt", SYSTEM_PROMPT,
            "-p", prompt,
        ]

        logger.info("Running: %s", " ".join(cmd[:6]) + " ...")
        self.running = True
        self.start_time = time.time()
        self.last_activity = time.time()
        self.accumulated_text = ""
        self.result_text = ""
        self.tool_log = []
        self.cost_usd = 0.0
        self.total_cost_usd = 0.0
        self.captured_session_id = None
        self.error_text = ""
        self.stderr_text = ""
        self.exit_code = None
        self.activity_type = "thinking"

        try:
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=workspace,
                text=True,
                bufsize=1,
            )
            self._read_stream()
        except FileNotFoundError:
            self.error_text = f"❌ Claude CLI não encontrado em {CLAUDE_PATH}"
            logger.error(self.error_text)
        except Exception as exc:
            self.error_text = f"❌ Erro ao executar Claude: {exc}"
            logger.error(self.error_text, exc_info=True)
        finally:
            self._cleanup()

    def _read_stream(self) -> None:
        assert self.process and self.process.stdout
        for raw_line in self.process.stdout:
            self.last_activity = time.time()
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._handle_event(obj)
        # capture stderr — always store, translate if no other error was set
        if self.process.stderr:
            stderr = self.process.stderr.read()
            if stderr and stderr.strip():
                stderr_clean = stderr.strip()
                self.stderr_text = stderr_clean
                logger.warning("Claude stderr: %s", stderr_clean[:500])
                if not self.accumulated_text and not self.result_text and not self.error_text:
                    self.error_text = _translate_error(stderr_clean)

    def _handle_event(self, obj: Dict[str, Any]) -> None:
        etype = obj.get("type", "")
        if etype == "system":
            sid = obj.get("session_id")
            if sid:
                self.captured_session_id = sid
        elif etype == "error":
            # Capture API-level errors from Claude CLI stream (e.g. overloaded, rate limit)
            err = obj.get("error", {})
            err_type = err.get("type", "unknown")
            err_msg = err.get("message", str(err))
            _FRIENDLY = {
                "overloaded_error": "API da Anthropic sobrecarregada — tente novamente em alguns minutos.",
                "rate_limit_error": "Limite de requisições atingido — aguarde antes de tentar novamente.",
                "authentication_error": "Erro de autenticação — verifique sua API key.",
                "permission_error": "Sem permissão para usar este modelo.",
                "not_found_error": "Recurso não encontrado na API.",
                "api_error": "Erro interno da API da Anthropic.",
            }
            friendly = _FRIENDLY.get(err_type, err_msg)
            self.error_text = f"❌ *Erro da API* (`{err_type}`)\n{friendly}"
            logger.error("Stream error event: type=%s msg=%s", err_type, err_msg)
        elif etype == "assistant":
            msg = obj.get("message", {})
            for block in msg.get("content", []):
                btype = block.get("type", "")
                if btype == "text":
                    with self._lock:
                        self.accumulated_text += block["text"]
                        self.activity_type = "text"
                elif btype == "tool_use":
                    tool_name = block.get("name", "?")
                    # Extract a short hint from input
                    inp = block.get("input", {})
                    hint = ""
                    if isinstance(inp, dict):
                        for key in ("command", "path", "file_path", "query", "url", "pattern"):
                            val = inp.get(key)
                            if val and isinstance(val, str):
                                hint = val[:60]
                                break
                    entry = f"🔧 {tool_name}" + (f": `{hint}`" if hint else "")
                    with self._lock:
                        self.tool_log.append(entry)
                        self.activity_type = "tool"
                        self.last_activity = time.time()
        elif etype == "result":
            self.result_text = obj.get("result", "")
            self.cost_usd = obj.get("cost_usd", 0.0)
            self.total_cost_usd = obj.get("total_cost_usd", 0.0)
            sid = obj.get("session_id")
            if sid:
                self.captured_session_id = sid

    def _cleanup(self) -> None:
        self.running = False
        if self.process:
            try:
                self.process.stdout and self.process.stdout.close()
                self.process.stderr and self.process.stderr.close()
                self.process.wait(timeout=5)
                self.exit_code = self.process.returncode
            except Exception:
                self.exit_code = None
            self.process = None
        else:
            self.exit_code = None

    def cancel(self) -> None:
        proc = self.process
        if not proc or not self.running:
            return
        logger.info("Cancelling Claude process PID %d", proc.pid)
        try:
            proc.send_signal(signal.SIGINT)
            time.sleep(3)
            if proc.poll() is None:
                proc.terminate()
                time.sleep(2)
                if proc.poll() is None:
                    proc.kill()
        except Exception as exc:
            logger.error("Error cancelling process: %s", exc)

    def get_snapshot(self) -> str:
        with self._lock:
            if self.accumulated_text:
                # Show last 5 tool calls + text so far
                if self.tool_log:
                    recent_tools = "\n".join(self.tool_log[-5:])
                    return f"{recent_tools}\n\n{self.accumulated_text}"
                return self.accumulated_text
            elif self.tool_log:
                # No text yet — show tool activity
                return "\n".join(self.tool_log[-10:])
            return ""


# ---------------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------------


def load_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    """Load agent definition from vault/Agents/{id}/agent.md. Returns parsed frontmatter + body or None."""
    agent_file = AGENTS_DIR / agent_id / "agent.md"
    if not agent_file.is_file():
        return None
    fm, body = get_frontmatter_and_body(agent_file)
    if not fm:
        return None
    fm["_body"] = body
    fm["_id"] = agent_id
    return fm


def list_agents() -> List[Dict[str, Any]]:
    """List all agents in vault/Agents/."""
    if not AGENTS_DIR.is_dir():
        return []
    agents = []
    for d in sorted(AGENTS_DIR.iterdir()):
        if d.is_dir() and (d / "agent.md").is_file():
            a = load_agent(d.name)
            if a:
                agents.append(a)
    return agents


def get_agent_journal_dir(agent_id: Optional[str], create: bool = False) -> Path:
    """Return the journal directory for an agent, or the global one."""
    if agent_id:
        d = AGENTS_DIR / agent_id / "Journal"
        if create:
            d.mkdir(parents=True, exist_ok=True)
        return d
    return VAULT_DIR / "Journal"


# ---------------------------------------------------------------------------
# Telegram Bot
# ---------------------------------------------------------------------------


class ClaudeTelegramBot:
    def __init__(self) -> None:
        self.token = TELEGRAM_BOT_TOKEN
        self.chat_id = str(TELEGRAM_CHAT_ID)
        self.base_url = f"https://api.telegram.org/bot{self.token}"

        self.sessions = SessionManager()
        self.runner = ClaudeRunner()

        self.timeout_seconds = DEFAULT_TIMEOUT
        self.effort: Optional[str] = None
        self.pending_messages: list = []  # List[str | RoutineTask]
        self._pending_lock = threading.Lock()
        self._update_offset = 0
        self._stop_event = threading.Event()

        self._stream_msg_id: Optional[int] = None
        self._user_msg_id: Optional[int] = None
        self._last_reaction: str = ""
        self._last_edit_time: float = 0.0
        self._last_typing_time: float = 0.0
        self._last_snapshot_len: int = 0

        # Routine scheduler
        self.routine_state = RoutineStateManager()
        self.scheduler = RoutineScheduler(self.routine_state, self._enqueue_routine)
        self.scheduler.start()

        logger.info("Bot initialized. Chat ID: %s", self.chat_id)

    def _enqueue_routine(self, task: RoutineTask) -> None:
        """Called by the scheduler thread to enqueue a routine for execution."""
        with self._pending_lock:
            self.pending_messages.append(task)

    # -- Telegram helpers --

    def tg_request(self, method: str, data: Optional[Dict] = None) -> Optional[Dict]:
        url = f"{self.base_url}/{method}"
        payload = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as exc:
                logger.warning("tg_request %s attempt %d failed: %s", method, attempt + 1, exc)
                if attempt < 2:
                    time.sleep(2)
        logger.error("tg_request %s failed after 3 attempts", method)
        return None

    def send_message(self, text: str, parse_mode: str = "Markdown",
                     reply_markup: Optional[Dict] = None) -> Optional[int]:
        chunks = self._split_message(text)
        last_msg_id = None
        for chunk in chunks:
            data: Dict[str, Any] = {
                "chat_id": self.chat_id,
                "text": chunk,
            }
            if parse_mode:
                data["parse_mode"] = parse_mode
            if reply_markup and chunk == chunks[-1]:
                data["reply_markup"] = reply_markup
            resp = self.tg_request("sendMessage", data)
            if resp and resp.get("ok"):
                last_msg_id = resp["result"]["message_id"]
            else:
                # retry without parse_mode in case of formatting error
                if parse_mode:
                    data.pop("parse_mode", None)
                    resp = self.tg_request("sendMessage", data)
                    if resp and resp.get("ok"):
                        last_msg_id = resp["result"]["message_id"]
        return last_msg_id

    def edit_message(self, message_id: int, text: str, parse_mode: str = "Markdown") -> bool:
        """Try to edit a message. Returns True on success, False on failure."""
        if not text.strip():
            return False
        text = text[:MAX_MESSAGE_LENGTH]
        data: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            data["parse_mode"] = parse_mode
        resp = self.tg_request("editMessageText", data)
        if resp and resp.get("ok"):
            return True
        # Retry without parse_mode (Markdown formatting error)
        if parse_mode:
            data.pop("parse_mode", None)
            resp = self.tg_request("editMessageText", data)
            if resp and resp.get("ok"):
                return True
        return False

    def send_typing(self) -> None:
        self.tg_request("sendChatAction", {"chat_id": self.chat_id, "action": "typing"})

    def set_reaction(self, message_id: int, emoji: str) -> None:
        """Set a reaction emoji on a message. Pass empty string to remove. Fails silently."""
        if not message_id:
            return
        if emoji:
            data = {
                "chat_id": self.chat_id,
                "message_id": message_id,
                "reaction": [{"type": "emoji", "emoji": emoji}],
            }
        else:
            data = {
                "chat_id": self.chat_id,
                "message_id": message_id,
                "reaction": [],
            }
        # Single attempt, fail silently — reactions are non-critical UX
        try:
            url = f"{self.base_url}/setMessageReaction"
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # reactions are best-effort

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.tg_request("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    # -- Message splitting --

    @staticmethod
    def _split_message(text: str) -> List[str]:
        if len(text) <= MAX_MESSAGE_LENGTH:
            return [text]

        chunks: List[str] = []
        remaining = text

        while len(remaining) > MAX_MESSAGE_LENGTH:
            segment = remaining[:MAX_MESSAGE_LENGTH]

            # Don't split inside code blocks
            open_blocks = segment.count("```")
            if open_blocks % 2 != 0:
                # find last ``` before the cut and split there
                idx = segment.rfind("```")
                if idx > 0:
                    segment = remaining[:idx]
                    chunks.append(segment)
                    remaining = remaining[idx:]
                    continue

            # Split at paragraph boundary
            nl_idx = segment.rfind("\n\n")
            if nl_idx > MAX_MESSAGE_LENGTH // 4:
                chunks.append(remaining[:nl_idx])
                remaining = remaining[nl_idx + 2:]
                continue

            # Split at line boundary
            nl_idx = segment.rfind("\n")
            if nl_idx > MAX_MESSAGE_LENGTH // 4:
                chunks.append(remaining[:nl_idx])
                remaining = remaining[nl_idx + 1:]
                continue

            # Hard split
            chunks.append(segment)
            remaining = remaining[MAX_MESSAGE_LENGTH:]

        if remaining:
            chunks.append(remaining)
        return chunks

    # -- Command handlers --

    def cmd_help(self) -> None:
        self.send_message(HELP_TEXT)

    def cmd_status(self) -> None:
        s = self.sessions.get_active()
        lines = ["📊 *Status*\n"]
        if s:
            lines.append(f"• Sessão: `{s.name}`")
            lines.append(f"• Modelo: `{s.model}`")
            lines.append(f"• Mensagens: {s.message_count}")
            lines.append(f"• Turns totais: {s.total_turns}")
            lines.append(f"• Session ID: `{s.session_id or 'nenhum'}`")
            lines.append(f"• Workspace: `{s.workspace}`")
        else:
            lines.append("• Nenhuma sessão ativa")
        lines.append(f"• Timeout: {self.timeout_seconds}s")
        lines.append(f"• Effort: {self.effort or 'padrão'}")
        lines.append(f"• Claude rodando: {'✅ Sim' if self.runner.running else '❌ Não'}")
        if self.runner.running and self.runner.process:
            lines.append(f"• PID: {self.runner.process.pid}")
        lines.append(f"• Turns cumulativos: {self.sessions.cumulative_turns}")
        self.send_message("\n".join(lines))

    def cmd_model_switch(self, model: str) -> None:
        s = self.sessions.ensure_active()
        s.model = model
        self.sessions.save()
        self.send_message(f"✅ Modelo alterado para `{model}`")

    def cmd_model_keyboard(self) -> None:
        markup = {
            "inline_keyboard": [
                [
                    {"text": "Sonnet", "callback_data": "model:sonnet"},
                    {"text": "Opus", "callback_data": "model:opus"},
                    {"text": "Haiku", "callback_data": "model:haiku"},
                ]
            ]
        }
        self.send_message("Escolha o modelo:", reply_markup=markup)

    def cmd_new(self, name: Optional[str]) -> None:
        # Consolidate current session before creating a new one
        self._consolidate_session()
        if not name:
            name = time.strftime("%d%b-%H%M").lower()
        s = self.sessions.create(name)
        self.send_message(f"✅ Sessão `{s.name}` criada e ativada.")

    def cmd_sessions_list(self) -> None:
        items = self.sessions.list()
        if not items:
            self.send_message("Nenhuma sessão encontrada.")
            return
        active = self.sessions.active_session
        lines = ["📋 *Sessões*\n"]
        for s in items:
            marker = " ◀️" if s.name == active else ""
            lines.append(f"• `{s.name}` — {s.model}, {s.message_count} msgs{marker}")
        self.send_message("\n".join(lines))

    def cmd_switch(self, name: str) -> None:
        # Consolidate current session before switching
        self._consolidate_session()
        s = self.sessions.switch(name)
        if s:
            self.send_message(f"✅ Sessão trocada para `{s.name}` (modelo: `{s.model}`)")
        else:
            self.send_message(f"❌ Sessão `{name}` não encontrada.")

    def cmd_delete(self, name: str) -> None:
        if self.sessions.delete(name):
            self.send_message(f"🗑 Sessão `{name}` apagada.")
        else:
            self.send_message(f"❌ Sessão `{name}` não encontrada.")

    def cmd_clear(self) -> None:
        s = self.sessions.get_active()
        if s:
            s.session_id = None
            self.sessions.save()
            self.send_message(f"🔄 Sessão `{s.name}` resetada (session\\_id removido).")
        else:
            self.send_message("❌ Nenhuma sessão ativa.")

    def cmd_compact(self) -> None:
        self._run_claude_prompt("/compact")

    def cmd_stop(self) -> None:
        if self.runner.running:
            self.runner.cancel()
            self.send_message("🛑 Cancelamento enviado.")
        else:
            self.send_message("ℹ️ Nenhum processo rodando.")

    def cmd_timeout(self, val: str) -> None:
        try:
            self.timeout_seconds = int(val)
            self.send_message(f"✅ Timeout alterado para {self.timeout_seconds}s")
        except ValueError:
            self.send_message("❌ Valor inválido. Use: `/timeout 300`")

    def cmd_workspace(self, path: str) -> None:
        p = os.path.expanduser(path)
        if os.path.isdir(p):
            s = self.sessions.ensure_active()
            s.workspace = p
            self.sessions.save()
            self.send_message(f"✅ Workspace: `{p}`")
        else:
            self.send_message(f"❌ Diretório não encontrado: `{p}`")

    def cmd_effort(self, val: str) -> None:
        val = val.lower().strip()
        if val in ("low", "medium", "high"):
            self.effort = val
            self.send_message(f"✅ Effort: `{val}`")
        else:
            self.send_message("❌ Valores aceitos: `low`, `medium`, `high`")

    def cmd_btw(self, text: str) -> None:
        if self.runner.running:
            with self._pending_lock:
                self.pending_messages.append(text)
            self.send_message("📝 Mensagem enfileirada — será enviada quando o Claude terminar.")
        else:
            self._run_claude_prompt(text)

    def _get_journal_path(self) -> str:
        """Return the journal file path for today, using agent journal if active."""
        session = self.sessions.get_active()
        today = time.strftime("%Y-%m-%d")
        journal_dir = get_agent_journal_dir(session.agent if session else None)
        return str(journal_dir / f"{today}.md")

    def cmd_important(self) -> None:
        journal_path = self._get_journal_path()
        prompt = (
            f"Revise as ultimas mensagens desta sessao e registre no Journal "
            f"({journal_path}) os pontos importantes: "
            "decisoes tomadas, informacoes aprendidas, tarefas concluidas ou pendentes. "
            "Use o formato padrao do Journal com frontmatter YAML. "
            "Append-only — nao sobrescreva conteudo existente."
        )
        self._run_claude_prompt(prompt)

    def _consolidate_session(self) -> None:
        """Send a consolidation prompt to the current session before switching.
        Skips if Claude is already running (to avoid consolidating in the wrong session)."""
        if self.runner.running:
            logger.info("Skipping consolidation — Claude is busy")
            return
        session = self.sessions.get_active()
        if not session or not session.session_id or session.message_count == 0:
            return
        journal_path = self._get_journal_path()
        prompt = (
            f"Consolide esta sessao no Journal. Appende um resumo da conversa em "
            f"{journal_path} com os topicos discutidos, decisoes e acoes. "
            "Use o formato padrao do Journal com frontmatter YAML. "
            "Append-only — nao sobrescreva conteudo existente. Depois confirme brevemente."
        )
        self._run_claude_prompt(prompt)

    def cmd_routine(self, arg: str) -> None:
        arg = arg.strip().lower()
        if arg == "list":
            routines = self.scheduler.list_today_routines()
            if not routines:
                self.send_message("📋 Nenhuma rotina agendada para hoje.")
                return
            _icons = {"pending": "⏰", "running": "🔄", "completed": "✅", "failed": "❌"}
            lines = ["📋 *Rotinas de hoje*\n"]
            for r in routines:
                icon = _icons.get(r["status"], "⏰")
                lines.append(f"- {icon} `{r['time']}` *{r['title']}* — {r['model']}")
            self.send_message("\n".join(lines))
        elif arg == "status":
            routines = self.scheduler.list_today_routines()
            if not routines:
                self.send_message("📊 Nenhuma rotina agendada para hoje.")
                return
            _icons = {"pending": "⏰", "running": "🔄", "completed": "✅", "failed": "❌"}
            lines = [f"📊 *Rotinas — {time.strftime('%Y-%m-%d')}*\n"]
            for r in routines:
                icon = _icons.get(r["status"], "⏰")
                extra = ""
                if r["status"] == "failed" and r.get("error"):
                    extra = f" — `{r['error'][:60]}`"
                lines.append(f"- {icon} `{r['time']}` *{r['title']}*{extra}")
            self.send_message("\n".join(lines))
        else:
            # Default: trigger create-routine skill
            prompt = (
                f"Execute a skill de criacao de rotinas. "
                f"Leia {VAULT_DIR}/Skills/create-routine.md para instrucoes. "
                f"Ajude o usuario a criar uma nova rotina em {VAULT_DIR}/Routines/. "
                "Faca as perguntas necessarias sobre: o que a rotina deve fazer, "
                "horarios, dias da semana, modelo, e data limite. "
                "Depois gere o arquivo .md com frontmatter completo e registre no Journal."
            )
            if arg:
                prompt += f"\n\nO usuario disse: {arg}"
            self._run_claude_prompt(prompt)

    # -- Agent commands --

    def cmd_agent(self, arg: str) -> None:
        arg = arg.strip()
        arg_lower = arg.lower()
        if not arg:
            # No argument: show keyboard picker
            self.cmd_agent_keyboard()
            return
        if arg_lower == "list":
            agents = list_agents()
            if not agents:
                self.send_message("🤖 Nenhum agente configurado.\nUse `/agent new` para criar um.")
                return
            session = self.sessions.get_active()
            active_agent = session.agent if session else None
            lines = ["🤖 *Agentes*\n"]
            for a in agents:
                icon = a.get("icon", "🤖")
                marker = " ◀️" if a["_id"] == active_agent else ""
                lines.append(f"- {icon} *{a.get('name', a['_id'])}* — {a.get('description', '')[:60]}{marker}")
            self.send_message("\n".join(lines))
        elif arg_lower in ("new", "create"):
            self._run_agent_create_skill("")
        else:
            # Try to switch to agent by name/id
            self.cmd_agent_switch(arg_lower)

    def _run_agent_create_skill(self, extra: str = "") -> None:
        prompt = (
            f"Execute a skill de criacao de agentes. "
            f"Leia {VAULT_DIR}/Skills/create-agent.md para instrucoes. "
            f"Ajude o usuario a criar um novo agente em {VAULT_DIR}/Agents/. "
            "Faca as perguntas necessarias sobre: nome, personalidade, especializacoes, "
            "modelo padrao, e icone. Depois gere os arquivos e registre no Journal."
        )
        if extra:
            prompt += f"\n\nO usuario disse: {extra}"
        self._run_claude_prompt(prompt)

    def cmd_agent_switch(self, agent_id: str) -> None:
        if agent_id == "none":
            session = self.sessions.ensure_active()
            session.agent = None
            session.workspace = CLAUDE_WORKSPACE
            self.sessions.save()
            self.send_message("🤖 Agente desativado. Usando modo padrão.")
            return
        # Try to find agent by id or name
        agents = list_agents()
        found = None
        for a in agents:
            if a["_id"] == agent_id or a.get("name", "").lower() == agent_id:
                found = a
                break
        if not found:
            self.send_message(f"❌ Agente `{agent_id}` não encontrado.")
            return
        session = self.sessions.ensure_active()
        session.agent = found["_id"]
        session.model = found.get("model", session.model)
        session.workspace = str(AGENTS_DIR / found["_id"])
        self.sessions.save()
        icon = found.get("icon", "🤖")
        name = found.get("name", found["_id"])
        self.send_message(f"{icon} Agente ativado: *{name}* (modelo: `{session.model}`)")

    def cmd_agent_keyboard(self) -> None:
        agents = list_agents()
        if not agents:
            self.send_message("🤖 Nenhum agente configurado.\nUse `/agent new` para criar um.")
            return
        buttons = []
        for a in agents:
            icon = a.get("icon", "🤖")
            name = a.get("name", a["_id"])
            buttons.append({"text": f"{icon} {name}", "callback_data": f"agent:{a['_id']}"})
        # Build rows of 2 buttons each
        rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
        rows.append([{"text": "❌ Nenhum", "callback_data": "agent:none"}])
        markup = {"inline_keyboard": rows}
        self.send_message("Escolha o agente:", reply_markup=markup)

    # -- Telegram file download --

    def _download_telegram_file(self, file_id: str) -> Optional[Path]:
        """Download a file from Telegram and save to temp directory."""
        try:
            resp = self.tg_request("getFile", {"file_id": file_id})
            if not resp or not resp.get("ok"):
                logger.error("getFile failed for file_id=%s", file_id)
                return None
            file_path = resp["result"]["file_path"]

            url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            ext = Path(file_path).suffix or ".jpg"
            filename = f"{int(time.time())}_{Path(file_path).stem}{ext}"
            save_path = TEMP_IMAGES_DIR / filename

            urllib.request.urlretrieve(url, str(save_path))
            logger.info("Downloaded image to %s (%s)", save_path, file_path)
            return save_path
        except Exception as exc:
            logger.error("Failed to download file %s: %s", file_id, exc)
            return None

    # -- Claude execution --

    def _run_claude_prompt(self, prompt: str, _retry: bool = False) -> None:
        if self.runner.running:
            with self._pending_lock:
                self.pending_messages.append(prompt)
            self.send_message("⏳ Mensagem enfileirada — será enviada quando o Claude terminar.")
            return

        session = self.sessions.ensure_active()
        if not _retry:
            session.message_count += 1
            session.total_turns += 1
            self.sessions.cumulative_turns += 1
            self.sessions.save()

        if not _retry:
            self._stream_msg_id = self.send_message("⏳ _Processando..._")
        self._last_edit_time = time.time()
        self._last_typing_time = time.time()
        self._last_snapshot_len = 0

        # Agent context is handled natively by Claude Code via CLAUDE.md
        # in the agent's workspace directory (vault/Agents/{id}/CLAUDE.md).
        # No prompt injection needed.

        # Start runner thread
        runner_thread = threading.Thread(
            target=self.runner.run,
            kwargs={
                "prompt": prompt,
                "model": session.model,
                "session_id": session.session_id,
                "workspace": session.workspace,
                "effort": self.effort,
            },
            daemon=True,
        )
        runner_thread.start()

        # Start watchdog thread
        watchdog_thread = threading.Thread(target=self._watchdog, daemon=True)
        watchdog_thread.start()

        # Stream updates while runner is active
        self._stream_updates(runner_thread)

        # Finalize — pass prompt so expired-session retry works
        self._finalize_response(session, prompt=prompt if not _retry else None)

        # Process queued messages
        self._process_pending()

    def _watchdog(self) -> None:
        """Activity-based timeout: only fires when Claude has been silent.
        Also applies a short no-output timeout (90s) when zero output since start.
        Notifies once when first output is received.
        """
        NO_OUTPUT_TIMEOUT = 90   # kill if Claude never starts responding
        MAX_TOTAL_TIMEOUT = 600  # hard cap — kill regardless of tool activity (10 min)
        _notified_first_output = False

        while self.runner.running:
            time.sleep(5)
            if not self.runner.running:
                break
            now = time.time()
            has_output = self.runner.last_activity > self.runner.start_time

            # Notify once when first output arrives
            if has_output and not _notified_first_output:
                _notified_first_output = True
                if self._stream_msg_id:
                    # already showing "Processando..." message — no extra noise
                    pass

            # Short timeout: no output at all since start
            if not has_output:
                elapsed_start = now - self.runner.start_time
                if elapsed_start > NO_OUTPUT_TIMEOUT:
                    logger.warning("No-output timeout after %.0fs", elapsed_start)
                    self.send_message(f"⏰ Timeout — Claude não produziu nenhum output em {int(elapsed_start)}s. Cancelando...")
                    self.runner.cancel()
                    break
            else:
                # Hard total timeout (prevents infinite tool loops)
                elapsed_total = now - self.runner.start_time
                if elapsed_total > MAX_TOTAL_TIMEOUT:
                    logger.warning("Hard total timeout after %.0fs", elapsed_total)
                    self.send_message(f"⏰ Timeout — Claude rodou por mais de {int(elapsed_total//60)}min sem concluir. Cancelando...")
                    self.runner.cancel()
                    break
                # Normal activity timeout (silence between tool calls)
                elapsed = now - self.runner.last_activity
                if elapsed > self.timeout_seconds:
                    logger.warning("Activity timeout after %.0fs of silence", elapsed)
                    self.send_message(f"⏰ Timeout — Claude ficou {int(elapsed)}s sem atividade. Cancelando...")
                    self.runner.cancel()
                    break

    def _update_reaction(self) -> None:
        """Update the reaction emoji on the user's message based on Claude's current activity."""
        if not self._user_msg_id:
            return
        activity = self.runner.activity_type
        _REACTION_MAP = {
            "thinking": "🤔",
            "tool": "⚡",
            "text": "✍️",
        }
        emoji = _REACTION_MAP.get(activity, "🤔")
        if emoji != self._last_reaction:
            self.set_reaction(self._user_msg_id, emoji)
            self._last_reaction = emoji

    def _stream_updates(self, runner_thread: threading.Thread) -> None:
        _first_output_notified = False
        _checkin_interval = 15.0   # edita a msg de status a cada 15s mesmo sem output novo
        _last_checkin = time.time()
        _last_sent_text = ""  # track what we've already shown to ensure append-only

        while runner_thread.is_alive():
            runner_thread.join(timeout=1.0)
            now = time.time()

            if now - self._last_typing_time >= TYPING_INTERVAL:
                self.send_typing()
                self._last_typing_time = now

            # Update reaction based on activity type
            self._update_reaction()

            if self._stream_msg_id:
                snapshot = self.runner.get_snapshot()
                has_new = len(snapshot) > self._last_snapshot_len
                elapsed = int(now - self.runner.start_time)

                # Notify once when first output arrives
                if has_new and not _first_output_notified:
                    _first_output_notified = True
                    logger.info("First output received from Claude")

                # Update message when there's new content
                if has_new and now - self._last_edit_time >= STREAM_EDIT_INTERVAL:
                    # Append-only: never show less content than before
                    display = snapshot
                    if len(display) > MAX_MESSAGE_LENGTH - 200:
                        display = "...\n" + display[-(MAX_MESSAGE_LENGTH - 200):]
                    display += f"\n\n⏳ _Processando... ({elapsed}s)_"
                    # Only update if display has at least as much content as before
                    if len(snapshot) >= len(_last_sent_text):
                        self.edit_message(self._stream_msg_id, display)
                        self._last_edit_time = now
                        self._last_snapshot_len = len(snapshot)
                        _last_sent_text = snapshot

                # Check-in periódico mesmo sem output novo
                elif now - _last_checkin >= _checkin_interval:
                    _last_checkin = now
                    if snapshot:
                        display = snapshot
                        if len(display) > MAX_MESSAGE_LENGTH - 200:
                            display = "...\n" + display[-(MAX_MESSAGE_LENGTH - 200):]
                        display += f"\n\n⏳ _Processando... ({elapsed}s)_"
                    else:
                        display = f"⏳ _Aguardando resposta do Claude... {elapsed}s_"
                    self.edit_message(self._stream_msg_id, display)

    def _finalize_response(self, session: Session, prompt: Optional[str] = None) -> None:
        # Update session_id
        if self.runner.captured_session_id:
            session.session_id = self.runner.captured_session_id
            self.sessions.save()

        logger.info(
            "Finalizing: result_text=%d chars, accumulated=%d chars, error=%s, stderr=%d chars, exit=%s",
            len(self.runner.result_text),
            len(self.runner.accumulated_text),
            repr(self.runner.error_text[:100]) if self.runner.error_text else "none",
            len(self.runner.stderr_text),
            self.runner.exit_code,
        )

        # Detect expired/invalid session: exit 1, no output, session_id was set
        if (
            self.runner.exit_code == 1
            and not self.runner.result_text
            and not self.runner.accumulated_text
            and not self.runner.error_text
            and not self.runner.stderr_text
            and session.session_id
            and prompt is not None
        ):
            logger.warning("Session ID %s appears expired — retrying without --resume", session.session_id)
            old_id = session.session_id
            session.session_id = None
            self.sessions.save()
            if self._stream_msg_id:
                self.edit_message(self._stream_msg_id, "⚠️ _Sessão expirada. Iniciando nova sessão..._")
            # Retry prompt without session_id
            self._run_claude_prompt(prompt, _retry=True)
            return

        # Build final response
        final_text = self.runner.result_text or self.runner.accumulated_text or self.runner.error_text
        if not final_text:
            exit_code = self.runner.exit_code
            stderr = self.runner.stderr_text

            if stderr:
                # We have stderr — translate it
                final_text = _translate_error(stderr)
                if exit_code and exit_code not in (0, 130):
                    final_text += f"\n_exit code {exit_code}_"
            elif exit_code == 130:
                final_text = "🛑 Execução cancelada pelo usuário."
            elif exit_code == 2:
                final_text = (
                    "❌ *Argumento inválido no Claude CLI*\n"
                    "O comando foi montado com um parâmetro incorreto. "
                    "Reporte para o Vini — pode ser um bug na configuração do bot."
                )
            else:
                final_text = (
                    "⚠️ *Claude não retornou resposta*\n"
                    "Causas prováveis: API da Anthropic sobrecarregada, timeout silencioso ou falha no CLI.\n"
                    "Tente novamente em alguns instantes. Se persistir, use /status."
                )

        # Append cost info and track weekly costs
        if self.runner.cost_usd > 0:
            final_text += f"\n\n💰 Custo: ${self.runner.cost_usd:.4f} (total: ${self.runner.total_cost_usd:.4f})"
            _track_cost(self.runner.cost_usd)

        # Send final (replace the streaming message for short responses, or send new)
        sent = False
        if self._stream_msg_id and len(final_text) <= MAX_MESSAGE_LENGTH:
            sent = self.edit_message(self._stream_msg_id, final_text)

        if not sent:
            # edit failed or response is long — send as new message(s)
            if self._stream_msg_id:
                # Try to clean up the "⏳ Processando..." placeholder
                self.edit_message(self._stream_msg_id, "✅")
            self.send_message(final_text)

        self._stream_msg_id = None

        # Clear reaction on user message
        if self._user_msg_id:
            self.set_reaction(self._user_msg_id, "")
            self._user_msg_id = None
            self._last_reaction = ""

    def _process_pending(self) -> None:
        while True:
            with self._pending_lock:
                if not self.pending_messages:
                    break
                msg = self.pending_messages.pop(0)
            if isinstance(msg, RoutineTask):
                self._execute_routine_task(msg)
            else:
                logger.info("Processing queued message: %s", str(msg)[:80])
                self._run_claude_prompt(msg)

    def _execute_routine_task(self, task: RoutineTask) -> None:
        """Execute a scheduled routine with model/agent/workspace override."""
        logger.info("Executing routine: %s (%s, model=%s, agent=%s)", task.name, task.time_slot, task.model, task.agent)
        session = self.sessions.ensure_active()
        original_model = session.model
        original_agent = session.agent
        original_workspace = session.workspace

        # Temporarily switch model, agent, and workspace
        if task.model and task.model != session.model:
            session.model = task.model
        if task.agent:
            session.agent = task.agent
            session.workspace = str(AGENTS_DIR / task.agent)
        changed = (session.model != original_model or session.agent != original_agent
                    or session.workspace != original_workspace)
        if changed:
            self.sessions.save()

        prompt = f"[ROTINA: {task.name} | {task.time_slot}]\n\n{task.prompt}"

        self.send_message(f"🔄 Executando rotina: *{task.name}* ({task.time_slot})")
        try:
            self._run_claude_prompt(prompt)
            # Check if there was an error
            if self.runner.error_text:
                self.routine_state.set_status(task.name, task.time_slot, "failed", self.runner.error_text[:200])
            else:
                self.routine_state.set_status(task.name, task.time_slot, "completed")
        except Exception as exc:
            logger.error("Routine %s failed: %s", task.name, exc)
            self.routine_state.set_status(task.name, task.time_slot, "failed", str(exc)[:200])

        # Restore original model, agent, and workspace
        session.model = original_model
        session.agent = original_agent
        session.workspace = original_workspace
        if changed:
            self.sessions.save()

    # -- Update processing --

    def _handle_text(self, text: str, user_msg_id: Optional[int] = None) -> None:
        text = text.strip()
        if not text:
            return

        # Commands
        if text.startswith("/"):
            parts = text.split(None, 1)
            cmd = parts[0].lower().split("@")[0]  # strip bot username
            arg = parts[1].strip() if len(parts) > 1 else ""

            handler_map = {
                "/start": lambda: self.cmd_help(),
                "/help": lambda: self.cmd_help(),
                "/status": lambda: self.cmd_status(),
                "/sonnet": lambda: self.cmd_model_switch("sonnet"),
                "/opus": lambda: self.cmd_model_switch("opus"),
                "/haiku": lambda: self.cmd_model_switch("haiku"),
                "/model": lambda: self.cmd_model_keyboard(),
                "/new": lambda: self.cmd_new(arg if arg else None),
                "/sessions": lambda: self.cmd_sessions_list(),
                "/switch": lambda: self.cmd_switch(arg) if arg else self.send_message("❌ Use: `/switch <nome>`"),
                "/delete": lambda: self.cmd_delete(arg) if arg else self.send_message("❌ Use: `/delete <nome>`"),
                "/compact": lambda: self.cmd_compact(),
                "/stop": lambda: self.cmd_stop(),
                "/timeout": lambda: self.cmd_timeout(arg) if arg else self.send_message(f"ℹ️ Timeout atual: {self.timeout_seconds}s"),
                "/workspace": lambda: self.cmd_workspace(arg) if arg else self.send_message("❌ Use: `/workspace <path>`"),
                "/effort": lambda: self.cmd_effort(arg) if arg else self.send_message(f"ℹ️ Effort atual: {self.effort or 'padrão'}"),
                "/btw": lambda: self.cmd_btw(arg) if arg else self.send_message("❌ Use: `/btw <mensagem>`"),
                "/clear": lambda: self.cmd_clear(),
                "/important": lambda: self.cmd_important(),
                "/routine": lambda: self.cmd_routine(arg),
                "/agent": lambda: self.cmd_agent(arg),
            }

            fn = handler_map.get(cmd)
            if fn:
                fn()
            else:
                self.send_message(f"❌ Comando desconhecido: `{cmd}`")
            return

        # Regular text → send to Claude (or queue)
        if self.runner.running:
            with self._pending_lock:
                self.pending_messages.append(text)
            self.send_message("⏳ Mensagem enfileirada — será enviada quando o Claude terminar.")
        else:
            self._user_msg_id = user_msg_id
            self.set_reaction(user_msg_id, "👀")  # eyes: message received
            self._last_reaction = "👀"
            self._run_claude_prompt(text)

    def _handle_callback(self, callback: Dict) -> None:
        cb_id = callback.get("id", "")
        data = callback.get("data", "")

        if data.startswith("model:"):
            model = data.split(":", 1)[1]
            self.cmd_model_switch(model)
            self.answer_callback(cb_id, f"Modelo: {model}")
        elif data.startswith("agent:"):
            agent_id = data.split(":", 1)[1]
            self.cmd_agent_switch(agent_id)
            self.answer_callback(cb_id, f"Agente: {agent_id}")
        else:
            self.answer_callback(cb_id)

    def _process_update(self, update: Dict) -> None:
        # Callback queries (inline keyboards)
        if "callback_query" in update:
            cb = update["callback_query"]
            # Check authorization
            cb_chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
            if cb_chat == self.chat_id:
                self._handle_callback(cb)
            return

        msg = update.get("message")
        if not msg:
            return

        # Authorization
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if chat_id != self.chat_id:
            return

        user_msg_id = msg.get("message_id")

        text = msg.get("text", "")
        if text:
            self._handle_text(text, user_msg_id=user_msg_id)
            return

        # Handle photos sent from Telegram
        photos = msg.get("photo")
        if photos:
            # Telegram sends multiple sizes — last is highest resolution
            best = photos[-1]
            file_id = best["file_id"]
            saved = self._download_telegram_file(file_id)
            if saved:
                caption = msg.get("caption", "Analise esta imagem.")
                prompt = f"[Imagem recebida e salva em: {saved}]\n\n{caption}"
                self._handle_text(prompt, user_msg_id=user_msg_id)
            else:
                self.send_message("❌ Não consegui baixar a imagem.")
            return

        # Handle documents that are images
        doc = msg.get("document")
        if doc:
            mime = doc.get("mime_type", "")
            if mime.startswith("image/"):
                file_id = doc["file_id"]
                saved = self._download_telegram_file(file_id)
                if saved:
                    caption = msg.get("caption", "Analise esta imagem.")
                    prompt = f"[Imagem recebida e salva em: {saved}]\n\n{caption}"
                    self._handle_text(prompt, user_msg_id=user_msg_id)
                else:
                    self.send_message("❌ Não consegui baixar a imagem.")
                return

    # -- Polling loop --

    def _poll_updates(self) -> List[Dict]:
        data = {
            "offset": self._update_offset,
            "timeout": 30,
            "allowed_updates": ["message", "callback_query"],
        }
        resp = self.tg_request("getUpdates", data)
        if resp and resp.get("ok"):
            return resp.get("result", [])
        return []

    def _register_commands(self) -> None:
        """Register bot commands with Telegram so they appear in autocomplete."""
        commands = [
            {"command": "help", "description": "Mostrar comandos disponiveis"},
            {"command": "status", "description": "Info da sessao e processo"},
            {"command": "new", "description": "Nova sessao"},
            {"command": "sessions", "description": "Listar sessoes"},
            {"command": "switch", "description": "Trocar sessao"},
            {"command": "sonnet", "description": "Usar modelo Sonnet"},
            {"command": "opus", "description": "Usar modelo Opus"},
            {"command": "haiku", "description": "Usar modelo Haiku"},
            {"command": "model", "description": "Escolher modelo"},
            {"command": "agent", "description": "Escolher ou criar agente"},
            {"command": "routine", "description": "Criar ou listar rotinas"},
            {"command": "important", "description": "Registrar pontos importantes no diario"},
            {"command": "compact", "description": "Compactar contexto"},
            {"command": "stop", "description": "Cancelar execucao"},
            {"command": "timeout", "description": "Alterar timeout"},
            {"command": "workspace", "description": "Alterar diretorio de trabalho"},
            {"command": "effort", "description": "Nivel de esforco (low/medium/high)"},
            {"command": "clear", "description": "Resetar sessao atual"},
        ]
        self.tg_request("setMyCommands", {"commands": commands})

    def run(self) -> None:
        logger.info("Starting bot polling loop...")
        self._register_commands()
        self.send_message("🤖 Bot iniciado. Use /help para ver comandos.")

        while not self._stop_event.is_set():
            try:
                updates = self._poll_updates()
                for update in updates:
                    uid = update.get("update_id", 0)
                    if uid >= self._update_offset:
                        self._update_offset = uid + 1
                    try:
                        # Handle commands that work while Claude is running
                        # in-line to avoid blocking the polling thread
                        if self.runner.running:
                            msg = update.get("message", {})
                            text = msg.get("text", "").strip()
                            chat_id = str(msg.get("chat", {}).get("id", ""))
                            if chat_id != self.chat_id:
                                continue
                            if text.startswith("/stop"):
                                self.cmd_stop()
                                continue
                            # Non-blocking commands while running
                            parts = text.split(None, 1)
                            cmd = parts[0].lower().split("@")[0] if parts and parts[0].startswith("/") else ""
                            non_blocking = {"/status", "/sessions", "/model", "/sonnet",
                                            "/opus", "/haiku", "/help", "/start", "/timeout",
                                            "/workspace", "/effort"}
                            # /routine list, /routine status, /agent, /agent list are non-blocking
                            if cmd == "/routine" and len(parts) > 1 and parts[1].strip().lower() in ("list", "status"):
                                self._process_update(update)
                                continue
                            if cmd == "/agent" and (len(parts) == 1 or (len(parts) > 1 and parts[1].strip().lower() in ("list", ""))):
                                self._process_update(update)
                                continue
                            if cmd in non_blocking:
                                self._process_update(update)
                                continue
                            if cmd == "/btw":
                                arg = parts[1].strip() if len(parts) > 1 else ""
                                if arg:
                                    self.cmd_btw(arg)
                                else:
                                    self.send_message("❌ Use: `/btw <mensagem>`")
                                continue
                            # Callback queries always processed
                            if "callback_query" in update:
                                self._process_update(update)
                                continue
                            # Any other text → queue
                            if text and not text.startswith("/"):
                                with self._pending_lock:
                                    self.pending_messages.append(text)
                                self.send_message("⏳ Mensagem enfileirada — será enviada quando o Claude terminar.")
                                continue
                            # Unknown command while running
                            if text.startswith("/"):
                                self._process_update(update)
                                continue
                        else:
                            self._process_update(update)
                    except Exception as exc:
                        logger.error("Error handling update %s: %s", update.get("update_id"), exc, exc_info=True)
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt, shutting down.")
                break
            except Exception as exc:
                logger.error("Polling error: %s", exc, exc_info=True)
                time.sleep(5)

        logger.info("Bot stopped.")

    def stop(self) -> None:
        self._stop_event.set()
        if self.runner.running:
            self.runner.cancel()


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--run" in sys.argv or len(sys.argv) == 1:
        bot = ClaudeTelegramBot()
        try:
            bot.run()
        except KeyboardInterrupt:
            bot.stop()
