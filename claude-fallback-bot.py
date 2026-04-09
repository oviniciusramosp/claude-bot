#!/usr/bin/env python3
"""
Telegram bot that provides remote access to Claude Code CLI.
Architecture: User <-> Telegram API <-> this script <-> Claude Code CLI (subprocess)
Only uses Python stdlib — no pip dependencies.
"""

BOT_VERSION = "2.13.1"  # fix: don't double-escape pre-escaped MDv2 sequences from Claude output

import http.server
import json
import logging
import os
import re
import secrets
import signal
import shutil
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
            elif _k == "FFMPEG_PATH":
                os.environ.setdefault("FFMPEG_PATH", _v)
            elif _k == "HEAR_PATH":
                os.environ.setdefault("HEAR_PATH", _v)
            elif _k == "HEAR_LOCALE":
                os.environ.setdefault("HEAR_LOCALE", _v)
            elif _k == "TTS_ENGINE":
                os.environ.setdefault("TTS_ENGINE", _v)
CLAUDE_PATH = os.environ.get("CLAUDE_PATH", "/opt/homebrew/bin/claude")
CLAUDE_WORKSPACE = os.environ.get("CLAUDE_WORKSPACE", str(Path(__file__).resolve().parent / "vault"))

DATA_DIR = Path.home() / ".claude-bot"
SESSIONS_FILE = DATA_DIR / "sessions.json"
CONTEXTS_FILE = DATA_DIR / "contexts.json"
LOG_FILE = DATA_DIR / "bot.log"

VAULT_DIR = Path(__file__).resolve().parent / "vault"
ROUTINES_DIR = VAULT_DIR / "Routines"
AGENTS_DIR = VAULT_DIR / "Agents"
ROUTINES_STATE_DIR = DATA_DIR / "routines-state"
TEMP_IMAGES_DIR = Path("/tmp/claude-bot-images")
TEMP_AUDIO_DIR = Path("/tmp/claude-bot-audio")
HEAR_BIN_DIR = DATA_DIR / "bin"

FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "/opt/homebrew/bin/ffmpeg")
HEAR_PATH = os.environ.get("HEAR_PATH", "")
HEAR_LOCALE = os.environ.get("HEAR_LOCALE", "pt-BR")

# TTS (Text-to-Speech) voice response
TTS_ENGINE = os.environ.get("TTS_ENGINE", "edge-tts")  # "edge-tts" or "say"
TTS_VOICE = os.environ.get("TTS_VOICE", "")  # empty = auto-select by locale
SAY_PATH = "/usr/bin/say"
EDGE_TTS_VOICE_MAP = {
    "pt-BR": "pt-BR-AntonioNeural", "en-US": "en-US-GuyNeural", "es-ES": "es-ES-AlvaroNeural",
    "fr-FR": "fr-FR-HenriNeural", "it-IT": "it-IT-DiegoNeural", "de-DE": "de-DE-ConradNeural",
    "ja-JP": "ja-JP-KeitaNeural", "zh-CN": "zh-CN-YunxiNeural", "en-GB": "en-GB-RyanNeural",
}
SAY_VOICE_MAP = {
    "pt-BR": "Luciana", "en-US": "Samantha", "es-ES": "Mónica",
    "fr-FR": "Thomas", "it-IT": "Alice", "de-DE": "Anna",
    "ja-JP": "Kyoko", "zh-CN": "Tingting", "en-GB": "Daniel",
}
TTS_LOCALE_NAMES = {
    "pt-BR": "Brazilian Portuguese", "en-US": "English", "es-ES": "Spanish",
    "fr-FR": "French", "it-IT": "Italian", "de-DE": "German",
    "ja-JP": "Japanese", "zh-CN": "Chinese", "en-GB": "British English",
}

def _tts_prompt_suffix() -> str:
    lang = TTS_LOCALE_NAMES.get(HEAR_LOCALE, "the user's language")
    return (
        f"\n\nIMPORTANT: The user is listening to your response as audio. "
        f"Respond in {lang}. "
        f"Keep your answer SHORT and conversational — max 3-4 sentences, no code blocks, "
        f"no markdown formatting, no bullet lists, no emojis. Speak naturally as if talking to someone."
    )

DEFAULT_TIMEOUT = 600
CONTROL_PORT = 27182
CONTROL_TOKEN_FILE = DATA_DIR / ".control-token"
PIPELINE_WORKSPACE_MAX_AGE = 86400  # 24 hours in seconds
PIPELINE_ACTIVITY_FILE = DATA_DIR / "pipeline-activity.json"
SESSION_MAX_AGE_DAYS = 60
AUTO_COMPACT_INTERVAL = 25   # auto-compact every N turns in a session
AUTO_ROTATE_THRESHOLD = 80   # start fresh session after N turns
STREAM_EDIT_INTERVAL = 3.0
TYPING_INTERVAL = 4.0
MAX_MESSAGE_LENGTH = 4000
APPROVAL_EXPIRY_SECONDS = 300  # 5 minutes

# Tool name → semantic activity type (for granular status indicators)
_TOOL_ACTIVITY_MAP = {
    "WebSearch": "searching_web", "WebFetch": "searching_web",
    "Grep": "searching_files", "Glob": "searching_files",
    "Read": "reading", "LSP": "searching_files",
    "Bash": "running_script",
    "Write": "editing", "Edit": "editing",
    "NotebookEdit": "editing", "TodoWrite": "editing",
}

# Activity type → Telegram sendChatAction value
_ACTIVITY_CHAT_ACTION = {
    "thinking": "typing", "text": "typing", "editing": "typing",
    "searching_web": "typing",
    "reading": "upload_document",
    "tool": "upload_document",
    "searching_files": "upload_document",
    "running_script": "upload_document",
    "transcribing": "record_voice",
    "synthesizing": "upload_voice",
}

# Activity type → emoji reaction (standard Telegram set only)
_REACTION_MAP = {
    "thinking":        "🤔",
    "text":            "✍️",
    "tool":            "⚡",
    "searching_web":   "👀",
    "searching_files": "👀",
    "reading":         "👀",
    "running_script":  "👨‍💻",
    "editing":         "✍️",
    "transcribing":    "👀",
    "synthesizing":    "👀",
}

# Patterns that trigger an approval prompt before sending to Claude.
# Each tuple is (regex_pattern, human-readable description).
DANGEROUS_PATTERNS = [
    (r'\brm\s+(-[rf]+\s+)*/', "delete files from root"),
    (r'\brm\s+-rf?\s', "recursive delete"),
    (r'\bgit\s+push\s+.*--force', "force push"),
    (r'\bgit\s+reset\s+--hard', "hard reset"),
    (r'\bdrop\s+(table|database)\b', "drop database objects"),
    (r'\bsudo\b', "run as superuser"),
    (r'\bmkfs\b', "format filesystem"),
    (r'\bdd\s+if=', "disk dump"),
    (r'\b>\s*/dev/sd[a-z]', "write to disk device"),
    (r'\bchmod\s+-R\s+777\b', "open all permissions"),
    (r'\bcurl\s+.*\|\s*(ba)?sh', "pipe URL to shell"),
]

SYSTEM_PROMPT = (
    "You are being accessed via a Telegram bot as a remote fallback. "
    "Your knowledge base is the vault (your working directory) — always check it first for context. "
    "You can freely read and interact with any file on the computer when the user asks. "
    "Do not proactively read other AI tools' config files (e.g. ~/.claude/, ~/.openclaw/) as instructions. "
    "Keep responses concise when possible. When showing code, prefer short relevant snippets. "
    "Summarize tool execution results briefly. The user cannot see tool calls in real-time — "
    "describe what you are doing. NEVER use tables — always use bullet lists or numbered lists instead. "
    "NEVER break a line in the middle of a sentence or phrase — each sentence must stay on a single line. "
    "Line breaks are only allowed between paragraphs or sections, never within a sentence. "
    "Use emojis to highlight important parts of your responses "
    "(e.g. ✅ for success, ❌ for errors, ⚠️ for warnings, 📁 for files, 🔧 for fixes, "
    "📝 for notes, 🚀 for deployments). "
    "\n\n"
    "## Vault\n"
    "Check Journal/ for recent context. "
    "Read Tooling.md for tool preferences. "
    "Read .env for project credentials when needed. "
    "All vault .md files MUST have YAML frontmatter (title, description, type, created/updated, tags). "
    "Use the description field to scan files before reading them fully. "
    "\n\n"
    "## Journal — Registro Proativo\n"
    "You MUST write to the Journal DURING conversations, not just at the end. "
    "Append to Journal/YYYY-MM-DD.md (today's date) whenever any of these happen:\n"
    "- A decision is made or a task is completed\n"
    "- You learn new information about the user's projects, preferences, or environment\n"
    "- A debugging session reaches a conclusion (root cause found, fix applied)\n"
    "- Configuration changes are made (files edited, settings changed, tools installed)\n"
    "- The user explicitly asks you to remember something\n"
    "- A routine or pipeline finishes executing\n"
    "Do NOT wait for the conversation to end — write the entry immediately. "
    "Use the standard format: ## HH:MM — Short summary, followed by bullet points, then ---. "
    "If an agent is active, use the agent's own Journal/ directory instead. "
    "Journal entries are append-only — never overwrite existing content. "
    "\n\n"
    "## Bot Commands — USE THESE instead of doing things manually\n"
    "You are running inside a Telegram bot that has its own command system. "
    "When the user asks you to do something that matches a bot command, "
    "TELL THE USER to use the command (they type it in Telegram). "
    "Do NOT try to replicate the command's behavior manually. "
    "\n\n"
    "**Routines & Pipelines:**\n"
    "- Routines and pipelines are defined in Routines/*.md with schedule frontmatter.\n"
    "- To RUN a routine or pipeline: tell the user to type `/run <name>` in Telegram. "
    "The bot's PipelineExecutor handles DAG orchestration, parallel steps, timeouts, retries, "
    "and state tracking — you CANNOT replicate this by reading step files yourself.\n"
    "- To CREATE a routine: read Skills/create-routine.md and follow its steps interactively.\n"
    "- To CREATE a pipeline: read Skills/create-pipeline.md and follow its steps interactively.\n"
    "- To list available routines: tell the user to type `/run` (no args) for a keyboard picker.\n"
    "\n\n"
    "**Skills:**\n"
    "- Skills are defined in Skills/*.md — each has a trigger and step-by-step instructions.\n"
    "- When the user asks for something that matches a skill's trigger, READ the skill file "
    "and FOLLOW its steps interactively (ask questions, create files, update indexes).\n"
    "- Available skills: list Skills/ directory to see all .md files.\n"
    "\n\n"
    "**Agents:**\n"
    "- To CREATE an agent: read Skills/create-agent.md and follow its steps.\n"
    "- To IMPORT an agent: read Skills/import-agent.md and follow its steps.\n"
    "- Agent switching is handled by the bot — tell user to use the agent picker in Telegram.\n"
    "\n\n"
    "**Session commands (inform user):**\n"
    "- `/new [name]` — new session, `/sessions` — list, `/switch <name>` — switch\n"
    "- `/sonnet` `/opus` `/haiku` — switch model\n"
    "- `/stop` — cancel current task, `/compact` — compact context\n"
    "- `/cost` — show token usage and costs\n"
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
• `/cost` — Custo e uso de tokens da sessão
• `/doctor` — Verificar saúde da instalação

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
• `/btw <msg>` — Injetar mensagem ao Claude em execução (nativo)

📓 *Journal*
• `/important` — Registrar pontos importantes da sessão no diário

🔁 *Rotinas*
• `/routine` — Gerenciar rotinas (listar, criar, editar)
• `/run [nome]` — Executar rotina/pipeline manualmente

🤖 *Agentes*
• `/agent` — Gerenciar agentes (trocar, criar, editar, importar)
• `/agent <nome>` — Trocar para agente

⚡ *Skills*
• `/skill` — Gerenciar skills (listar, editar)

🎤 *Áudio*
• `/audio` — Escolher idioma de transcrição
• `/voice [on|off]` — Ativar/desativar respostas por voz
• `#voice` na mensagem — resposta por voz (uma vez só)
• Envie mensagens de voz — serão transcritas e enviadas ao Claude

💬 Qualquer outra mensagem é enviada como prompt ao Claude.
💭 Mensagens enquanto Claude roda são injetadas automaticamente como `/btw`.
📷 Envie fotos diretamente — o Claude irá analisá-las."""

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

DATA_DIR.mkdir(parents=True, exist_ok=True)
ROUTINES_STATE_DIR.mkdir(parents=True, exist_ok=True)
TEMP_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)
HEAR_BIN_DIR.mkdir(parents=True, exist_ok=True)

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
# Pipeline body parser
# ---------------------------------------------------------------------------


def parse_pipeline_body(body: str) -> list:
    """Extract step definitions from a ```pipeline fenced block in the markdown body.

    Returns a list of dicts, each with keys like id, name, model, depends_on, prompt_file, etc.
    """
    # Find the fenced block
    in_block = False
    block_lines: list = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```pipeline"):
            in_block = True
            continue
        if in_block and stripped == "```":
            break
        if in_block:
            block_lines.append(line)

    if not block_lines:
        return []

    steps: list = []
    current: Optional[dict] = None
    for line in block_lines:
        stripped = line.strip()
        if not stripped or stripped == "steps:":
            continue
        # New step item: "  - id: value"
        if stripped.startswith("- "):
            if current is not None:
                steps.append(current)
            current = {}
            stripped = stripped[2:].strip()  # Remove "- " prefix
        if current is None:
            continue
        # Parse "key: value" pair
        if ":" in stripped:
            colon = stripped.index(":")
            key = stripped[:colon].strip()
            val = stripped[colon + 1:].strip()
            if val:
                parsed = _parse_yaml_value(val)
                current[key] = parsed
    if current:
        steps.append(current)
    return steps


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
    minimal_context: bool = False
    voice: bool = False


@dataclass
class PipelineStep:
    id: str
    name: str
    model: str
    prompt: str  # resolved prompt text
    depends_on: list = field(default_factory=list)
    agent: Optional[str] = None
    timeout: int = 1200           # max wall-clock seconds (hard limit)
    inactivity_timeout: int = 300  # max seconds without any output (kills idle steps)
    retry: int = 0
    output_to_telegram: bool = False
    output_type: str = "file"  # "none", "file", "telegram", or vault-relative path
    output_file: Optional[str] = None  # custom output filename (default: {id}.md)
    engine: str = "claude"

    @property
    def resolved_filename(self) -> str:
        """Return the output filename: custom if set, otherwise {id}.md."""
        return self.output_file if self.output_file else f"{self.id}.md"


@dataclass
class PipelineTask:
    name: str
    title: str
    steps: list  # List[PipelineStep]
    model: str
    time_slot: str
    agent: Optional[str] = None
    notify: str = "final"
    minimal_context: bool = False
    voice: bool = False


class RoutineStateManager:
    """Tracks daily routine execution state in ~/.claude-bot/routines-state/YYYY-MM-DD.json."""

    def __init__(self) -> None:
        ROUTINES_STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._cleanup_stale_running()

    def _cleanup_stale_running(self) -> None:
        """On startup, mark any 'running' entries from today as failed (bot was killed mid-run)."""
        sf = ROUTINES_STATE_DIR / f"{time.strftime('%Y-%m-%d')}.json"
        if not sf.exists():
            return
        try:
            data = json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            return
        changed = False
        for routine_name, slots in data.items():
            for slot, entry in slots.items():
                if entry.get("status") == "running":
                    entry["status"] = "failed"
                    entry["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                    entry["error"] = "Bot restarted — process killed before completion"
                    changed = True
                    logger.warning("Startup cleanup: marked %s@%s as failed (was running)", routine_name, slot)
                    # Also cleanup pipeline steps
                    if entry.get("type") == "pipeline" and isinstance(entry.get("steps"), dict):
                        for step_id, step_entry in entry["steps"].items():
                            if step_entry.get("status") == "running":
                                step_entry["status"] = "failed"
                                step_entry["error"] = "Bot restarted"
        if changed:
            sf.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # Clean up stale activity sidecar (no pipelines running after restart)
        if PIPELINE_ACTIVITY_FILE.exists():
            try:
                PIPELINE_ACTIVITY_FILE.unlink()
                logger.info("Startup cleanup: removed stale pipeline-activity.json")
            except Exception:
                pass

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
        with self._lock:
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

    # --- Pipeline-specific state methods ---

    def set_pipeline_status(self, name: str, time_slot: str, status: str,
                            steps_init: Optional[list] = None, error: Optional[str] = None,
                            workspace: Optional[str] = None) -> None:
        """Set pipeline-level status. steps_init can be list of ids or list of dicts with id+output_type."""
        with self._lock:
            data = self._load()
            if name not in data:
                data[name] = {}
            entry = data[name].get(time_slot, {})
            entry["status"] = status
            entry["type"] = "pipeline"
            if workspace:
                entry["workspace"] = workspace
            if status == "running":
                entry["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                entry.pop("finished_at", None)
                entry.pop("error", None)
            elif status in ("completed", "failed"):
                entry["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if error:
                entry["error"] = error
            if steps_init is not None:
                steps = {}
                for item in steps_init:
                    if isinstance(item, dict):
                        steps[item["id"]] = {"status": "pending", "attempt": 0, "output_type": item.get("output_type", "file")}
                    else:
                        steps[item] = {"status": "pending", "attempt": 0}
                entry["steps"] = steps
            data[name][time_slot] = entry
            self._save(data)

    def set_step_status(self, pipeline_name: str, time_slot: str, step_id: str,
                        status: str, error: Optional[str] = None, attempt: Optional[int] = None) -> None:
        """Update a single step within a pipeline run."""
        with self._lock:
            data = self._load()
            entry = data.get(pipeline_name, {}).get(time_slot, {})
            steps = entry.get("steps", {})
            step = steps.get(step_id, {})
            step["status"] = status
            if status == "running":
                step["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            elif status in ("completed", "failed", "skipped"):
                step["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            if error:
                step["error"] = error
            if attempt is not None:
                step["attempt"] = attempt
            steps[step_id] = step
            entry["steps"] = steps
            data.setdefault(pipeline_name, {})[time_slot] = entry
            self._save(data)

    def get_pipeline_steps(self, pipeline_name: str, time_slot: str) -> Dict:
        """Read step-level status for a pipeline run."""
        data = self._load()
        return data.get(pipeline_name, {}).get(time_slot, {}).get("steps", {})


def _cleanup_stale_pipeline_workspaces() -> None:
    """Remove /tmp/claude-pipeline-* directories older than 24 hours."""
    cutoff = time.time() - PIPELINE_WORKSPACE_MAX_AGE
    for p in Path("/tmp").glob("claude-pipeline-*"):
        try:
            if p.is_dir() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                logger.info("Cleaned up stale pipeline workspace: %s", p)
        except OSError:
            pass


class RoutineScheduler:
    """Background thread that checks vault/Routines/ every 60s and enqueues matching routines."""

    def __init__(self, state: RoutineStateManager, enqueue_fn, enqueue_pipeline_fn=None,
                 notify_fn=None) -> None:
        self.state = state
        self._enqueue = enqueue_fn
        self._enqueue_pipeline = enqueue_pipeline_fn
        self._notify_fn = notify_fn  # callable(text) to send Telegram messages
        self._notified_invalid_routines: set = set()  # tracks notified routines per day
        self._notified_date: str = ""  # YYYY-MM-DD for daily reset
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

    def _notify_invalid_routine(self, routine_name: str, errors: list) -> None:
        """Send a one-per-day Telegram notification about invalid routine frontmatter."""
        if not self._notify_fn or routine_name in self._notified_invalid_routines:
            return
        self._notified_invalid_routines.add(routine_name)
        bullet_list = "\n".join(f"- {e}" for e in errors)
        msg = (
            f"\u26a0\ufe0f Rotina `{routine_name}` tem erros no frontmatter:\n"
            f"{bullet_list}\n\n"
            f"Corrija o arquivo `vault/Routines/{routine_name}.md`"
        )
        try:
            self._notify_fn(msg)
        except Exception as exc:
            logger.error("Failed to notify about invalid routine %s: %s", routine_name, exc)

    def _check_routines(self) -> None:
        if not ROUTINES_DIR.is_dir():
            return
        now_time = time.strftime("%H:%M")
        now_day_idx = time.localtime().tm_wday  # 0=Monday
        today_str = time.strftime("%Y-%m-%d")

        # Reset notification tracking at day boundary + daily cleanup
        if self._notified_date != today_str:
            self._notified_invalid_routines.clear()
            self._notified_date = today_str
            _cleanup_stale_pipeline_workspaces()

        for md_file in sorted(ROUTINES_DIR.glob("*.md")):
            try:
                fm, body = get_frontmatter_and_body(md_file)
                if not fm or not body:
                    continue
                # Skip index files (e.g. Routines.md) — they are Obsidian hubs, not routines
                if str(fm.get("type", "")).lower() == "index":
                    continue
                # P2-05: Validate required frontmatter fields
                _missing = [f for f in ("title", "type", "schedule", "model", "enabled")
                            if f not in fm]
                if _missing:
                    logger.warning("Routine %s skipped — missing required fields: %s",
                                   md_file.name, ", ".join(_missing))
                    self._notify_invalid_routine(
                        md_file.stem,
                        [f"Campo `{f}` ausente" for f in _missing],
                    )
                    continue
                if not fm.get("enabled", False):
                    continue
                schedule = fm.get("schedule", {})
                if not isinstance(schedule, dict):
                    logger.warning("Routine %s skipped — 'schedule' must be a mapping", md_file.name)
                    self._notify_invalid_routine(
                        md_file.stem,
                        ["Campo `schedule` deve ser um mapeamento (dict), nao " + type(schedule).__name__],
                    )
                    continue
                if not isinstance(schedule.get("times"), list) or not schedule["times"]:
                    logger.warning("Routine %s skipped — 'schedule.times' must be a non-empty list",
                                   md_file.name)
                    self._notify_invalid_routine(
                        md_file.stem,
                        ["Campo `schedule.times` deve ser uma lista nao-vazia"],
                    )
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
                routine_name = md_file.stem
                model = str(fm.get("model", "sonnet"))
                routine_type = str(fm.get("type", "routine"))
                for t in times:
                    t_str = str(t).strip()
                    if t_str == now_time and not self.state.is_executed(routine_name, t_str):
                        logger.info("Routine matched: %s at %s (type=%s)", routine_name, t_str, routine_type)
                        if routine_type == "pipeline" and self._enqueue_pipeline:
                            self._enqueue_pipeline_from_file(md_file, fm, body, routine_name, model, t_str)
                        else:
                            self.state.set_status(routine_name, t_str, "running")
                            task = RoutineTask(
                                name=routine_name,
                                prompt=body,
                                model=model,
                                time_slot=t_str,
                                agent=fm.get("agent"),
                                minimal_context=bool(fm.get("context") == "minimal"),
                                voice=bool(fm.get("voice", False)),
                            )
                            self._enqueue(task)
            except Exception as exc:
                logger.error("Error checking routine %s: %s", md_file.name, exc)

    def _enqueue_pipeline_from_file(self, md_file: Path, fm: Dict, body: str,
                                     routine_name: str, model: str, t_str: str) -> None:
        """Parse pipeline steps and enqueue as PipelineTask."""
        steps_raw = parse_pipeline_body(body)
        if not steps_raw:
            logger.error("Pipeline %s has no valid steps in ```pipeline block", routine_name)
            return
        # Resolve step prompts
        pipeline_dir = md_file.parent / md_file.stem
        default_agent = fm.get("agent")
        steps = []
        for s in steps_raw:
            step_id = str(s.get("id", ""))
            if not step_id:
                continue
            # Load prompt from file or inline
            prompt_text = ""
            pf = s.get("prompt_file")
            if pf:
                prompt_path = pipeline_dir / str(pf)
                if prompt_path.exists():
                    prompt_text = prompt_path.read_text(encoding="utf-8").strip()
                    # Strip trailing vault wikilink (Obsidian graph metadata, not prompt)
                    if prompt_text:
                        _lines = prompt_text.split("\n")
                        while _lines and re.match(r'^\s*(\(.*\[\[.+\]\].*\)|(?:rotina:\s*)?\[\[.+\]\])\s*$', _lines[-1]):
                            _lines.pop()
                        prompt_text = "\n".join(_lines).rstrip()
                else:
                    logger.warning("Pipeline %s step %s: prompt_file not found: %s", routine_name, step_id, pf)
            if not prompt_text:
                prompt_text = str(s.get("prompt", ""))
            if not prompt_text:
                logger.error("Pipeline %s step %s: no prompt (prompt_file missing or empty, no inline prompt)",
                             routine_name, step_id)
                continue

            depends = s.get("depends_on", [])
            if isinstance(depends, str):
                depends = [depends]

            raw_output = str(s.get("output", "")).strip().lower()
            if raw_output == "telegram":
                out_type = "telegram"
            elif raw_output == "none":
                out_type = "none"
            elif raw_output:
                out_type = s.get("output", "").strip()  # preserve original case for paths
            else:
                out_type = "file"

            steps.append(PipelineStep(
                id=step_id,
                name=str(s.get("name", step_id)),
                model=str(s.get("model", model)),
                prompt=prompt_text,
                depends_on=depends,
                agent=s.get("agent") or default_agent,
                timeout=int(s.get("timeout", 1200)),
                inactivity_timeout=int(s.get("inactivity_timeout", 300)),
                retry=int(s.get("retry", 1)),
                output_to_telegram=(raw_output == "telegram"),
                output_type=out_type,
                output_file=s.get("output_file") or None,
                engine=str(s.get("engine", "claude")),
            ))

        if not steps:
            logger.error("Pipeline %s: no valid steps after parsing", routine_name)
            return

        # P2-04: DAG cycle detection via DFS
        step_ids_set = {s.id for s in steps}
        adj: Dict[str, list] = {s.id: [d for d in s.depends_on if d in step_ids_set] for s in steps}
        WHITE, GRAY, BLACK = 0, 1, 2
        color: Dict[str, int] = {sid: WHITE for sid in step_ids_set}

        def _dfs_cycle(node: str, path: list) -> Optional[list]:
            color[node] = GRAY
            path.append(node)
            for dep in adj[node]:
                if color[dep] == GRAY:
                    cycle_start = path.index(dep)
                    return path[cycle_start:]
                if color[dep] == WHITE:
                    result = _dfs_cycle(dep, path)
                    if result is not None:
                        return result
            path.pop()
            color[node] = BLACK
            return None

        for sid in step_ids_set:
            if color[sid] == WHITE:
                cycle = _dfs_cycle(sid, [])
                if cycle is not None:
                    cycle_str = " -> ".join(cycle + [cycle[0]])
                    logger.error("Pipeline %s has dependency cycle: %s", routine_name, cycle_str)
                    return

        task = PipelineTask(
            name=routine_name,
            title=str(fm.get("title", routine_name)),
            steps=steps,
            model=model,
            time_slot=t_str,
            agent=default_agent,
            notify=str(fm.get("notify", "final")),
            minimal_context=bool(fm.get("context") == "minimal"),
            voice=bool(fm.get("voice", False)),
        )
        steps_info = [{"id": s.id, "output_type": s.output_type} for s in steps]
        self.state.set_pipeline_status(routine_name, t_str, "running", steps_init=steps_info)
        self._enqueue_pipeline(task)

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
                if str(fm.get("type", "")).lower() == "index":
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
                    r_entry = {
                        "name": routine_name,
                        "title": fm.get("title", routine_name),
                        "time": t_str,
                        "model": fm.get("model", "sonnet"),
                        "status": status,
                        "error": entry.get("error"),
                        "type": str(fm.get("type", "routine")),
                    }
                    if entry.get("type") == "pipeline":
                        r_entry["type"] = "pipeline"
                        r_entry["steps"] = entry.get("steps", {})
                    routines.append(r_entry)
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


def _make_session_name(agent: Optional[str], sessions: dict) -> str:
    """Generate a session name: YYYY-MM-DD-HH-MM-{agent}-{n}."""
    now = time.strftime("%Y-%m-%d-%H-%M")
    agent_label = agent if agent else "main"
    prefix = f"{now}-{agent_label}-"
    max_n = 0
    for name in sessions:
        if name.startswith(prefix):
            suffix = name[len(prefix):]
            if suffix.isdigit():
                max_n = max(max_n, int(suffix))
    return f"{prefix}{max_n + 1}"


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
        self._evict_old_sessions()

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

    def _evict_old_sessions(self) -> None:
        """Remove sessions older than SESSION_MAX_AGE_DAYS."""
        cutoff = time.time() - (SESSION_MAX_AGE_DAYS * 86400)
        expired = [name for name, s in self.sessions.items() if s.created_at < cutoff]
        if not expired:
            return
        for name in expired:
            del self.sessions[name]
            logger.info("Evicted expired session: %s", name)
        # Fix active session if it was evicted
        if self.active_session not in self.sessions:
            self.active_session = next(iter(self.sessions), None)
        self.save()
        logger.info("Evicted %d sessions older than %d days", len(expired), SESSION_MAX_AGE_DAYS)

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
        system_prompt: Optional[str] = SYSTEM_PROMPT,
        lightweight: bool = False,  # unused, kept for API compat
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
            cmd += ["--effort", effort]
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]
        cmd += ["-p", prompt]

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
            # Strip CLAUDECODE env var to prevent "nested session" errors.
            # Claude CLI checks this var to detect nesting — we must ensure
            # our subprocesses never inherit it.
            clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                cwd=workspace,
                env=clean_env,
                text=True,
                bufsize=1,
            )
            # Close stdin immediately — prevents Claude CLI from waiting 3s
            # for input. BTW injection falls back to queue when stdin is closed.
            if self.process.stdin:
                self.process.stdin.close()
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
                with self._lock:
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
                elif btype == "thinking":
                    with self._lock:
                        self.activity_type = "thinking"
                        self.last_activity = time.time()
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
                        if len(self.tool_log) > 200:
                            self.tool_log = self.tool_log[-100:]
                        self.activity_type = _TOOL_ACTIVITY_MAP.get(tool_name, "tool")
                        self.last_activity = time.time()
        elif etype == "result":
            self.result_text = obj.get("result", "")
            self.cost_usd = obj.get("cost_usd", 0.0)
            self.total_cost_usd = obj.get("total_cost_usd", 0.0)
            sid = obj.get("session_id")
            if sid:
                with self._lock:
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

    def send_btw(self, message: str) -> bool:
        """Inject a /btw message to the running Claude process via stdin.
        Returns True if the write succeeded, False otherwise."""
        if not self.running or not self.process or not self.process.stdin:
            return False
        try:
            self.process.stdin.write(f"/btw {message}\n")
            self.process.stdin.flush()
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

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


@dataclass
class ThreadContext:
    """Per-topic/chat execution context. Each Telegram topic (or private chat) gets its own."""
    chat_id: str
    thread_id: Optional[int] = None  # None for private chats, int for group topics
    runner: Optional[Any] = field(default=None, repr=False)
    session_name: Optional[str] = None
    pending: list = field(default_factory=list)
    pending_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    stream_msg_id: Optional[int] = None
    user_msg_id: Optional[int] = None
    last_reaction: str = ""
    last_edit_time: float = 0.0
    last_typing_time: float = 0.0
    last_snapshot_len: int = 0
    tts_enabled: bool = False

    def ensure_runner(self) -> "ClaudeRunner":
        if self.runner is None:
            self.runner = ClaudeRunner()
        return self.runner


# ---------------------------------------------------------------------------
# Pipeline Executor — DAG-based multi-step orchestration
# ---------------------------------------------------------------------------


class PipelineExecutor:
    """Executes a pipeline of steps as a DAG with shared workspace and parallel waves."""

    def __init__(self, task: PipelineTask, bot: "ClaudeTelegramBot",
                 ctx: "ThreadContext", state_mgr: RoutineStateManager) -> None:
        self.task = task
        self.bot = bot
        self.ctx = ctx
        self.state = state_mgr
        self.workspace = Path(f"/tmp/claude-pipeline-{task.name}-{secrets.token_hex(6)}")
        self._step_status: Dict[str, str] = {s.id: "pending" for s in task.steps}
        self._step_outputs: Dict[str, str] = {}
        self._step_errors: Dict[str, str] = {}
        self._step_attempts: Dict[str, int] = {s.id: 0 for s in task.steps}
        self._active_runners: Dict[str, ClaudeRunner] = {}
        self._lock = threading.Lock()
        self._activity_lock = threading.Lock()
        self._cancelled = threading.Event()
        self._steps_by_id: Dict[str, PipelineStep] = {s.id: s for s in task.steps}
        self._bot = None  # set by _enqueue_pipeline if available
        self._progress_msg_id: Optional[int] = None  # Telegram message ID for live progress

    def execute(self) -> bool:
        """Run the full pipeline. Returns True if all steps completed successfully."""
        # P2-01: Validate that the vault/workspace path exists before running
        vault = Path(CLAUDE_WORKSPACE)
        if not vault.is_dir():
            logger.error("Pipeline %s aborted: workspace path does not exist: %s", self.task.name, vault)
            self.state.set_pipeline_status(self.task.name, self.task.time_slot, "failed",
                                           error=f"Workspace not found: {vault}")
            return False
        logger.info("Pipeline %s starting (%d steps)", self.task.name, len(self.task.steps))
        self.workspace.mkdir(parents=True, exist_ok=True)
        data_dir = self.workspace / "data"
        data_dir.mkdir(exist_ok=True)

        # Initialize pipeline state with all step ids + output types + workspace path
        steps_info = [{"id": s.id, "output_type": s.output_type} for s in self.task.steps]
        self.state.set_pipeline_status(self.task.name, self.task.time_slot, "running",
                                        steps_init=steps_info, workspace=str(self.workspace))

        # Send live progress message to Telegram
        self._send_progress_message()

        start_time = time.time()
        self._start_time = start_time
        try:
            self._run_dag_loop(data_dir)
        except Exception as exc:
            logger.error("Pipeline %s error: %s", self.task.name, exc)
            self.state.set_pipeline_status(self.task.name, self.task.time_slot, "failed", error=str(exc)[:200])
            self._finalize_progress(success=False, error=str(exc), elapsed=int(time.time() - start_time))
            return False

        # Determine final status
        all_completed = all(s == "completed" for s in self._step_status.values())
        elapsed = int(time.time() - start_time)

        if all_completed:
            self.state.set_pipeline_status(self.task.name, self.task.time_slot, "completed")
            self._finalize_progress(success=True, elapsed=elapsed)
            self._notify_success(elapsed)
            logger.info("Pipeline %s completed in %ds", self.task.name, elapsed)
        else:
            failed_steps = [sid for sid, st in self._step_status.items() if st == "failed"]
            skipped_steps = [sid for sid, st in self._step_status.items() if st == "skipped"]
            parts = []
            if failed_steps:
                parts.append(f"failed: {', '.join(failed_steps)}")
            if skipped_steps:
                parts.append(f"skipped: {', '.join(skipped_steps)}")
            err = f"Steps {'; '.join(parts)}" if parts else "Pipeline did not complete (unknown state)"
            status = "cancelled" if self._cancelled.is_set() else "failed"
            self.state.set_pipeline_status(self.task.name, self.task.time_slot, status, error=err)
            self._finalize_progress(success=False, error=err, elapsed=elapsed)
            logger.warning("Pipeline %s %s: %s", self.task.name, status, err)

        # Workspace kept for 24h (cleaned by _cleanup_stale_pipeline_workspaces on next startup)
        # Remove pipeline activity sidecar
        self._cleanup_activity()
        return all_completed

    def cancel(self) -> None:
        """Cancel the pipeline — kill active runners and skip remaining steps."""
        self._cancelled.set()
        with self._lock:
            for runner in self._active_runners.values():
                if runner.running:
                    runner.cancel()

    # -- Activity sidecar (pipeline-activity.json) --------------------------------

    def _write_step_activity(self, step_id: str, runner: "ClaudeRunner") -> None:
        """Write live activity snapshot for a running step to the sidecar file."""
        with self._activity_lock:
            try:
                data: Dict = {}
                if PIPELINE_ACTIVITY_FILE.exists():
                    try:
                        data = json.loads(PIPELINE_ACTIVITY_FILE.read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        data = {}
                pipeline_entry = data.setdefault(self.task.name, {})
                with runner._lock:
                    activity_type = runner.activity_type or "thinking"
                    # Get last 3 tool entries, strip emoji prefix
                    raw_tools = runner.tool_log[-3:] if runner.tool_log else []
                    tools = [t.replace("🔧 ", "") for t in raw_tools]
                    detail = tools[-1] if tools else ""
                pipeline_entry[step_id] = {
                    "activity_type": activity_type,
                    "detail": detail,
                    "tools": tools,
                    "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                # Atomic write: temp file + rename
                import tempfile as _tf
                tmp = _tf.NamedTemporaryFile(mode="w", dir=str(DATA_DIR),
                                             suffix=".json", delete=False, encoding="utf-8")
                tmp.write(json.dumps(data, ensure_ascii=False))
                tmp.close()
                os.rename(tmp.name, str(PIPELINE_ACTIVITY_FILE))
            except Exception as exc:
                logger.debug("Activity sidecar write failed: %s", exc)

    def _remove_step_activity(self, step_id: str) -> None:
        """Remove a step's entry from the activity sidecar."""
        with self._activity_lock:
            try:
                if not PIPELINE_ACTIVITY_FILE.exists():
                    return
                data = json.loads(PIPELINE_ACTIVITY_FILE.read_text(encoding="utf-8"))
                if self.task.name in data:
                    data[self.task.name].pop(step_id, None)
                    if not data[self.task.name]:
                        data.pop(self.task.name)
                if data:
                    PIPELINE_ACTIVITY_FILE.write_text(
                        json.dumps(data, ensure_ascii=False), encoding="utf-8")
                else:
                    PIPELINE_ACTIVITY_FILE.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Activity sidecar remove failed: %s", exc)

    def _cleanup_activity(self) -> None:
        """Remove entire pipeline entry from activity sidecar."""
        with self._activity_lock:
            try:
                if not PIPELINE_ACTIVITY_FILE.exists():
                    return
                data = json.loads(PIPELINE_ACTIVITY_FILE.read_text(encoding="utf-8"))
                data.pop(self.task.name, None)
                if data:
                    PIPELINE_ACTIVITY_FILE.write_text(
                        json.dumps(data, ensure_ascii=False), encoding="utf-8")
                else:
                    PIPELINE_ACTIVITY_FILE.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Pipeline activity cleanup failed: %s", exc)

    def _run_dag_loop(self, data_dir: Path) -> None:
        """Execute steps in topological waves until all are terminal."""
        terminal = {"completed", "failed", "skipped"}

        while True:
            if self._cancelled.is_set():
                with self._lock:
                    for sid, st in self._step_status.items():
                        if st not in terminal:
                            self._step_status[sid] = "skipped"
                            self.state.set_step_status(self.task.name, self.task.time_slot, sid, "skipped",
                                                       error="Cancelled")
                break

            # Check if all steps are terminal
            with self._lock:
                non_terminal = [sid for sid, st in self._step_status.items() if st not in terminal]
                if not non_terminal:
                    break

            # Find ready steps (pending + all deps completed)
            ready = []
            with self._lock:
                for sid, st in self._step_status.items():
                    if st != "pending":
                        continue
                    step = self._steps_by_id[sid]
                    deps_met = all(self._step_status.get(d) == "completed" for d in step.depends_on)
                    if deps_met:
                        ready.append(step)

            if not ready:
                # Check if anything is still running
                with self._lock:
                    running = any(st == "running" for st in self._step_status.values())
                if running:
                    time.sleep(1)
                    continue
                else:
                    break  # Deadlock or all resolved

            # Launch ready steps in parallel
            threads = []
            for step in ready:
                with self._lock:
                    self._step_status[step.id] = "running"
                t = threading.Thread(target=self._execute_step, args=(step, data_dir),
                                     daemon=True, name=f"pipeline-step-{step.id}")
                threads.append(t)
                t.start()

            # Wait for this wave — check cancellation periodically so we don't
            # block forever on stuck step threads.
            for t in threads:
                while t.is_alive():
                    t.join(timeout=2)
                    if self._cancelled.is_set():
                        break
                if self._cancelled.is_set():
                    # Give running threads a moment to wrap up after runners are killed
                    for t2 in threads:
                        if t2.is_alive():
                            t2.join(timeout=5)
                    break

            # Post-wave: handle retries and cascade skips
            with self._lock:
                for step in self.task.steps:
                    if self._step_status[step.id] == "failed":
                        if self._step_attempts[step.id] <= step.retry:
                            logger.info("Pipeline %s: retrying step %s (attempt %d/%d)",
                                        self.task.name, step.id,
                                        self._step_attempts[step.id], step.retry)
                            self._step_status[step.id] = "pending"
                        else:
                            self._cascade_skip(step.id)

            # Update live progress message after each wave
            self._update_progress()

    def _execute_step(self, step: PipelineStep, data_dir: Path) -> None:
        """Execute a single pipeline step using ClaudeRunner."""
        attempt = self._step_attempts.get(step.id, 0) + 1
        with self._lock:
            self._step_attempts[step.id] = attempt
        self.state.set_step_status(self.task.name, self.task.time_slot, step.id, "running", attempt=attempt)

        logger.info("Pipeline %s: step %s starting (model=%s, attempt=%d)",
                     self.task.name, step.id, step.model, attempt)

        # Build prompt with workspace context
        prompt = self._build_step_prompt(step, data_dir)

        # Create a fresh ClaudeRunner for this step
        runner = ClaudeRunner()
        with self._lock:
            self._active_runners[step.id] = runner

        # Determine workspace for Claude CLI
        ws = str(self.workspace)
        if step.agent:
            agent_dir = AGENTS_DIR / step.agent
            if agent_dir.is_dir():
                ws = str(agent_dir)
        elif self.task.agent:
            agent_dir = AGENTS_DIR / self.task.agent
            if agent_dir.is_dir():
                ws = str(agent_dir)

        try:
            # Run Claude CLI in a separate thread so timeouts can actually fire
            runner_thread = threading.Thread(
                target=runner.run,
                kwargs={"prompt": prompt, "model": step.model, "workspace": ws,
                         "system_prompt": None if self.task.minimal_context else SYSTEM_PROMPT},
                daemon=True, name=f"pipeline-runner-{step.id}")
            runner_thread.start()

            # Wait for completion with dual timeout:
            #   - inactivity_timeout: max seconds without any output from Claude
            #   - timeout: max wall-clock seconds (hard limit)
            hard_deadline = time.time() + step.timeout
            last_activity_write = 0.0
            while runner_thread.is_alive() and time.time() < hard_deadline:
                if self._cancelled.is_set():
                    runner.cancel()
                    break
                # Check inactivity — only trigger if the process itself has exited
                # but the thread is still alive (stuck cleanup), OR if the process
                # is alive but genuinely idle (no stdout AND process not waiting on API).
                # A live process (poll() is None) means the agent is reasoning or
                # waiting for an API response — that's NOT idle.
                idle = time.time() - runner.last_activity
                if idle > step.inactivity_timeout and runner.last_activity > runner.start_time:
                    proc = runner.process
                    if proc and proc.poll() is None:
                        # Process alive = agent reasoning / API call in flight — not idle
                        pass
                    else:
                        runner.cancel()
                        raise TimeoutError(
                            f"Step {step.id} idle for {int(idle)}s (inactivity limit: {step.inactivity_timeout}s)")
                # Write activity sidecar every 3 seconds
                now = time.time()
                if now - last_activity_write >= 3.0:
                    self._write_step_activity(step.id, runner)
                    last_activity_write = now
                time.sleep(1)
            if runner_thread.is_alive() or runner.running:
                elapsed = int(time.time() - runner.start_time)
                runner.cancel()
                runner_thread.join(timeout=10)
                raise TimeoutError(f"Step {step.id} exceeded {step.timeout}s hard limit (ran {elapsed}s)")
            # Ensure thread is fully done
            runner_thread.join(timeout=5)

            # Capture output
            output = runner.result_text or runner.accumulated_text or ""
            if runner.error_text and not output:
                # Detect nested session error — retry with exponential backoff
                is_nested = ("cannot be launched inside another" in runner.error_text.lower() or
                             "nested sessions" in runner.error_text.lower())
                if is_nested:
                    # Force-clean the env var in case it leaked in
                    os.environ.pop("CLAUDECODE", None)
                    for delay in (15, 30):
                        logger.warning("Pipeline %s: step %s hit nested session error, retrying after %ds...",
                                       self.task.name, step.id, delay)
                        time.sleep(delay)
                        if self._cancelled.is_set():
                            raise RuntimeError("Pipeline cancelled during nested session wait")
                        logger.info("Pipeline %s: retrying step %s after nested session wait", self.task.name, step.id)
                        runner2 = ClaudeRunner()
                        with self._lock:
                            self._active_runners[step.id] = runner2
                        runner2.run(prompt, model=step.model, workspace=ws,
                                    system_prompt=None if self.task.minimal_context else SYSTEM_PROMPT)
                        output = runner2.result_text or runner2.accumulated_text or ""
                        if runner2.error_text and not output:
                            is_still_nested = ("cannot be launched inside another" in runner2.error_text.lower() or
                                               "nested sessions" in runner2.error_text.lower())
                            if is_still_nested:
                                continue  # try next delay
                            raise RuntimeError(runner2.error_text)
                        break  # Success on retry
                    else:
                        raise RuntimeError(f"Step {step.id} failed after nested session retries: {runner.error_text}")
                else:
                    raise RuntimeError(runner.error_text)

            # Capture output: prefer file written by Claude, fallback to runner text
            output_file = data_dir / step.resolved_filename
            if not (output_file.exists() and output_file.stat().st_size > 0):
                # Fallback: check if Claude wrote to the agent's data/ dir instead
                # (safety net for when agent workspace differs from pipeline data_dir)
                agent_id = step.agent or self.task.agent
                if agent_id:
                    agent_data_file = AGENTS_DIR / agent_id / "data" / step.resolved_filename
                    if agent_data_file.exists() and agent_data_file.stat().st_size > 0:
                        output = agent_data_file.read_text(encoding="utf-8")
                        output_file.write_text(output, encoding="utf-8")
                        logger.info("Pipeline %s: step %s output recovered from agent workspace %s",
                                    self.task.name, step.id, agent_id)

            if output_file.exists() and output_file.stat().st_size > 0:
                # Claude wrote the file directly — use that
                output = output_file.read_text(encoding="utf-8")
            elif output:
                # Claude returned text but didn't write the file — save it
                output_file.write_text(output, encoding="utf-8")
            else:
                # No output at all — write empty file as marker
                output_file.write_text("", encoding="utf-8")

            with self._lock:
                self._step_outputs[step.id] = output
                self._step_status[step.id] = "completed"
            self.state.set_step_status(self.task.name, self.task.time_slot, step.id, "completed", attempt=attempt)
            logger.info("Pipeline %s: step %s completed", self.task.name, step.id)

        except Exception as exc:
            err_msg = str(exc)[:200]
            with self._lock:
                self._step_errors[step.id] = err_msg
                self._step_status[step.id] = "failed"
            self.state.set_step_status(self.task.name, self.task.time_slot, step.id, "failed",
                                       error=err_msg, attempt=attempt)
            logger.error("Pipeline %s: step %s failed: %s", self.task.name, step.id, err_msg)
        finally:
            with self._lock:
                self._active_runners.pop(step.id, None)
            self._remove_step_activity(step.id)

    def _build_step_prompt(self, step: PipelineStep, data_dir: Path) -> str:
        """Build the full prompt for a step, including workspace context and upstream data."""
        # List available data from completed dependencies (using resolved filenames)
        available = []
        for dep_id in step.depends_on:
            dep_step = self._steps_by_id.get(dep_id)
            dep_fname = dep_step.resolved_filename if dep_step else f"{dep_id}.md"
            dep_file = data_dir / dep_fname
            dep_name = dep_step.name if dep_step else dep_id
            if dep_file.exists():
                available.append(f"- {data_dir}/{dep_fname} ({dep_name} — completed)")

        # Also list any other completed step outputs
        with self._lock:
            for sid, st in self._step_status.items():
                if st == "completed" and sid not in step.depends_on:
                    s_step = self._steps_by_id.get(sid)
                    s_fname = s_step.resolved_filename if s_step else f"{sid}.md"
                    sfile = data_dir / s_fname
                    if sfile.exists():
                        sname = s_step.name if s_step else sid
                        available.append(f"- {data_dir}/{s_fname} ({sname} — completed, not a dependency)")

        # Use absolute paths so Claude writes to the correct location
        # regardless of the CLI's working directory (which may differ when agent is set)
        abs_data_dir = str(data_dir)
        prefix_lines = [
            f"[PIPELINE: {self.task.name} | Step: {step.name} ({step.id})]",
            "",
            f"Seu workspace compartilhado está em {abs_data_dir}/.",
        ]
        if available:
            prefix_lines.append("Dados disponíveis de etapas anteriores:")
            prefix_lines.extend(available)
        prefix_lines.extend([
            "",
            f"Escreva seu output em: {abs_data_dir}/{step.resolved_filename}",
            "",
            "IMPORTANTE: execute a tarefa e escreva APENAS os dados/conteúdo solicitados no arquivo acima. "
            "NÃO escreva confirmações de execução, resumos de status, nem mensagens como '✅ Coleta concluída'. "
            "O arquivo deve conter exclusivamente o output da tarefa no formato especificado.",
            "",
            "---",
            "",
        ])

        return "\n".join(prefix_lines) + step.prompt

    def _cascade_skip(self, failed_id: str) -> None:
        """Recursively mark all transitive dependents of a failed step as skipped."""
        for step in self.task.steps:
            if failed_id in step.depends_on and self._step_status[step.id] == "pending":
                self._step_status[step.id] = "skipped"
                self.state.set_step_status(self.task.name, self.task.time_slot, step.id, "skipped",
                                           error=f"Dependency {failed_id} failed")
                self._cascade_skip(step.id)  # Recurse

    # -- Live progress message in Telegram --

    def _build_progress_text(self, elapsed: int = 0) -> str:
        """Build the progress status text for the live Telegram message."""
        icons = {"completed": "✅", "failed": "❌", "skipped": "⏭", "running": "🔄", "pending": "⏳"}
        lines = [f"🔗 *Pipeline: {self.task.title}*", ""]
        for step in self.task.steps:
            st = self._step_status.get(step.id, "pending")
            icon = icons.get(st, "⏳")
            lines.append(f"{icon} {step.name}")
        total = len(self.task.steps)
        done = sum(1 for st in self._step_status.values() if st == "completed")
        running = sum(1 for st in self._step_status.values() if st == "running")
        elapsed_str = f" — {elapsed // 60}m{elapsed % 60:02d}s" if elapsed else ""
        status = f"\n_{done}/{total} concluídos"
        if running:
            status += f", {running} rodando"
        status += f"{elapsed_str}_"
        lines.append(status)
        return "\n".join(lines)

    def _send_progress_message(self) -> None:
        """Send the initial progress message and store its message_id."""
        try:
            text = self._build_progress_text()
            msg_id = self.bot.send_message(text, chat_id=self.ctx.chat_id, thread_id=self.ctx.thread_id)
            self._progress_msg_id = msg_id
        except Exception as exc:
            logger.debug("Failed to send pipeline progress: %s", exc)

    def _update_progress(self) -> None:
        """Edit the progress message with current step statuses."""
        if not self._progress_msg_id:
            return
        try:
            elapsed = int(time.time() - (self._start_time if hasattr(self, '_start_time') else time.time()))
            text = self._build_progress_text(elapsed)
            self.bot.edit_message(self._progress_msg_id, text)
        except Exception as exc:
            logger.debug("Failed to update pipeline progress: %s", exc)

    def _finalize_progress(self, success: bool, error: str = "", elapsed: int = 0) -> None:
        """Finalize the progress message: delete on success, update with error/cancelled on failure."""
        if not self._progress_msg_id:
            return
        try:
            if success:
                self.bot.delete_message(self._progress_msg_id, chat_id=self.ctx.chat_id)
            else:
                cancelled = self._cancelled.is_set()
                icons = {"completed": "✅", "failed": "❌", "skipped": "⏭", "running": "🔄", "pending": "⏳"}
                if cancelled:
                    header = f"🛑 *Pipeline: {self.task.title}* — CANCELADO"
                else:
                    header = f"❌ *Pipeline: {self.task.title}* — FAILED"
                lines = [header, ""]
                for step in self.task.steps:
                    st = self._step_status.get(step.id, "pending")
                    icon = icons.get(st, "⏳")
                    err_detail = ""
                    if st == "failed" and step.id in self._step_errors:
                        err_detail = f" — `{self._step_errors[step.id][:60]}`"
                    lines.append(f"{icon} {step.name}{err_detail}")
                mins, secs = elapsed // 60, elapsed % 60
                if not cancelled:
                    lines.append(f"\n_Erro: {error[:100]}_")
                lines.append(f"_Duração: {mins}m{secs:02d}s_")
                self.bot.edit_message(self._progress_msg_id, "\n".join(lines))
        except Exception as exc:
            logger.debug("Failed to finalize pipeline progress: %s", exc)

    def _notify_progress(self) -> None:
        """Legacy progress notification (for notify=all mode)."""
        self._update_progress()

    def _notify_success(self, elapsed: int) -> None:
        """Send final success notification based on notify mode."""
        if self.task.notify == "none":
            return

        # Find the step marked output: telegram
        output_text = None
        for step in self.task.steps:
            if step.output_to_telegram and step.id in self._step_outputs:
                output_text = self._step_outputs[step.id]
                break
        # Fallback: last completed step's output
        if output_text is None:
            for step in reversed(self.task.steps):
                if step.id in self._step_outputs:
                    output_text = self._step_outputs[step.id]
                    break

        sent_text = None
        if self.task.notify == "summary" or not output_text:
            mins = elapsed // 60
            secs = elapsed % 60
            sent_text = f"Pipeline *{self.task.title}*: {len(self.task.steps)}/{len(self.task.steps)} steps completed in {mins}m{secs}s"
            try:
                self.bot.send_message(sent_text, chat_id=self.ctx.chat_id, thread_id=self.ctx.thread_id,
                                      disable_notification=True)
            except Exception as exc:
                logger.warning("Pipeline notify_success send failed: %s", exc)
        elif output_text:
            sent_text = output_text
            try:
                self.bot.send_message(sent_text, chat_id=self.ctx.chat_id, thread_id=self.ctx.thread_id,
                                      disable_notification=True)
            except Exception as exc:
                logger.warning("Pipeline notify_success send failed: %s", exc)

        # TTS: send voice message if pipeline has voice: true
        if self.task.voice and sent_text:
            try:
                self.bot._maybe_send_tts(sent_text, self.ctx.chat_id, self.ctx.thread_id)
            except Exception as exc:
                logger.warning("Pipeline TTS failed: %s", exc)

    def _notify_failure(self, error: str) -> None:
        """Always notify on failure, regardless of notify mode. Skip if cancelled (progress msg already updated)."""
        if self._cancelled.is_set():
            return  # Progress message already shows CANCELADO
        icons = {"completed": "✅", "failed": "❌", "skipped": "⏭", "running": "🔄", "pending": "⏰"}
        step_lines = []
        for step in self.task.steps:
            st = self._step_status.get(step.id, "pending")
            icon = icons.get(st, "⏰")
            step_lines.append(f"{icon} {step.name}")
        steps_summary = ", ".join(step_lines)
        msg = (f"Pipeline *{self.task.title}* FAILED\n"
               f"Error: `{error[:100]}`\n"
               f"Steps: {steps_summary}")
        try:
            self.bot.send_message(msg, chat_id=self.ctx.chat_id, thread_id=self.ctx.thread_id)
        except Exception as exc:
            logger.error("Pipeline notify_failure send failed: %s", exc)


class ClaudeTelegramBot:
    def __init__(self) -> None:
        self.token = TELEGRAM_BOT_TOKEN
        # Support comma-separated chat IDs (private + group)
        self.authorized_ids: set = set()
        for cid in str(TELEGRAM_CHAT_ID).split(","):
            cid = cid.strip()
            if cid:
                self.authorized_ids.add(cid)
        self.base_url = f"https://api.telegram.org/bot{self.token}"

        self.sessions = SessionManager()
        self.timeout_seconds = DEFAULT_TIMEOUT
        self.effort: Optional[str] = None
        self._update_offset = self._load_offset()
        self._stop_event = threading.Event()

        # Thread contexts: keyed by (chat_id, thread_id)
        self._contexts: Dict[tuple, ThreadContext] = {}
        self._contexts_lock = threading.RLock()
        self._load_contexts()

        # Active context (set per-message in the polling loop)
        self._ctx: Optional[ThreadContext] = None

        # Routine scheduler
        self.routine_state = RoutineStateManager()
        _cleanup_stale_pipeline_workspaces()
        self.scheduler = RoutineScheduler(
            self.routine_state, self._enqueue_routine, self._enqueue_pipeline,
            notify_fn=self.send_message,
        )
        self.scheduler.start()

        # Tracks active routine/pipeline contexts for HTTP stop requests
        self._routine_contexts: Dict[str, "ThreadContext"] = {}
        self._routine_contexts_lock = threading.Lock()
        self._active_pipelines: Dict[str, PipelineExecutor] = {}
        self._active_pipelines_lock = threading.Lock()

        self._start_time = time.time()
        self._start_control_server()

        # Pending dangerous-prompt approvals: {callback_id: {prompt, chat_id, thread_id, user_msg_id, ts}}
        self._pending_approvals: Dict[str, dict] = {}
        self._voice_picks: Dict[str, dict] = {}  # voice/text picker during transcription

        # Voice transcription tools
        self._voice_tools = self._check_voice_tools()
        if self._voice_tools["can_transcribe"]:
            logger.info("Voice transcription: enabled (ffmpeg=%s, hear=%s)",
                        self._voice_tools["ffmpeg"], self._voice_tools["hear"])
        else:
            logger.warning("Voice transcription: disabled (ffmpeg=%s, hear=%s)",
                           self._voice_tools.get("ffmpeg", "not found"),
                           self._voice_tools.get("hear", "not found"))

        # TTS synthesis tools
        self._tts_tools = self._check_tts_tools()
        if self._tts_tools["can_synthesize"]:
            logger.info("TTS synthesis: enabled (engine=%s, edge-tts=%s, say=%s, ffmpeg=%s)",
                        TTS_ENGINE,
                        self._tts_tools.get("edge_tts", "not found"),
                        self._tts_tools["say"], self._tts_tools["ffmpeg"])
        else:
            logger.warning("TTS synthesis: disabled (edge-tts=%s, say=%s, ffmpeg=%s)",
                           self._tts_tools.get("edge_tts", "not found"),
                           self._tts_tools.get("say", "not found"),
                           self._tts_tools.get("ffmpeg", "not found"))

        logger.info("Bot initialized. Authorized IDs: %s", self.authorized_ids)

    def _load_offset(self) -> int:
        """Load last persisted Telegram update offset from disk."""
        f = DATA_DIR / "telegram_offset.json"
        try:
            return json.loads(f.read_text()).get("offset", 0)
        except Exception:
            return 0

    def _save_offset(self, offset: int) -> None:
        """Persist Telegram update offset so restarts don't reprocess messages."""
        f = DATA_DIR / "telegram_offset.json"
        try:
            f.write_text(json.dumps({"offset": offset}))
        except Exception as exc:
            logger.warning("Failed to persist telegram offset: %s", exc)

    def _load_contexts(self) -> None:
        """Restore context→session mappings from disk."""
        if not CONTEXTS_FILE.exists():
            return
        try:
            data = json.loads(CONTEXTS_FILE.read_text(encoding="utf-8"))
            for entry in data.get("contexts", []):
                cid = entry.get("chat_id", "")
                tid = entry.get("thread_id")
                sname = entry.get("session_name")
                if cid and sname:
                    ctx = ThreadContext(chat_id=cid, thread_id=tid)
                    ctx.session_name = sname
                    ctx.tts_enabled = entry.get("tts_enabled", False)
                    self._contexts[(cid, tid)] = ctx
            logger.info("Loaded %d contexts from disk", len(self._contexts))
        except Exception as exc:
            logger.error("Failed to load contexts: %s", exc)

    def _save_contexts(self) -> None:
        """Persist context→session mappings to disk. Must NOT acquire _contexts_lock (caller may hold it)."""
        try:
            entries = []
            # Iterate without lock — called from within _get_context which holds the lock
            for (cid, tid), ctx in list(self._contexts.items()):
                entries.append({
                    "chat_id": cid,
                    "thread_id": tid,
                    "session_name": ctx.session_name,
                    "tts_enabled": ctx.tts_enabled,
                })
            data = {"contexts": entries}
            tmp = CONTEXTS_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            tmp.replace(CONTEXTS_FILE)
        except Exception as exc:
            logger.error("Failed to save contexts: %s", exc)

    def _get_context(self, chat_id: str, thread_id: Optional[int] = None) -> ThreadContext:
        """Get or create a ThreadContext for a chat/topic pair."""
        key = (chat_id, thread_id)
        with self._contexts_lock:
            if key not in self._contexts:
                ctx = ThreadContext(chat_id=chat_id, thread_id=thread_id)
                # Auto-create session for this context
                name = _make_session_name(None, self.sessions.sessions)
                if name not in self.sessions.sessions:
                    self.sessions.create(name)
                ctx.session_name = name
                self._contexts[key] = ctx
                self._save_contexts()
            return self._contexts[key]

    def _is_authorized(self, chat_id: str) -> bool:
        return chat_id in self.authorized_ids

    def _authorize_chat(self, chat_id: str) -> None:
        """Dynamically authorize a new chat ID (e.g., a group the bot was added to)."""
        self.authorized_ids.add(chat_id)
        # Persist to .env
        try:
            env_file = Path(__file__).resolve().parent / ".env"
            if env_file.is_file():
                content = env_file.read_text()
                lines = content.splitlines()
                new_lines = []
                found = False
                for line in lines:
                    if line.startswith("TELEGRAM_CHAT_ID="):
                        current = line.split("=", 1)[1].strip()
                        ids = {i.strip() for i in current.split(",") if i.strip()}
                        ids.add(chat_id)
                        new_lines.append(f"TELEGRAM_CHAT_ID={','.join(sorted(ids))}")
                        found = True
                    else:
                        new_lines.append(line)
                if not found:
                    new_lines.append(f"TELEGRAM_CHAT_ID={chat_id}")
                env_file.write_text("\n".join(new_lines) + "\n")
            logger.info("Auto-authorized chat ID: %s", chat_id)
        except Exception as exc:
            logger.error("Failed to persist authorized chat: %s", exc)

    def _find_context_for_routine(self, task: "RoutineTask") -> "ThreadContext":
        """Find the correct Telegram context for a routine based on its agent assignment."""
        if task.agent:
            # Priority 1: agent has a dedicated chat_id in its agent.md frontmatter
            agent_def = load_agent(task.agent)
            if agent_def:
                agent_chat_id = agent_def.get("chat_id") or agent_def.get("telegram_chat_id")
                agent_thread_id = agent_def.get("thread_id") or agent_def.get("telegram_thread_id")
                if agent_chat_id:
                    return self._get_context(str(agent_chat_id), str(agent_thread_id) if agent_thread_id else None)

            # Priority 2: find active session bound to this agent
            with self._contexts_lock:
                for ctx in self._contexts.values():
                    if ctx.session_name:
                        session = self.sessions.sessions.get(ctx.session_name)
                        if session and session.agent == task.agent:
                            return ctx

        # Fallback: prefer private chat (positive chat_id, no thread)
        with self._contexts_lock:
            for ctx in self._contexts.values():
                if ctx.thread_id is None and ctx.chat_id and not ctx.chat_id.startswith("-"):
                    return ctx
            # Fall back to any context without a thread (e.g. group main chat)
            for ctx in self._contexts.values():
                if ctx.thread_id is None:
                    return ctx
        # Last resort: create/get the default chat from env
        default_chat = str(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else "0"
        return self._get_context(default_chat, None)

    def _make_dedicated_context(self, base_ctx: "ThreadContext") -> "ThreadContext":
        """Create a dedicated ThreadContext for routine/pipeline execution.

        Uses the same chat_id/thread_id as the base context (so Telegram messages
        go to the right place) but with its own independent runner, allowing
        concurrent execution with interactive sessions.
        """
        return ThreadContext(chat_id=base_ctx.chat_id, thread_id=base_ctx.thread_id)

    def _enqueue_routine(self, task: RoutineTask) -> None:
        """Called by the scheduler thread to enqueue a routine for execution."""
        base_ctx = self._find_context_for_routine(task)
        # Dedicated context so routine runs concurrently with interactive sessions
        ctx = self._make_dedicated_context(base_ctx)

        def _run_routine() -> None:
            with self._routine_contexts_lock:
                self._routine_contexts[task.name] = ctx
            try:
                self._ctx = ctx
                self._execute_routine_task(task)
            except Exception as exc:
                logger.error("Routine %s crashed: %s", task.name, exc, exc_info=True)
                self.routine_state.set_status(task.name, task.time_slot, "failed", str(exc)[:200])
                try:
                    self.send_message(f"❌ Rotina *{task.name}* crashed: `{exc}`")
                except Exception:
                    pass
            finally:
                with self._routine_contexts_lock:
                    self._routine_contexts.pop(task.name, None)

        threading.Thread(target=_run_routine, daemon=True, name=f"routine-{task.name}").start()

    def _enqueue_pipeline(self, task: PipelineTask) -> None:
        """Called by the scheduler thread to enqueue a pipeline for execution."""
        # Guard: prevent duplicate pipeline executions
        with self._active_pipelines_lock:
            if task.name in self._active_pipelines:
                logger.warning("Pipeline %s already running, skipping duplicate enqueue", task.name)
                return
        # Use a dummy RoutineTask to find context (reuses same routing logic)
        dummy = RoutineTask(name=task.name, prompt="", model=task.model,
                            time_slot=task.time_slot, agent=task.agent)
        base_ctx = self._find_context_for_routine(dummy)
        # Dedicated context so pipeline runs concurrently with interactive sessions
        ctx = self._make_dedicated_context(base_ctx)

        def _run_pipeline() -> None:
            executor = PipelineExecutor(task, self, ctx, self.routine_state)
            executor._bot = self
            with self._active_pipelines_lock:
                self._active_pipelines[task.name] = executor
            try:
                self._ctx = ctx
                executor.execute()
            except Exception as exc:
                logger.error("Pipeline %s crashed: %s", task.name, exc, exc_info=True)
                self.routine_state.set_status(task.name, task.time_slot, "failed", str(exc)[:200])
                try:
                    self.send_message(f"❌ Pipeline *{task.name}* crashed: `{exc}`")
                except Exception:
                    pass
            finally:
                with self._active_pipelines_lock:
                    self._active_pipelines.pop(task.name, None)

        threading.Thread(target=_run_pipeline, daemon=True, name=f"pipeline-{task.name}").start()

    # -- Telegram helpers --

    def tg_request(self, method: str, data: Optional[Dict] = None,
                   timeout: int = 15) -> Optional[Dict]:
        url = f"{self.base_url}/{method}"
        payload = json.dumps(data or {}).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                retry_after = 2
                try:
                    err_body = json.loads(exc.read().decode("utf-8"))
                    retry_after = err_body.get("parameters", {}).get("retry_after", retry_after)
                except Exception:
                    pass
                logger.warning("tg_request %s attempt %d HTTP %s: %s (retry_after=%s)",
                               method, attempt + 1, exc.code, exc.reason, retry_after)
                if attempt < 2:
                    time.sleep(min(retry_after, 30))
            except Exception as exc:
                logger.warning("tg_request %s attempt %d failed: %s", method, attempt + 1, exc)
                if attempt < 2:
                    time.sleep(2)
        logger.error("tg_request %s failed after 3 attempts", method)
        return None

    def _tg_upload_file(self, method: str, file_path: Path, file_field: str = "voice",
                        data: Optional[Dict] = None) -> Optional[Dict]:
        """Upload a file to Telegram API using multipart/form-data (stdlib only)."""
        url = f"{self.base_url}/{method}"
        boundary = secrets.token_hex(16)
        body_parts: list = []

        # Text fields
        for key, value in (data or {}).items():
            body_parts.append(
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                f"{value}\r\n".encode("utf-8")
            )

        # File field
        _mime_map = {".ogg": "audio/ogg", ".md": "text/markdown", ".txt": "text/plain"}
        mime = _mime_map.get(file_path.suffix, "application/octet-stream")
        file_data = file_path.read_bytes()
        body_parts.append(
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n".encode("utf-8")
        )
        body_parts.append(file_data)
        body_parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))

        payload = b"".join(body_parts)
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                retry_after = 2
                try:
                    err_body = json.loads(exc.read().decode("utf-8"))
                    retry_after = err_body.get("parameters", {}).get("retry_after", retry_after)
                except Exception:
                    pass
                logger.warning("_tg_upload_file %s attempt %d HTTP %s (retry_after=%s)",
                               method, attempt + 1, exc.code, retry_after)
                if attempt < 2:
                    time.sleep(min(retry_after, 30))
            except Exception as exc:
                logger.warning("_tg_upload_file %s attempt %d failed: %s", method, attempt + 1, exc)
                if attempt < 2:
                    time.sleep(2)
        logger.error("_tg_upload_file %s failed after 3 attempts", method)
        return None

    # Large output threshold for sending as document instead of chunked messages
    DOCUMENT_THRESHOLD = 8000

    def _send_as_document(self, text: str, filename: str = "response.md",
                          caption: str = "",
                          chat_id: Optional[str] = None,
                          thread_id: Optional[str] = None,
                          reply_to_message_id: Optional[int] = None) -> Optional[int]:
        """Send large text as a .md document attachment with optional caption."""
        import tempfile
        chat_id = chat_id or self._chat_id
        thread_id = thread_id or (self._ctx.thread_id if self._ctx else None)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, encoding='utf-8') as f:
            f.write(text)
            tmp_path = Path(f.name)

        try:
            # Rename to desired filename
            target = tmp_path.parent / filename
            tmp_path.rename(target)

            data: Dict[str, str] = {"chat_id": chat_id}
            if thread_id:
                data["message_thread_id"] = thread_id
            if caption:
                sanitized = self._sanitize_markdown_v2(caption)
                data["caption"] = sanitized
                data["parse_mode"] = "MarkdownV2"
            if reply_to_message_id:
                # sendDocument doesn't support reply_parameters as JSON string in multipart,
                # but we can pass reply_to_message_id directly
                data["reply_to_message_id"] = str(reply_to_message_id)

            resp = self._tg_upload_file("sendDocument", target, file_field="document", data=data)
            if resp and resp.get("ok"):
                return resp["result"]["message_id"]
            return None
        finally:
            # Clean up temp files
            for p in (target, tmp_path):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

    @property
    def _chat_id(self) -> str:
        return self._ctx.chat_id if self._ctx else str(TELEGRAM_CHAT_ID)

    @property
    def runner(self) -> ClaudeRunner:
        """Runner for the current context (backward compat property)."""
        if self._ctx:
            return self._ctx.ensure_runner()
        # Fallback: create a transient runner
        return ClaudeRunner()

    def send_message(self, text: str, parse_mode: str = "MarkdownV2",
                     reply_markup: Optional[Dict] = None,
                     chat_id: Optional[str] = None,
                     thread_id: Optional[str] = None,
                     reply_to_message_id: Optional[int] = None,
                     disable_notification: bool = False) -> Optional[int]:
        if parse_mode == "MarkdownV2":
            text = self._sanitize_markdown_v2(text)
        elif parse_mode == "Markdown":
            text = self._sanitize_markdown(text)
        chunks = self._split_message(text)
        last_msg_id = None
        if chat_id is None:
            chat_id = self._chat_id
        if thread_id is None:
            thread_id = self._ctx.thread_id if self._ctx else None
        for i, chunk in enumerate(chunks):
            data: Dict[str, Any] = {"chat_id": chat_id, "text": chunk}
            if thread_id:
                data["message_thread_id"] = thread_id
            if parse_mode:
                data["parse_mode"] = parse_mode
            if reply_markup and chunk == chunks[-1]:
                data["reply_markup"] = reply_markup
            # Reply-to only on first chunk
            if reply_to_message_id and i == 0:
                data["reply_parameters"] = {"message_id": reply_to_message_id,
                                            "allow_sending_without_reply": True}
            # Suppress link previews in bot responses
            data["link_preview_options"] = {"is_disabled": True}
            if disable_notification:
                data["disable_notification"] = True
            resp = self.tg_request("sendMessage", data)
            if resp and resp.get("ok"):
                last_msg_id = resp["result"]["message_id"]
            else:
                if parse_mode:
                    data.pop("parse_mode", None)
                    resp = self.tg_request("sendMessage", data)
                    if resp and resp.get("ok"):
                        last_msg_id = resp["result"]["message_id"]
        return last_msg_id

    def edit_message(self, message_id: int, text: str, parse_mode: str = "MarkdownV2") -> bool:
        if not text.strip():
            return False
        if parse_mode == "MarkdownV2":
            text = self._sanitize_markdown_v2(text)
        elif parse_mode == "Markdown":
            text = self._sanitize_markdown(text)
        text = text[:MAX_MESSAGE_LENGTH]
        chat_id = self._chat_id
        data: Dict[str, Any] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if parse_mode:
            data["parse_mode"] = parse_mode
        resp = self._tg_edit(data)
        if resp:
            return True
        # Retry without parse_mode (markdown may be invalid)
        if parse_mode:
            data.pop("parse_mode", None)
            resp = self._tg_edit(data)
            if resp:
                return True
        return False

    def _tg_edit(self, data: Dict) -> Optional[Dict]:
        """editMessageText with graceful handling of Telegram-specific errors."""
        url = f"{self.base_url}/editMessageText"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                err_body = json.loads(exc.read().decode("utf-8"))
                description = err_body.get("description", "")
            except Exception:
                description = str(exc)
            # "message is not modified" — normal during streaming, skip silently
            if "message is not modified" in description:
                return None
            # "message to edit not found" — stale message_id, skip silently
            if "message to edit not found" in description:
                return None
            logger.warning("editMessageText failed (%d): %s", exc.code, description)
            return None
        except Exception as exc:
            logger.warning("editMessageText error: %s", exc)
            return None

    def delete_message(self, message_id: int, chat_id: Optional[str] = None) -> bool:
        if chat_id is None:
            chat_id = self._chat_id
        resp = self.tg_request("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        return bool(resp and resp.get("ok"))

    def send_typing(self, action: str = "typing") -> None:
        chat_id = self._chat_id
        data: Dict[str, Any] = {"chat_id": chat_id, "action": action}
        if self._ctx and self._ctx.thread_id:
            data["message_thread_id"] = self._ctx.thread_id
        self.tg_request("sendChatAction", data)

    def set_reaction(self, message_id: int, emoji: str) -> None:
        if not message_id:
            return
        chat_id = self._chat_id
        data: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reaction": [{"type": "emoji", "emoji": emoji}] if emoji else [],
        }
        try:
            url = f"{self.base_url}/setMessageReaction"
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=5)
        except Exception as exc:
            logger.debug("set_reaction failed for msg %s: %s", message_id, exc)

    def answer_callback(self, callback_id: str, text: str = "") -> None:
        self.tg_request("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    # -- Markdown sanitization --

    # Characters that must be escaped in MarkdownV2 outside code/pre blocks
    _MDV2_ESCAPE_RE = re.compile(r'([_*\[\]()~>#\+\-=|{}.!\\])')

    @staticmethod
    def _sanitize_markdown_v2(text: str) -> str:
        """Convert Claude's natural Markdown output to Telegram MarkdownV2.

        Strategy: split text into code blocks (``` and inline `) which are
        left untouched, and prose segments where special chars are escaped
        while preserving intended formatting (bold, italic, links, etc.).
        """
        # Fix unbalanced triple-backtick code blocks first
        if text.count("```") % 2 != 0:
            text += "\n```"

        parts = text.split("```")
        for i in range(len(parts)):
            if i % 2 == 1:
                # Inside fenced code block — leave as-is (pre block in MDv2)
                continue
            # Outside code blocks — escape special chars, preserving formatting
            parts[i] = ClaudeTelegramBot._escape_mdv2_segment(parts[i])

        return "```".join(parts)

    @staticmethod
    def _escape_mdv2_segment(text: str) -> str:
        """Escape a prose segment for MarkdownV2, preserving bold/italic/links/inline code."""
        result = []
        pos = 0
        n = len(text)

        while pos < n:
            # Inline code: ` ... ` — leave contents unescaped
            if text[pos] == '`':
                end = text.find('`', pos + 1)
                if end != -1:
                    result.append(text[pos:end + 1])
                    pos = end + 1
                    continue
                else:
                    result.append('`')
                    pos += 1
                    continue

            # Markdown links: [text](url) — escape text, leave url structure
            if text[pos] == '[':
                # Find matching ] then (url)
                close_bracket = text.find(']', pos + 1)
                if close_bracket != -1 and close_bracket + 1 < n and text[close_bracket + 1] == '(':
                    close_paren = text.find(')', close_bracket + 2)
                    if close_paren != -1:
                        link_text = text[pos + 1:close_bracket]
                        url = text[close_bracket + 2:close_paren]
                        escaped_text = ClaudeTelegramBot._MDV2_ESCAPE_RE.sub(r'\\\1', link_text)
                        result.append(f'[{escaped_text}]({url})')
                        pos = close_paren + 1
                        continue

            # Bold: **text** or *text* — preserve markers, escape inside
            if text[pos] == '*':
                # Double ** (bold)
                if pos + 1 < n and text[pos + 1] == '*':
                    end = text.find('**', pos + 2)
                    if end != -1:
                        inner = text[pos + 2:end]
                        escaped = ClaudeTelegramBot._MDV2_ESCAPE_RE.sub(r'\\\1', inner)
                        result.append(f'*{escaped}*')
                        pos = end + 2
                        continue
                # Single * (italic in standard md, bold in Telegram)
                end = text.find('*', pos + 1)
                if end != -1 and end > pos + 1:
                    inner = text[pos + 1:end]
                    escaped = ClaudeTelegramBot._MDV2_ESCAPE_RE.sub(r'\\\1', inner)
                    result.append(f'*{escaped}*')
                    pos = end + 1
                    continue

            # Italic: _text_ — preserve markers, escape inside
            if text[pos] == '_':
                # Double __ (underline in MDv2)
                if pos + 1 < n and text[pos + 1] == '_':
                    end = text.find('__', pos + 2)
                    if end != -1:
                        inner = text[pos + 2:end]
                        escaped = ClaudeTelegramBot._MDV2_ESCAPE_RE.sub(r'\\\1', inner)
                        result.append(f'__{escaped}__')
                        pos = end + 2
                        continue
                # Single _ (italic)
                end = text.find('_', pos + 1)
                if end != -1 and end > pos + 1:
                    inner = text[pos + 1:end]
                    # Skip if looks like snake_case (no spaces)
                    if ' ' not in inner and pos > 0 and text[pos - 1].isalnum():
                        result.append('\\_')
                        pos += 1
                        continue
                    escaped = ClaudeTelegramBot._MDV2_ESCAPE_RE.sub(r'\\\1', inner)
                    result.append(f'_{escaped}_')
                    pos = end + 1
                    continue

            # Strikethrough: ~text~
            if text[pos] == '~':
                end = text.find('~', pos + 1)
                if end != -1 and end > pos + 1:
                    inner = text[pos + 1:end]
                    escaped = ClaudeTelegramBot._MDV2_ESCAPE_RE.sub(r'\\\1', inner)
                    result.append(f'~{escaped}~')
                    pos = end + 1
                    continue

            # Blockquote: > at start of line — MDv2 expects unescaped >
            if text[pos] == '>' and (pos == 0 or text[pos - 1] == '\n'):
                result.append('>')
                pos += 1
                continue

            # Regular character — escape if special
            ch = text[pos]
            # Already-escaped MDv2 sequence (\X where X is a special char) — pass through
            # to avoid double-escaping (e.g. \. → \\. which is invalid)
            if ch == '\\' and pos + 1 < n and text[pos + 1] in r'_*[]()~`>#+-=|{}.!\\":':
                result.append(text[pos:pos + 2])
                pos += 2
                continue
            if ch in r'_*[]()~>#+-=|{}.!\\":':
                result.append(f'\\{ch}')
            else:
                result.append(ch)
            pos += 1

        return ''.join(result)

    @staticmethod
    def _sanitize_markdown(text: str) -> str:
        """Fix unbalanced Markdown v1 markers to avoid Telegram parse errors.

        Ensures code blocks (```), inline code (`), bold (*), and italic (_)
        markers are balanced. Appends closing markers when needed.
        """
        # Fix unbalanced triple-backtick code blocks
        if text.count("```") % 2 != 0:
            text += "\n```"

        # For inline markers, only fix within non-code-block segments
        parts = text.split("```")
        for i in range(0, len(parts), 2):  # even indices = outside code blocks
            seg = parts[i]
            # Fix unbalanced inline code
            if seg.count("`") % 2 != 0:
                parts[i] = seg + "`"
            # Fix unbalanced bold (only standalone *, not inside words)
            seg = parts[i]
            bold_count = len(re.findall(r'(?<!\w)\*(?!\s)', seg)) + len(re.findall(r'(?<!\s)\*(?!\w)', seg))
            if seg.count("*") % 2 != 0:
                parts[i] = seg + "*"
            # Fix unbalanced italic (only _word_ pattern, skip snake_case)
            seg = parts[i]
            if seg.count("_") % 2 != 0:
                parts[i] = seg + "_"

        return "```".join(parts)

    # -- Code extraction for CopyTextButton --

    @staticmethod
    def _extract_copyable_code(text: str) -> Optional[str]:
        """Extract code from response if it has a single dominant code block.

        Returns the code content (without fences) if the response contains
        exactly one fenced code block that makes up most of the response.
        Returns None otherwise (multiple blocks, no blocks, or too much prose).
        """
        blocks = re.findall(r'```(?:\w*\n)?(.*?)```', text, re.DOTALL)
        if len(blocks) != 1:
            return None
        code = blocks[0].strip()
        # Only offer copy if code block is at least 40% of the response
        if len(code) < 20 or len(code) < len(text) * 0.4:
            return None
        # Telegram copy_text has a 256-char limit per button — skip if too long
        # Actually the limit is much higher, but cap at 4096 for sanity
        if len(code) > 4096:
            return None
        return code

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
        s = self._get_session()
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
        ctx = self._ctx
        voice_status = "🔊 On" if (ctx and ctx.tts_enabled) else "🔇 Off"
        lines.append(f"• Resposta por voz: {voice_status}")
        self.send_message("\n".join(lines))

    def cmd_model_switch(self, model: str) -> None:
        s = self._get_session()
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

    def cmd_audio(self) -> None:
        """Show audio language picker and current status."""
        current = HEAR_LOCALE
        can = self._voice_tools.get("can_transcribe", False)
        status = "✅ ativo" if can else "❌ indisponível"

        markup = {
            "inline_keyboard": [
                [
                    {"text": "🇧🇷 Português", "callback_data": "audio:pt-BR"},
                    {"text": "🇺🇸 English", "callback_data": "audio:en-US"},
                ],
                [
                    {"text": "🇪🇸 Español", "callback_data": "audio:es-ES"},
                    {"text": "🇫🇷 Français", "callback_data": "audio:fr-FR"},
                ],
                [
                    {"text": "🇮🇹 Italiano", "callback_data": "audio:it-IT"},
                    {"text": "🇩🇪 Deutsch", "callback_data": "audio:de-DE"},
                ],
                [
                    {"text": "🇯🇵 日本語", "callback_data": "audio:ja-JP"},
                    {"text": "🇨🇳 中文", "callback_data": "audio:zh-CN"},
                ],
            ]
        }
        self.send_message(
            f"🎤 *Áudio*\n\n"
            f"Status: {status}\n"
            f"Idioma atual: `{current}`\n\n"
            f"Escolha o idioma para transcrição:",
            reply_markup=markup,
        )

    def cmd_voice(self, arg: str = "") -> None:
        """Toggle TTS voice responses on/off."""
        ctx = self._ctx
        if not ctx:
            self.send_message("❌ Contexto não disponível.")
            return
        if not self._tts_tools.get("can_synthesize"):
            self.send_message(
                "❌ TTS indisponível.\n"
                "Necessário: `edge-tts` ou `say` (macOS) + `ffmpeg`."
            )
            return
        if arg.lower() in ("on", "1", "sim"):
            ctx.tts_enabled = True
        elif arg.lower() in ("off", "0", "nao", "não"):
            ctx.tts_enabled = False
        else:
            ctx.tts_enabled = not ctx.tts_enabled
        self._save_contexts()
        if TTS_ENGINE == "edge-tts" and self._tts_tools.get("edge_tts"):
            engine = "Edge TTS"
            voice = TTS_VOICE or EDGE_TTS_VOICE_MAP.get(HEAR_LOCALE, "pt-BR-AntonioNeural")
        else:
            engine = "macOS Say"
            voice = TTS_VOICE or SAY_VOICE_MAP.get(HEAR_LOCALE, "Samantha")
        status = "✅ ativado" if ctx.tts_enabled else "❌ desativado"
        self.send_message(f"🔊 Resposta por voz: {status}\nEngine: `{engine}` | Voz: `{voice}`")

    def cmd_new(self, name: Optional[str]) -> None:
        # Consolidate current session before creating a new one
        self._consolidate_session()
        if not name:
            current = self._get_session()
            agent = current.agent if current else None
            name = _make_session_name(agent, self.sessions.sessions)
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
        # Consolidate before clearing — session_id will be lost
        self._consolidate_session()
        s = self._get_session()
        if s:
            s.session_id = None
            self.sessions.save()
            self.send_message(f"🔄 Sessão `{s.name}` resetada (session\\_id removido).")
        else:
            self.send_message("❌ Nenhuma sessão ativa.")

    def cmd_compact(self) -> None:
        self._run_claude_prompt("/compact")

    def _auto_compact(self, session: Session) -> None:
        """Run /compact in background to keep session context manageable."""
        if not session.session_id:
            return
        sid = session.session_id
        ws = session.workspace
        model = session.model

        def _worker() -> None:
            try:
                logger.info("Auto-compact starting for session %s (turns=%d)",
                            session.name, session.message_count)
                runner = ClaudeRunner()
                runner.run(
                    prompt="/compact",
                    model=model,
                    session_id=sid,
                    workspace=ws,
                    system_prompt=None,
                )
                if runner.captured_session_id:
                    session.session_id = runner.captured_session_id
                    self.sessions.save()
                logger.info("Auto-compact completed for session %s", session.name)
            except Exception as exc:
                logger.error("Auto-compact failed: %s", exc)

        threading.Thread(target=_worker, daemon=True, name="auto-compact").start()

    def cmd_cost(self) -> None:
        self._run_claude_prompt("/cost")

    def cmd_doctor(self) -> None:
        self._run_claude_prompt("/doctor")

    def cmd_stop(self, arg: str = "") -> None:
        arg = arg.strip().replace(".md", "")

        # /stop <name> — stop a specific routine/pipeline
        if arg:
            if self._stop_routine_by_name(arg):
                self.send_message(f"🛑 `{arg}` cancelado.")
            else:
                self.send_message(f"ℹ️ `{arg}` não está rodando.")
            return

        # /stop (no arg) — stop current user task first
        if self.runner.running:
            self.runner.cancel()
            self.send_message("🛑 Cancelamento enviado.")
            return

        # No user task — check running routines/pipelines
        running = self._get_running_routines()
        if not running:
            self.send_message("ℹ️ Nenhum processo rodando.")
        elif len(running) == 1:
            name, rtype = running[0]
            self._stop_routine_by_name(name)
            icon = "🔗" if rtype == "pipeline" else "🔁"
            self.send_message(f"🛑 {icon} `{name}` cancelado.")
        else:
            buttons = []
            for name, rtype in running:
                icon = "🔗" if rtype == "pipeline" else "🔁"
                buttons.append([{"text": f"🛑 {icon} {name}", "callback_data": f"stop:{name}"}])
            self.send_message("🛑 *Qual processo parar?*", reply_markup={"inline_keyboard": buttons})

    def cmd_timeout(self, val: str) -> None:
        try:
            self.timeout_seconds = int(val)
            self.send_message(f"✅ Timeout alterado para {self.timeout_seconds}s")
        except ValueError:
            self.send_message("❌ Valor inválido. Use: `/timeout 300`")

    def cmd_workspace(self, path: str) -> None:
        p = os.path.expanduser(path)
        if os.path.isdir(p):
            s = self._get_session()
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
        ctx = self._ctx
        if ctx and ctx.runner and ctx.runner.running:
            if ctx.runner.send_btw(text):
                self.send_message("💭 Enviado ao Claude via /btw.")
            else:
                with ctx.pending_lock:
                    if len(ctx.pending) >= 10:
                        self.send_message("⚠️ Fila cheia — aguarde o Claude terminar.")
                        return
                    ctx.pending.append(text)
                self.send_message("💭 BTW enfileirado — será enviado quando Claude terminar.")
        else:
            self._run_claude_prompt(text)

    def _get_journal_path(self) -> str:
        """Return the journal file path for today, using agent journal if active."""
        session = self._get_session()
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
        session = self._get_session()
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
        arg = arg.strip()
        arg_lower = arg.lower()
        if not arg:
            # No arg: show action keyboard
            markup = {"inline_keyboard": [
                [{"text": "📋 Listar", "callback_data": "routine:list"},
                 {"text": "📊 Status", "callback_data": "routine:status"}],
                [{"text": "➕ Criar nova", "callback_data": "routine:new"},
                 {"text": "✏️ Editar", "callback_data": "routine:edit"}],
            ]}
            self.send_message("🔁 *Rotinas* — o que deseja fazer?", reply_markup=markup)
            return
        if arg_lower == "list":
            self._routine_list()
        elif arg_lower == "status":
            self._routine_status()
        elif arg_lower in ("new", "create"):
            self._routine_create("")
        elif arg_lower.startswith("edit"):
            edit_arg = arg[4:].strip()
            self._routine_edit(edit_arg)
        else:
            # Treat as creation request with context
            self._routine_create(arg)

    def _routine_list(self) -> None:
        routines = self.scheduler.list_today_routines()
        if not routines:
            self.send_message("📋 Nenhuma rotina agendada para hoje.")
            return
        _icons = {"pending": "⏰", "running": "🔄", "completed": "✅", "failed": "❌", "skipped": "⏭"}
        lines = ["📋 *Rotinas de hoje*\n"]
        for r in routines:
            icon = _icons.get(r["status"], "⏰")
            rtype = r.get("type", "routine")
            if rtype == "pipeline":
                steps_info = r.get("steps", {})
                total = len(steps_info) if steps_info else 0
                done = sum(1 for s in steps_info.values() if s.get("status") in ("completed", "failed", "skipped")) if steps_info else 0
                lines.append(f"- {icon} `{r['time']}` *{r['title']}* — pipeline {done}/{total} steps — {r['model']}")
            else:
                lines.append(f"- {icon} `{r['time']}` *{r['title']}* — {r['model']}")
        self.send_message("\n".join(lines))

    def _routine_status(self) -> None:
        routines = self.scheduler.list_today_routines()
        if not routines:
            self.send_message("📊 Nenhuma rotina agendada para hoje.")
            return
        _icons = {"pending": "⏰", "running": "🔄", "completed": "✅", "failed": "❌", "skipped": "⏭"}
        lines = [f"📊 *Rotinas — {time.strftime('%Y-%m-%d')}*\n"]
        for r in routines:
            icon = _icons.get(r["status"], "⏰")
            extra = ""
            if r["status"] == "failed" and r.get("error"):
                extra = f" — `{r['error'][:60]}`"
            rtype = r.get("type", "routine")
            if rtype == "pipeline":
                steps_info = r.get("steps", {})
                lines.append(f"- {icon} `{r['time']}` *{r['title']}* (pipeline){extra}")
                if steps_info:
                    for sid, sdata in steps_info.items():
                        si = _icons.get(sdata.get("status", "pending"), "⏰")
                        lines.append(f"    {si} {sid}")
            else:
                lines.append(f"- {icon} `{r['time']}` *{r['title']}*{extra}")
        self.send_message("\n".join(lines))

    def _routine_create(self, extra: str) -> None:
        prompt = (
            f"Execute a skill de criacao de rotinas. "
            "Leia Skills/create-routine.md para instrucoes. "
            "Ajude o usuario a criar uma nova rotina em Routines/. "
            "Faca as perguntas necessarias sobre: o que a rotina deve fazer, "
            "horarios, dias da semana, modelo, e data limite. "
            "Depois gere o arquivo .md com frontmatter completo e registre no Journal."
        )
        if extra:
            prompt += f"\n\nO usuario disse: {extra}"
        self._run_claude_prompt(prompt)

    def _routine_edit(self, name: str) -> None:
        prompt = (
            f"O usuario quer editar uma rotina existente. "
            "Liste os arquivos em Routines/ e mostre as rotinas disponiveis. "
            "Pergunte qual deseja editar e o que quer mudar (horario, dias, prompt, modelo, ativar/desativar). "
            "Faca a edicao no arquivo .md e confirme."
        )
        if name:
            prompt += f"\n\nO usuario quer editar: {name}"
        self._run_claude_prompt(prompt)

    # -- Stop helpers --

    def _get_running_routines(self) -> list:
        """Returns list of (name, type) for all running routines and pipelines."""
        running = []
        with self._active_pipelines_lock:
            for name in self._active_pipelines:
                running.append((name, "pipeline"))
        with self._routine_contexts_lock:
            for name, ctx in self._routine_contexts.items():
                if ctx.runner and ctx.runner.running:
                    running.append((name, "routine"))
        return running

    def _stop_routine_by_name(self, name: str) -> bool:
        """Cancel a running routine or pipeline by name. Returns True if found."""
        with self._active_pipelines_lock:
            executor = self._active_pipelines.get(name)
        if executor:
            executor.cancel()
            return True
        with self._routine_contexts_lock:
            ctx = self._routine_contexts.get(name)
        if ctx and ctx.runner and ctx.runner.running:
            ctx.runner.cancel()
            return True
        return False

    # -- Run command (manual trigger) --

    def cmd_run(self, arg: str) -> None:
        """Manually trigger a routine or pipeline by name."""
        arg = arg.strip()
        if not arg:
            self._run_list_keyboard()
            return

        name = arg.replace(".md", "").strip()
        md_file = ROUTINES_DIR / f"{name}.md"

        if not md_file.exists():
            self.send_message(f"❌ Rotina `{name}` não encontrada.")
            return

        # Check if already running
        with self._active_pipelines_lock:
            if name in self._active_pipelines:
                self.send_message(f"⚠️ Pipeline `{name}` já está em execução.")
                return
        with self._routine_contexts_lock:
            if name in self._routine_contexts:
                self.send_message(f"⚠️ Rotina `{name}` já está em execução.")
                return

        fm, body = get_frontmatter_and_body(md_file)
        if not fm or not body:
            self.send_message(f"❌ Arquivo de rotina `{name}` inválido.")
            return

        model = str(fm.get("model", "sonnet"))
        time_slot = f"manual-{time.strftime('%H:%M:%S')}"
        routine_type = str(fm.get("type", "routine"))

        if routine_type == "pipeline":
            self.scheduler._enqueue_pipeline_from_file(
                md_file, fm, body, name, model, time_slot)
            self.send_message(f"🚀 Pipeline `{name}` disparada manualmente.")
        else:
            self.routine_state.set_status(name, time_slot, "running")
            task = RoutineTask(
                name=name,
                prompt=body,
                model=model,
                time_slot=time_slot,
                agent=fm.get("agent"),
                minimal_context=bool(fm.get("context") == "minimal"),
                voice=bool(fm.get("voice", False)),
            )
            self._enqueue_routine(task)
            self.send_message(f"🚀 Rotina `{name}` disparada manualmente.")

    def _run_list_keyboard(self) -> None:
        """Show inline keyboard with all available routines/pipelines."""
        if not ROUTINES_DIR.is_dir():
            self.send_message("❌ Nenhuma rotina disponível.")
            return

        buttons = []
        for md_file in sorted(ROUTINES_DIR.glob("*.md")):
            fm, body = get_frontmatter_and_body(md_file)
            if not fm or not body:
                continue
            if str(fm.get("type", "")).lower() == "index":
                continue
            title = fm.get("title", md_file.stem)
            rtype = str(fm.get("type", "routine"))
            enabled = fm.get("enabled", False)
            icon = "🔗" if rtype == "pipeline" else "🔁"
            status = "" if enabled else " (off)"
            buttons.append([{
                "text": f"{icon} {title}{status}",
                "callback_data": f"run:{md_file.stem}"
            }])

        if not buttons:
            self.send_message("❌ Nenhuma rotina disponível.")
            return

        markup = {"inline_keyboard": buttons}
        self.send_message("🚀 *Executar rotina/pipeline manualmente:*", reply_markup=markup)

    # -- Skill commands --

    def cmd_skill(self, arg: str) -> None:
        arg = arg.strip()
        arg_lower = arg.lower()
        if not arg:
            markup = {"inline_keyboard": [
                [{"text": "📋 Listar", "callback_data": "skill:list"},
                 {"text": "✏️ Editar", "callback_data": "skill:edit"}],
            ]}
            self.send_message("⚡ *Skills* — o que deseja fazer?", reply_markup=markup)
            return
        if arg_lower == "list":
            self._skill_list()
        elif arg_lower.startswith("edit"):
            self._skill_edit(arg[4:].strip())
        else:
            self._skill_edit(arg)

    def _skill_list(self) -> None:
        skills_dir = VAULT_DIR / "Skills"
        if not skills_dir.is_dir():
            self.send_message("⚡ Nenhuma skill encontrada.")
            return
        lines = ["⚡ *Skills*\n"]
        for f in sorted(skills_dir.glob("*.md")):
            if f.name.startswith("Skills"):
                continue  # skip index
            fm, _ = get_frontmatter_and_body(f)
            title = fm.get("title", f.stem)
            desc = fm.get("description", "")[:60]
            lines.append(f"- *{title}* — {desc}")
        if len(lines) == 1:
            self.send_message("⚡ Nenhuma skill encontrada.")
        else:
            self.send_message("\n".join(lines))

    def _skill_edit(self, name: str) -> None:
        prompt = (
            f"O usuario quer editar uma skill existente. "
            "Liste as skills em Skills/ (leia o frontmatter de cada .md). "
            "Pergunte qual deseja editar e o que quer mudar. "
            "Faca a edicao no arquivo .md e confirme."
        )
        if name:
            prompt += f"\n\nO usuario quer editar: {name}"
        self._run_claude_prompt(prompt)

    # -- Agent commands --

    def cmd_agent(self, arg: str) -> None:
        arg = arg.strip()
        arg_lower = arg.lower()
        if not arg:
            # No argument: show action keyboard
            rows = [
                [{"text": "🔀 Trocar agente", "callback_data": "agentmenu:switch"},
                 {"text": "📋 Listar", "callback_data": "agentmenu:list"}],
                [{"text": "➕ Criar novo", "callback_data": "agent:create"},
                 {"text": "✏️ Editar", "callback_data": "agentmenu:edit"}],
                [{"text": "📥 Importar (OC)", "callback_data": "agentmenu:import"}],
            ]
            markup = {"inline_keyboard": rows}
            self.send_message("🤖 *Agentes* — o que deseja fazer?", reply_markup=markup)
            return
        if arg_lower == "list":
            self._agent_list()
        elif arg_lower in ("new", "create"):
            self._run_agent_create_skill("")
        elif arg_lower == "import":
            self._agent_import("")
        elif arg_lower.startswith("edit"):
            self._agent_edit(arg[4:].strip())
        else:
            self.cmd_agent_switch(arg_lower)

    def _agent_list(self) -> None:
        agents = list_agents()
        if not agents:
            self.send_message("🤖 Nenhum agente configurado.\nUse `/agent new` para criar um.")
            return
        session = self._get_session()
        active_agent = session.agent if session else None
        lines = ["🤖 *Agentes*\n"]
        for a in agents:
            icon = a.get("icon", "🤖")
            marker = " ◀️" if a["_id"] == active_agent else ""
            lines.append(f"- {icon} *{a.get('name', a['_id'])}* — {a.get('description', '')[:60]}{marker}")
        self.send_message("\n".join(lines))

    def _agent_edit(self, name: str) -> None:
        prompt = (
            f"O usuario quer editar um agente existente. "
            "Liste os agentes em Agents/ (leia o frontmatter de cada agent.md). "
            "Pergunte qual deseja editar e o que quer mudar (personalidade, instrucoes, modelo, icone). "
            "Faca a edicao nos arquivos agent.md e/ou CLAUDE.md do agente e confirme."
        )
        if name:
            prompt += f"\n\nO usuario quer editar: {name}"
        self._run_claude_prompt(prompt)

    def _agent_import(self, extra: str) -> None:
        prompt = (
            f"Execute a skill de importacao de agentes. "
            "Leia Skills/import-agent.md para instrucoes. "
            "Ajude o usuario a importar um agente existente do OpenClaw para o vault."
        )
        if extra:
            prompt += f"\n\nO usuario disse: {extra}"
        self._run_claude_prompt(prompt)

    def _run_agent_create_skill(self, extra: str = "") -> None:
        prompt = (
            f"Execute a skill de criacao de agentes. "
            "Leia Skills/create-agent.md para instrucoes. "
            "Ajude o usuario a criar um novo agente em Agents/. "
            "Faca as perguntas necessarias sobre: nome, personalidade, especializacoes, "
            "modelo padrao, e icone. Depois gere os arquivos e registre no Journal."
        )
        if extra:
            prompt += f"\n\nO usuario disse: {extra}"
        self._run_claude_prompt(prompt)

    def cmd_agent_switch(self, agent_id: str) -> None:
        if agent_id == "none":
            session = self._get_session()
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
        session = self._get_session()
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
        rows.append([
            {"text": "➕ Criar novo", "callback_data": "agent:create"},
            {"text": "❌ Nenhum", "callback_data": "agent:none"},
        ])
        markup = {"inline_keyboard": rows}
        self.send_message("Escolha o agente:", reply_markup=markup)

    # -- Telegram file download --

    def _download_telegram_file(self, file_id: str, save_dir: Path = TEMP_IMAGES_DIR) -> Optional[Path]:
        """Download a file from Telegram and save to a directory."""
        try:
            resp = self.tg_request("getFile", {"file_id": file_id})
            if not resp or not resp.get("ok"):
                logger.error("getFile failed for file_id=%s", file_id)
                return None
            file_path = resp["result"]["file_path"]

            url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
            ext = Path(file_path).suffix or ".bin"
            filename = f"{int(time.time())}_{Path(file_path).stem}{ext}"
            save_path = save_dir / filename

            with urllib.request.urlopen(url, timeout=30) as resp:
                save_path.write_bytes(resp.read())
            logger.info("Downloaded file to %s (%s)", save_path, file_path)
            return save_path
        except Exception as exc:
            logger.error("Failed to download file %s: %s", file_id, exc)
            return None

    # -- Voice transcription --

    def _check_voice_tools(self) -> Dict[str, Any]:
        """Check availability of voice transcription tools."""
        import shutil as _shutil
        result: Dict[str, Any] = {"ffmpeg": None, "hear": None, "can_transcribe": False}

        # Check ffmpeg
        if Path(FFMPEG_PATH).is_file():
            result["ffmpeg"] = FFMPEG_PATH
        else:
            found = _shutil.which("ffmpeg")
            if found:
                result["ffmpeg"] = found

        # Check hear — configured path, then bundled location, then system PATH
        hear_candidates = []
        if HEAR_PATH:
            hear_candidates.append(HEAR_PATH)
        hear_candidates.append(str(HEAR_BIN_DIR / "hear"))
        for candidate in hear_candidates:
            if Path(candidate).is_file():
                result["hear"] = candidate
                break
        if not result["hear"]:
            found = _shutil.which("hear")
            if found:
                result["hear"] = found

        result["can_transcribe"] = bool(result["ffmpeg"] and result["hear"])
        return result

    def _convert_ogg_to_wav(self, ogg_path: Path) -> Optional[Path]:
        """Convert OGG/Opus audio to WAV (16kHz mono) using ffmpeg."""
        wav_path = ogg_path.with_suffix(".wav")
        try:
            proc = subprocess.run(
                [self._voice_tools["ffmpeg"], "-y", "-i", str(ogg_path),
                 "-ar", "16000", "-ac", "1", "-f", "wav", str(wav_path)],
                capture_output=True, text=True, timeout=30,
            )
            if proc.returncode != 0:
                logger.error("ffmpeg conversion failed: %s", proc.stderr[:500])
                return None
            return wav_path
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg conversion timed out for %s", ogg_path)
            return None
        except Exception as exc:
            logger.error("ffmpeg conversion error: %s", exc)
            return None

    def _transcribe_audio(self, wav_path: Path, locale: str = "") -> Optional[str]:
        """Transcribe WAV audio to text using the 'hear' CLI (Apple SFSpeechRecognizer)."""
        locale = locale or HEAR_LOCALE
        try:
            cmd = [self._voice_tools["hear"], "-l", locale, "-i", str(wav_path)]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
            )
            if proc.returncode != 0:
                logger.error("hear transcription failed (rc=%d): %s", proc.returncode, proc.stderr[:500])
                return None
            text = proc.stdout.strip()
            if not text:
                logger.warning("hear returned empty transcription for %s", wav_path)
                return None
            return text
        except subprocess.TimeoutExpired:
            logger.error("hear transcription timed out for %s", wav_path)
            return None
        except Exception as exc:
            logger.error("hear transcription error: %s", exc)
            return None

    def _handle_voice(self, msg: Dict, user_msg_id: Optional[int] = None) -> None:
        """Handle a voice/audio message: download, convert, transcribe, send to Claude."""
        voice_data = msg.get("voice") or msg.get("audio")
        if not voice_data:
            return
        file_id = voice_data["file_id"]
        duration = voice_data.get("duration", 0)
        reply_ctx = self._extract_reply_context(msg)

        # Check tools
        if not self._voice_tools.get("can_transcribe"):
            missing = []
            if not self._voice_tools.get("ffmpeg"):
                missing.append("ffmpeg (`brew install ffmpeg`)")
            if not self._voice_tools.get("hear"):
                missing.append("hear (https://github.com/sveinbjornt/hear)")
            self.send_message(
                "⚠️ Transcrição de áudio indisponível.\n"
                f"Ferramentas faltando: {', '.join(missing)}\n"
                "Execute `./claude-bot.sh install` e reinicie o bot."
            )
            return

        # Voice/text response picker — show buttons while transcribing
        self.send_typing("record_voice")
        ctx = self._ctx
        current_is_voice = ctx.tts_enabled if ctx else False
        pick_id = secrets.token_hex(4)
        self._voice_picks[pick_id] = {"force_tts": current_is_voice, "resolved": False}
        markup = {"inline_keyboard": [[
            {"text": f"🔊 Áudio{' ✓' if current_is_voice else ''}",
             "callback_data": f"voicepick:{pick_id}:audio"},
            {"text": f"💬 Texto{' ✓' if not current_is_voice else ''}",
             "callback_data": f"voicepick:{pick_id}:text"},
        ]]}
        status_msg = self.send_message(
            f"🎤 Áudio recebido ({duration}s). Transcrevendo...",
            reply_markup=markup,
        )

        # Download
        saved = self._download_telegram_file(file_id, save_dir=TEMP_AUDIO_DIR)
        if not saved:
            self._voice_picks.pop(pick_id, None)
            self._voice_status(status_msg, "❌ Não consegui baixar o áudio.")
            return

        try:
            # Convert OGG → WAV
            wav_path = self._convert_ogg_to_wav(saved)
            if not wav_path:
                self._voice_picks.pop(pick_id, None)
                self._voice_status(status_msg, "❌ Falha na conversão do áudio (ffmpeg).")
                return

            # Transcribe
            transcription = self._transcribe_audio(wav_path)
            if not transcription:
                self._voice_picks.pop(pick_id, None)
                self._voice_status(
                    status_msg,
                    "❌ Falha na transcrição.\n"
                    "Verifique se Dictation está habilitado: System Settings → Keyboard → Dictation"
                )
                return

            # Resolve pick: read user's choice and remove buttons
            pick = self._voice_picks.pop(pick_id, None)
            force_tts = pick["force_tts"] if pick else current_is_voice

            # Show transcription preview (removes inline keyboard)
            preview = transcription[:500] + ("..." if len(transcription) > 500 else "")
            self._voice_status(status_msg, f"🎤 _{preview}_")

            # Build prompt and send to Claude
            caption = msg.get("caption", "")
            prefix = "[Mensagem de voz transcrita]"
            if caption:
                prompt = f"{prefix}\n\n{reply_ctx}{transcription}\n\n[Legenda]: {caption}"
            else:
                prompt = f"{prefix}\n\n{reply_ctx}{transcription}"

            # Send to Claude with the user's response format choice
            if ctx:
                ctx.user_msg_id = user_msg_id
                self.set_reaction(user_msg_id, "👀")
                ctx.last_reaction = "👀"
            self._run_claude_prompt(prompt, force_tts=force_tts)

        finally:
            # Cleanup temp files
            cleanup_paths = [saved]
            if saved:
                cleanup_paths.append(saved.with_suffix(".wav"))
            for p in cleanup_paths:
                try:
                    if p and p.exists():
                        p.unlink()
                except OSError:
                    pass

    def _voice_status(self, msg_id: Optional[int], text: str) -> None:
        """Update or send a voice status message."""
        if msg_id:
            self.edit_message(msg_id, text)
        else:
            self.send_message(text)

    # -- Voice synthesis (TTS) --

    def _check_tts_tools(self) -> Dict[str, Any]:
        """Check availability of TTS synthesis tools (edge-tts, say, ffmpeg)."""
        result: Dict[str, Any] = {"can_synthesize": False, "say": None, "ffmpeg": None, "edge_tts": None}
        if Path(SAY_PATH).is_file():
            result["say"] = SAY_PATH
        ffmpeg = FFMPEG_PATH if Path(FFMPEG_PATH).is_file() else shutil.which("ffmpeg")
        if ffmpeg:
            result["ffmpeg"] = ffmpeg
        # shutil.which uses the process PATH — launchd may not include ~/.local/bin (pipx default)
        _pipx_edge = Path.home() / ".local/bin/edge-tts"
        edge = shutil.which("edge-tts") or (str(_pipx_edge) if _pipx_edge.is_file() else None)
        if edge:
            result["edge_tts"] = edge
        can_edge = bool(result["edge_tts"] and result["ffmpeg"])
        can_say = bool(result["say"] and result["ffmpeg"])
        result["can_synthesize"] = can_edge or can_say
        return result

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Remove Markdown formatting to produce clean text for TTS."""
        # Remove code blocks (triple backticks and content)
        text = re.sub(r"```[\s\S]*?```", "", text)
        # Remove inline code
        text = re.sub(r"`([^`]*)`", r"\1", text)
        # Remove bold/italic markers
        text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
        text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text)
        # Remove links [text](url) keeping text
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        # Remove bullet/list markers
        text = re.sub(r"^[\s]*[-*•]\s+", "", text, flags=re.MULTILINE)
        text = re.sub(r"^[\s]*\d+\.\s+", "", text, flags=re.MULTILINE)
        # Remove headings
        text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
        # Remove cost line (appended by bot)
        text = re.sub(r"\n*💰.*$", "", text)
        # Remove emojis (macOS say reads them aloud as descriptions)
        text = re.sub(
            r"[\U0001F300-\U0001FAFF\U00002702-\U000027B0\U0000FE00-\U0000FE0F"
            r"\U0000200D\U00002600-\U000026FF\U00002B50\U00002B55"
            r"\U000023E0-\U000023FF\U00002300-\U000023CF\U0000203C\U00002049"
            r"\U000020E3\U00003030\U0000303D\U00003297\U00003299"
            r"\U0001F000-\U0001F02F\U0001F900-\U0001F9FF]+", "", text)
        # Collapse whitespace
        text = re.sub(r"\n{2,}", "\n", text).strip()
        return text

    def _tts_generate(self, text: str) -> Optional[Path]:
        """Convert text to OGG Opus audio file. Returns path or None on failure."""
        if not self._tts_tools.get("can_synthesize"):
            return None

        clean = self._strip_markdown(text)
        if len(clean) < 10:
            return None

        ts = int(time.time() * 1000)
        ogg_path = TEMP_AUDIO_DIR / f"tts_{ts}.ogg"
        TEMP_AUDIO_DIR.mkdir(parents=True, exist_ok=True)

        # Try configured engine first, fallback to the other
        if TTS_ENGINE == "edge-tts" and self._tts_tools.get("edge_tts"):
            logger.info("TTS: generating with edge-tts")
            result = self._tts_edge(clean, ogg_path)
            if result:
                return result
            logger.warning("edge-tts failed, falling back to say")

        if self._tts_tools.get("say") and self._tts_tools.get("ffmpeg"):
            logger.info("TTS: generating with macOS say")
            result = self._tts_say(clean, ogg_path)
            if result:
                return result

        # If say is primary but failed, try edge-tts as fallback
        if TTS_ENGINE == "say" and self._tts_tools.get("edge_tts"):
            logger.info("TTS: say failed, falling back to edge-tts")
            return self._tts_edge(clean, ogg_path)

        return None

    def _tts_edge(self, text: str, ogg_path: Path) -> Optional[Path]:
        """Generate OGG via edge-tts (neural voices)."""
        voice = TTS_VOICE or EDGE_TTS_VOICE_MAP.get(HEAR_LOCALE, "pt-BR-AntonioNeural")
        mp3_path = ogg_path.with_suffix(".mp3")
        try:
            result = subprocess.run(
                [self._tts_tools["edge_tts"], "--voice", voice,
                 "--text", text, "--write-media", str(mp3_path)],
                capture_output=True, timeout=60,
            )
            if result.returncode != 0 or not mp3_path.exists():
                logger.error("edge-tts failed: %s", result.stderr.decode(errors="replace"))
                return None

            # Convert MP3 -> OGG Opus
            ffmpeg = self._tts_tools["ffmpeg"]
            result = subprocess.run(
                [ffmpeg, "-y", "-i", str(mp3_path), "-c:a", "libopus", "-b:a", "48k", str(ogg_path)],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0 or not ogg_path.exists():
                logger.error("ffmpeg edge-tts conversion failed: %s", result.stderr.decode(errors="replace"))
                return None

            return ogg_path
        except Exception as exc:
            logger.error("edge-tts generation failed: %s", exc)
            return None
        finally:
            try:
                if mp3_path.exists():
                    mp3_path.unlink()
            except OSError:
                pass

    def _tts_say(self, text: str, ogg_path: Path) -> Optional[Path]:
        """Generate OGG via macOS say (fallback)."""
        voice = TTS_VOICE or SAY_VOICE_MAP.get(HEAR_LOCALE, "Samantha")
        aiff_path = ogg_path.with_suffix(".aiff")
        try:
            result = subprocess.run(
                [SAY_PATH, "-v", voice, "-o", str(aiff_path), text],
                capture_output=True, timeout=60,
            )
            if result.returncode != 0 or not aiff_path.exists():
                logger.error("say failed: %s", result.stderr.decode(errors="replace"))
                return None

            ffmpeg = self._tts_tools["ffmpeg"]
            result = subprocess.run(
                [ffmpeg, "-y", "-i", str(aiff_path), "-c:a", "libopus", "-b:a", "48k", str(ogg_path)],
                capture_output=True, timeout=30,
            )
            if result.returncode != 0 or not ogg_path.exists():
                logger.error("ffmpeg TTS conversion failed: %s", result.stderr.decode(errors="replace"))
                return None

            return ogg_path
        except Exception as exc:
            logger.error("say TTS generation failed: %s", exc)
            return None
        finally:
            try:
                if aiff_path.exists():
                    aiff_path.unlink()
            except OSError:
                pass

    def _send_voice_message(self, ogg_path: Path, chat_id: str,
                            thread_id: Optional[int] = None) -> Optional[int]:
        """Upload OGG file as Telegram voice message."""
        data: Dict[str, Any] = {"chat_id": chat_id}
        if thread_id:
            data["message_thread_id"] = thread_id
        resp = self._tg_upload_file("sendVoice", ogg_path, file_field="voice", data=data)
        if resp and resp.get("ok"):
            return resp.get("result", {}).get("message_id")
        return None

    def _maybe_send_tts(self, text: str, chat_id: str, thread_id: Optional[int] = None) -> None:
        """Dispatch TTS generation and sending in a background thread."""
        if not self._tts_tools.get("can_synthesize"):
            return
        t = threading.Thread(
            target=self._tts_worker, args=(text, chat_id, thread_id),
            daemon=True, name="tts-worker",
        )
        t.start()

    def _tts_worker(self, text: str, chat_id: str, thread_id: Optional[int] = None) -> None:
        """Background: generate TTS audio and send as voice message."""
        try:
            # Show "generating audio" action during TTS synthesis
            synth_data: Dict[str, Any] = {"chat_id": chat_id, "action": "record_voice"}
            if thread_id:
                synth_data["message_thread_id"] = thread_id
            self.tg_request("sendChatAction", synth_data)
            ogg_path = self._tts_generate(text)
            if not ogg_path:
                return
            # Show "sending audio" action before upload
            action_data: Dict[str, Any] = {"chat_id": chat_id, "action": "upload_voice"}
            if thread_id:
                action_data["message_thread_id"] = thread_id
            self.tg_request("sendChatAction", action_data)
            # Upload
            self._send_voice_message(ogg_path, chat_id, thread_id)
        except Exception as exc:
            logger.error("TTS worker failed: %s", exc)
        finally:
            # Cleanup OGG
            try:
                if ogg_path and ogg_path.exists():
                    ogg_path.unlink()
            except (OSError, UnboundLocalError):
                pass

    # -- Claude execution --

    def _get_session(self) -> Session:
        """Get the session for the current context."""
        ctx = self._ctx
        if ctx and ctx.session_name:
            if ctx.session_name in self.sessions.sessions:
                return self.sessions.sessions[ctx.session_name]
            # Create session for this context
            s = self.sessions.create(ctx.session_name)
            return s
        # No context or no session_name — ensure at least one session exists
        self.sessions.ensure_active()
        active = self.sessions.active_session
        if active and active in self.sessions.sessions:
            return self.sessions.sessions[active]
        # Last resort: create a default session
        return self.sessions.create()

    def _run_claude_prompt(self, prompt: str, _retry: bool = False, *,
                          no_output_timeout: int = 90,
                          max_total_timeout: int = 600,
                          routine_mode: bool = False,
                          system_prompt: Optional[str] = SYSTEM_PROMPT,
                          force_tts: bool = False,
                          suppress_text: bool = False) -> None:
        ctx = self._ctx
        runner = ctx.ensure_runner() if ctx else ClaudeRunner()

        if runner.running:
            if runner.send_btw(prompt):
                self.send_message("💭 Enviado ao Claude via /btw.")
            else:
                lock = ctx.pending_lock if ctx else threading.Lock()
                q = ctx.pending if ctx else []
                with lock:
                    q.append(prompt)
                self.send_message("💭 BTW enfileirado — será enviado quando Claude terminar.")
            return

        session = self._get_session()
        if not _retry:
            session.message_count += 1
            session.total_turns += 1
            self.sessions.cumulative_turns += 1

        # Append TTS instruction when voice mode is active or force_tts
        effective_sp = system_prompt
        tts_this_request = force_tts or (ctx and ctx.tts_enabled and not routine_mode)
        if tts_this_request:
            suffix = _tts_prompt_suffix()
            effective_sp = (effective_sp + suffix) if effective_sp else suffix

        # All paths use the same session/model/effort
        effective_session_id = session.session_id
        effective_model = session.model
        effective_effort = self.effort

        # Start runner thread FIRST — before any blocking network I/O
        runner_thread = threading.Thread(
            target=runner.run,
            kwargs={
                "prompt": prompt,
                "model": effective_model,
                "session_id": effective_session_id,
                "workspace": session.workspace,
                "effort": effective_effort,
                "system_prompt": effective_sp,
            },
            daemon=True,
        )
        runner_thread.start()

        # Now send status message and save session (non-blocking for subprocess)
        if not _retry:
            self.sessions.save()
        if not _retry and not routine_mode:
            if ctx:
                ctx.stream_msg_id = self.send_message("⏳ _Processando..._",
                                                       reply_to_message_id=ctx.user_msg_id)

        # Start watchdog thread
        watchdog_thread = threading.Thread(
            target=self._watchdog, args=(runner, no_output_timeout, max_total_timeout), daemon=True)
        watchdog_thread.start()

        # Stream updates while runner is active
        self._stream_updates(runner_thread, runner, routine_mode=routine_mode)

        # Finalize
        self._finalize_response(session, runner, prompt=prompt if not _retry else None,
                                routine_mode=routine_mode, force_tts=tts_this_request,
                                suppress_text=force_tts)

        # Process queued messages for this context
        self._process_pending()

    def _watchdog(self, runner: ClaudeRunner,
                  no_output_timeout: int = 90,
                  max_total_timeout: int = 600) -> None:
        NO_OUTPUT_TIMEOUT = no_output_timeout
        MAX_TOTAL_TIMEOUT = max_total_timeout
        _notified_first_output = False

        while runner.running:
            time.sleep(5)
            if not runner.running:
                break
            now = time.time()
            has_output = bool(runner.accumulated_text or runner.result_text or runner.tool_log)
            is_thinking = runner.activity_type == "thinking"

            if (has_output or is_thinking) and not _notified_first_output:
                _notified_first_output = True

            if not has_output and not is_thinking:
                elapsed_start = now - runner.start_time
                if elapsed_start > NO_OUTPUT_TIMEOUT:
                    logger.warning("No-output timeout after %.0fs", elapsed_start)
                    self.send_message(f"⏰ Timeout — Claude não produziu nenhum output em {int(elapsed_start)}s. Cancelando...")
                    runner.cancel()
                    break
            else:
                elapsed_total = now - runner.start_time
                if elapsed_total > MAX_TOTAL_TIMEOUT:
                    logger.warning("Hard total timeout after %.0fs", elapsed_total)
                    self.send_message(f"⏰ Timeout — Claude rodou por mais de {int(elapsed_total//60)}min sem concluir. Cancelando...")
                    runner.cancel()
                    break
                elapsed = now - runner.last_activity
                if elapsed > self.timeout_seconds:
                    # Only trigger if process is dead — a live process means
                    # the agent is reasoning or waiting for API response
                    proc = runner.process
                    if proc and proc.poll() is None:
                        pass  # process alive = agent working, not idle
                    else:
                        logger.warning("Activity timeout after %.0fs of silence", elapsed)
                        self.send_message(f"⏰ Timeout — Claude ficou {int(elapsed)}s sem atividade. Cancelando...")
                        runner.cancel()
                        break

    def _update_reaction(self, runner: ClaudeRunner) -> None:
        ctx = self._ctx
        if not ctx or not ctx.user_msg_id:
            return
        emoji = _REACTION_MAP.get(runner.activity_type, "🤔")
        with ctx.lock:
            if emoji != ctx.last_reaction:
                self.set_reaction(ctx.user_msg_id, emoji)
                ctx.last_reaction = emoji

    def _stream_updates(self, runner_thread: threading.Thread, runner: ClaudeRunner,
                        routine_mode: bool = False) -> None:
        ctx = self._ctx
        _first_output_notified = False
        _checkin_interval = 15.0
        _last_checkin = time.time()
        _last_sent_text = ""

        while runner_thread.is_alive():
            runner_thread.join(timeout=1.0)
            now = time.time()

            if not routine_mode:
                if ctx and now - ctx.last_typing_time >= TYPING_INTERVAL:
                    action = _ACTIVITY_CHAT_ACTION.get(runner.activity_type, "typing")
                    self.send_typing(action)
                    ctx.last_typing_time = now
                self._update_reaction(runner)

            stream_msg = ctx.stream_msg_id if ctx else None
            if stream_msg and not routine_mode:
                snapshot = runner.get_snapshot()
                last_len = ctx.last_snapshot_len if ctx else 0
                has_new = len(snapshot) > last_len
                elapsed = int(now - runner.start_time)
                last_edit = ctx.last_edit_time if ctx else 0.0

                if has_new and not _first_output_notified:
                    _first_output_notified = True
                    logger.info("First output received from Claude")

                if has_new and now - last_edit >= STREAM_EDIT_INTERVAL:
                    display = snapshot
                    if len(display) > MAX_MESSAGE_LENGTH - 200:
                        display = "...\n" + display[-(MAX_MESSAGE_LENGTH - 200):]
                    display += f"\n\n⏳ _Processando... ({elapsed}s)_"
                    if len(snapshot) >= len(_last_sent_text):
                        self.edit_message(stream_msg, display)
                        if ctx:
                            ctx.last_edit_time = now
                            ctx.last_snapshot_len = len(snapshot)
                        _last_sent_text = snapshot

                elif now - _last_checkin >= _checkin_interval:
                    _last_checkin = now
                    if snapshot:
                        display = snapshot
                        if len(display) > MAX_MESSAGE_LENGTH - 200:
                            display = "...\n" + display[-(MAX_MESSAGE_LENGTH - 200):]
                        display += f"\n\n⏳ _Processando... ({elapsed}s)_"
                    else:
                        display = f"⏳ _Aguardando resposta do Claude... {elapsed}s_"
                    self.edit_message(stream_msg, display)

    def _finalize_response(self, session: Session, runner: ClaudeRunner, prompt: Optional[str] = None,
                           routine_mode: bool = False, force_tts: bool = False,
                           suppress_text: bool = False) -> None:
        ctx = self._ctx

        if runner.captured_session_id:
            session.session_id = runner.captured_session_id
            self.sessions.save()

        # Auto session management (interactive sessions only)
        if not routine_mode and session.session_id and runner.exit_code in (None, 0):
            if session.message_count >= AUTO_ROTATE_THRESHOLD:
                logger.info("Auto-rotate: session %s reached %d turns, starting fresh",
                            session.name, session.message_count)
                session.session_id = None
                session.message_count = 0
                self.sessions.save()
                self.send_message("🔄 _Sessão rotacionada automaticamente (%d turns)_" % AUTO_ROTATE_THRESHOLD)
            elif session.message_count > 0 and session.message_count % AUTO_COMPACT_INTERVAL == 0:
                self.send_message("🔄 _Auto-compact da sessão..._")
                self._auto_compact(session)

        logger.info(
            "Finalizing: result_text=%d chars, accumulated=%d chars, error=%s, stderr=%d chars, exit=%s",
            len(runner.result_text), len(runner.accumulated_text),
            repr(runner.error_text[:100]) if runner.error_text else "none",
            len(runner.stderr_text), runner.exit_code,
        )

        # Detect expired session
        if (runner.exit_code == 1 and not runner.result_text and not runner.accumulated_text
                and not runner.error_text and not runner.stderr_text
                and session.session_id and prompt is not None):
            logger.warning("Session ID %s appears expired — retrying", session.session_id)
            session.session_id = None
            self.sessions.save()
            stream_msg = ctx.stream_msg_id if ctx else None
            if stream_msg:
                self.edit_message(stream_msg, "⚠️ _Sessão expirada. Iniciando nova sessão..._")
            self._run_claude_prompt(prompt, _retry=True)
            return

        # Build final response
        final_text = runner.result_text or runner.accumulated_text or runner.error_text
        if not final_text:
            exit_code = runner.exit_code
            stderr = runner.stderr_text
            if stderr:
                final_text = _translate_error(stderr)
                if exit_code and exit_code not in (0, 130):
                    final_text += f"\n_exit code {exit_code}_"
            elif exit_code == 130:
                final_text = "🛑 Execução cancelada pelo usuário."
            elif exit_code == 2:
                final_text = "❌ *Argumento inválido no Claude CLI*"
            else:
                final_text = "⚠️ *Claude não retornou resposta*\nTente novamente em alguns instantes."

        if runner.cost_usd > 0:
            final_text += f"\n\n💰 Custo: ${runner.cost_usd:.4f} (total: ${runner.total_cost_usd:.4f})"
            _track_cost(runner.cost_usd)

        # Build copy-code button if response has a single dominant code block
        copy_markup = None
        copyable = self._extract_copyable_code(final_text)
        if copyable:
            copy_markup = {"inline_keyboard": [[
                {"text": "📋 Copiar código", "copy_text": {"text": copyable}}
            ]]}

        # Send final
        stream_msg = ctx.stream_msg_id if ctx else None
        if routine_mode:
            # NO_REPLY means Claude completed via tools with no text to send — silent success
            if final_text.strip() == "NO_REPLY":
                return
            # Cancellation in routine mode: skip sending (progress message is updated by caller)
            if runner.exit_code == 130 and not runner.result_text and not runner.accumulated_text:
                return
            if stream_msg:
                self.delete_message(stream_msg)
                if ctx:
                    ctx.stream_msg_id = None
            self.send_message(final_text, disable_notification=True)
        elif suppress_text:
            # Inline #voice: send only audio, suppress text message
            if stream_msg:
                self.delete_message(stream_msg)
                if ctx:
                    ctx.stream_msg_id = None
        else:
            sent = False
            if stream_msg and len(final_text) <= MAX_MESSAGE_LENGTH:
                sent = self.edit_message(stream_msg, final_text)
            if not sent:
                if stream_msg:
                    self.edit_message(stream_msg, "✅")
                # Large responses: send as document attachment instead of chunked messages
                if len(final_text) > self.DOCUMENT_THRESHOLD and '```' in final_text:
                    # Extract first meaningful line as caption
                    first_line = final_text.split('\n', 1)[0][:200].strip()
                    caption = f"{first_line}\n\n📎 _Resposta completa no arquivo anexo_"
                    self._send_as_document(final_text, filename="response.md", caption=caption)
                else:
                    self.send_message(final_text, reply_markup=copy_markup)

        # TTS: send voice message if enabled or forced (background, non-blocking)
        if force_tts and ctx:
            # Strip cost line from TTS — not useful as audio
            tts_text = re.sub(r'\n\n💰 Custo:.*$', '', final_text, flags=re.DOTALL).strip()
            if tts_text:
                self._maybe_send_tts(tts_text, ctx.chat_id, ctx.thread_id)

        if ctx:
            ctx.stream_msg_id = None
            if ctx.user_msg_id:
                self.set_reaction(ctx.user_msg_id, "")
                ctx.user_msg_id = None
                ctx.last_reaction = ""

    def _process_pending(self) -> None:
        ctx = self._ctx
        if not ctx:
            return
        while True:
            with ctx.pending_lock:
                if not ctx.pending:
                    break
                msg = ctx.pending.pop(0)
            if isinstance(msg, RoutineTask):
                self._execute_routine_task(msg)
            else:
                logger.info("Processing queued message: %s", str(msg)[:80])
                self._run_claude_prompt(msg)

    def _execute_routine_task(self, task: RoutineTask) -> None:
        """Execute a scheduled routine with model/agent/workspace override."""
        logger.info("Executing routine: %s (%s, model=%s, agent=%s)", task.name, task.time_slot, task.model, task.agent)
        session = self._get_session()
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

        # Routines always run with a fresh session (no prior conversation context)
        original_session_id = session.session_id
        session.session_id = None

        if changed:
            self.sessions.save()

        # Parse #voice from prompt text (same as interactive messages)
        task_prompt = task.prompt
        inline_tts = False
        if re.search(r'(?:^|\s)#voice\b', task_prompt, re.IGNORECASE):
            inline_tts = True
            task_prompt = re.sub(r'(?:^|\s)#voice\b', '', task_prompt, flags=re.IGNORECASE).strip()

        prompt = (f"[ROTINA: {task.name} | {task.time_slot}]\n"
                  f"Importante: execute a tarefa abaixo e envie apenas o output. "
                  f"Não adicione cabeçalho, confirmação de execução, nem frase dizendo que a rotina rodou.\n\n"
                  f"{task_prompt}")

        # Send progress message so it can be updated on failure/cancellation
        progress_msg_id = self.send_message(f"🔁 _Executando rotina *{task.name}*..._",
                                                   disable_notification=True)

        saved_timeout = self.timeout_seconds
        self.timeout_seconds = 300  # 5 min inactivity for routines
        try:
            self._run_claude_prompt(prompt, no_output_timeout=300, max_total_timeout=1200,
                                    routine_mode=True,
                                    system_prompt=None if task.minimal_context else SYSTEM_PROMPT,
                                    force_tts=task.voice or inline_tts)
            # Check if there was an error or cancellation
            runner = self.runner
            if runner.exit_code == 130:
                # Manually cancelled
                self.routine_state.set_status(task.name, task.time_slot, "cancelled")
                if progress_msg_id:
                    self.edit_message(progress_msg_id, f"🛑 Rotina *{task.name}* cancelada.")
            elif runner.error_text:
                self.routine_state.set_status(task.name, task.time_slot, "failed", runner.error_text[:200])
                if progress_msg_id:
                    self.edit_message(progress_msg_id, f"❌ Rotina *{task.name}* falhou: {runner.error_text[:200]}")
            else:
                self.routine_state.set_status(task.name, task.time_slot, "completed")
                # Success: delete progress message (output was already sent by _finalize_response)
                if progress_msg_id:
                    self.delete_message(progress_msg_id)
        except Exception as exc:
            logger.error("Routine %s failed: %s", task.name, exc)
            self.routine_state.set_status(task.name, task.time_slot, "failed", str(exc)[:200])
            if progress_msg_id:
                self.edit_message(progress_msg_id, f"❌ Rotina *{task.name}* falhou: {str(exc)[:300]}")
            else:
                self.send_message(f"❌ Rotina *{task.name}* falhou: {str(exc)[:300]}")
        finally:
            self.timeout_seconds = saved_timeout

        # Restore original model, agent, workspace, and session_id
        session.model = original_model
        session.agent = original_agent
        session.workspace = original_workspace
        session.session_id = original_session_id
        if changed:
            self.sessions.save()

    # -- Dangerous prompt approval --

    def _check_dangerous_prompt(self, prompt: str) -> Optional[str]:
        """Check if user prompt contains dangerous commands. Returns warning or None."""
        matches = []
        for pattern, description in DANGEROUS_PATTERNS:
            if re.search(pattern, prompt, re.IGNORECASE):
                matches.append(f"• {description}")
        if not matches:
            return None
        return "\n".join(matches)

    def _expire_approvals(self) -> None:
        """Remove pending approvals older than APPROVAL_EXPIRY_SECONDS."""
        now = time.time()
        expired = [k for k, v in self._pending_approvals.items()
                   if now - v["ts"] > APPROVAL_EXPIRY_SECONDS]
        for k in expired:
            del self._pending_approvals[k]

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
                "/cost": lambda: self.cmd_cost(),
                "/doctor": lambda: self.cmd_doctor(),
                "/stop": lambda: self.cmd_stop(arg),
                "/timeout": lambda: self.cmd_timeout(arg) if arg else self.send_message(f"ℹ️ Timeout atual: {self.timeout_seconds}s"),
                "/workspace": lambda: self.cmd_workspace(arg) if arg else self.send_message("❌ Use: `/workspace <path>`"),
                "/effort": lambda: self.cmd_effort(arg) if arg else self.send_message(f"ℹ️ Effort atual: {self.effort or 'padrão'}"),
                "/btw": lambda: self.cmd_btw(arg) if arg else self.send_message("❌ Use: `/btw <mensagem>`"),
                "/clear": lambda: self.cmd_clear(),
                "/important": lambda: self.cmd_important(),
                "/routine": lambda: self.cmd_routine(arg),
                "/run": lambda: self.cmd_run(arg),
                "/agent": lambda: self.cmd_agent(arg),
                "/skill": lambda: self.cmd_skill(arg),
                "/audio": lambda: self.cmd_audio(),
                "/voice": lambda: self.cmd_voice(arg),
            }

            fn = handler_map.get(cmd)
            if fn:
                fn()
            else:
                self.send_message(f"❌ Comando desconhecido: `{cmd}`")
            return

        # Regular text → send to Claude (queued per-context if runner busy)
        # Check for dangerous patterns first
        warning = self._check_dangerous_prompt(text)
        if warning:
            self._expire_approvals()
            approval_id = secrets.token_hex(8)
            ctx = self._ctx
            self._pending_approvals[approval_id] = {
                "prompt": text,
                "chat_id": self._chat_id,
                "thread_id": ctx.thread_id if ctx else None,
                "user_msg_id": user_msg_id,
                "ts": time.time(),
            }
            markup = {
                "inline_keyboard": [[
                    {"text": "✅ Aprovar", "callback_data": f"approve:{approval_id}"},
                    {"text": "❌ Cancelar", "callback_data": f"reject:{approval_id}"},
                ]]
            }
            self.send_message(
                f"⚠️ *Comando potencialmente perigoso detectado:*\n{warning}\n\n"
                f"Deseja enviar mesmo assim?",
                reply_markup=markup,
            )
            return

        # Inline #voice trigger: strip tag and enable TTS for this single message
        inline_tts = False
        if re.search(r'(?:^|\s)#voice\b', text, re.IGNORECASE):
            inline_tts = True
            text = re.sub(r'(?:^|\s)#voice\b', '', text, flags=re.IGNORECASE).strip()

        ctx = self._ctx
        if ctx:
            ctx.user_msg_id = user_msg_id
            self.set_reaction(user_msg_id, "👀")
            ctx.last_reaction = "👀"
        self._run_claude_prompt(text, force_tts=inline_tts)

    def _remove_keyboard(self, callback: Dict) -> None:
        """Remove inline keyboard from the message that had the buttons."""
        msg = callback.get("message", {})
        msg_id = msg.get("message_id")
        text = msg.get("text", "")
        if msg_id and text:
            self.edit_message(msg_id, text)

    def _handle_callback(self, callback: Dict) -> None:
        cb_id = callback.get("id", "")
        data = callback.get("data", "")

        # Voice pick: update selection without removing keyboard
        if data.startswith("voicepick:"):
            parts = data.split(":")
            if len(parts) == 3:
                pick_id, choice = parts[1], parts[2]
                entry = self._voice_picks.get(pick_id)
                if entry and not entry["resolved"]:
                    entry["force_tts"] = (choice == "audio")
                    self.answer_callback(cb_id, "🔊 Áudio" if choice == "audio" else "💬 Texto")
                    # Re-render buttons with updated checkmark
                    msg = callback.get("message", {})
                    msg_id = msg.get("message_id")
                    msg_text = msg.get("text", "")
                    if msg_id and msg_text:
                        is_voice = (choice == "audio")
                        new_markup = {"inline_keyboard": [[
                            {"text": f"🔊 Áudio{' ✓' if is_voice else ''}",
                             "callback_data": f"voicepick:{pick_id}:audio"},
                            {"text": f"💬 Texto{' ✓' if not is_voice else ''}",
                             "callback_data": f"voicepick:{pick_id}:text"},
                        ]]}
                        self.tg_request("editMessageText", {
                            "chat_id": self._chat_id,
                            "message_id": msg_id,
                            "text": self._sanitize_markdown_v2(msg_text),
                            "parse_mode": "MarkdownV2",
                            "reply_markup": new_markup,
                        })
                else:
                    self.answer_callback(cb_id)
            else:
                self.answer_callback(cb_id)
            return

        self._remove_keyboard(callback)

        if data.startswith("audio:"):
            locale = data.split(":", 1)[1]
            global HEAR_LOCALE
            HEAR_LOCALE = locale
            self.answer_callback(cb_id, f"Idioma: {locale}")
            self.send_message(f"✅ Idioma de transcrição alterado para `{locale}`")
        elif data.startswith("model:"):
            model = data.split(":", 1)[1]
            self.cmd_model_switch(model)
            self.answer_callback(cb_id, f"Modelo: {model}")
        elif data.startswith("agent:"):
            agent_id = data.split(":", 1)[1]
            self.answer_callback(cb_id)
            if agent_id == "create":
                self._run_agent_create_skill("")
            else:
                self.cmd_agent_switch(agent_id)
        elif data.startswith("agentmenu:"):
            action = data.split(":", 1)[1]
            self.answer_callback(cb_id)
            if action == "switch":
                self.cmd_agent_keyboard()
            elif action == "list":
                self._agent_list()
            elif action == "edit":
                self._agent_edit("")
            elif action == "import":
                self._agent_import("")
        elif data.startswith("routine:"):
            action = data.split(":", 1)[1]
            self.answer_callback(cb_id)
            if action == "list":
                self._routine_list()
            elif action == "status":
                self._routine_status()
            elif action == "new":
                self._routine_create("")
            elif action == "edit":
                self._routine_edit("")
        elif data.startswith("run:"):
            name = data.split(":", 1)[1]
            self.answer_callback(cb_id, f"Executando {name}...")
            self.cmd_run(name)
        elif data.startswith("stop:"):
            name = data.split(":", 1)[1]
            self.answer_callback(cb_id, f"Parando {name}...")
            if self._stop_routine_by_name(name):
                self.send_message(f"🛑 `{name}` cancelado.")
            else:
                self.send_message(f"ℹ️ `{name}` não está mais rodando.")
        elif data.startswith("skill:"):
            action = data.split(":", 1)[1]
            self.answer_callback(cb_id)
            if action == "list":
                self._skill_list()
            elif action == "edit":
                self._skill_edit("")
        elif data.startswith("approve:"):
            approval_id = data.split(":", 1)[1]
            entry = self._pending_approvals.pop(approval_id, None)
            if entry and time.time() - entry["ts"] <= APPROVAL_EXPIRY_SECONDS:
                self.answer_callback(cb_id, "Aprovado")
                ctx = self._ctx
                if ctx:
                    ctx.user_msg_id = entry.get("user_msg_id")
                    self.set_reaction(ctx.user_msg_id, "👀")
                    ctx.last_reaction = "👀"
                self._run_claude_prompt(entry["prompt"])
            else:
                self.answer_callback(cb_id, "Expirado")
                self.send_message("⏰ Aprovação expirada. Envie o comando novamente.")
        elif data.startswith("reject:"):
            approval_id = data.split(":", 1)[1]
            self._pending_approvals.pop(approval_id, None)
            self.answer_callback(cb_id, "Cancelado")
            self.send_message("🚫 Comando cancelado.")
        else:
            self.answer_callback(cb_id)

    def _extract_reply_context(self, msg: Dict) -> str:
        """If msg is a reply, return a context prefix with the original message content."""
        reply_to = msg.get("reply_to_message")
        if not reply_to:
            return ""

        sender = reply_to.get("from", {})
        is_bot = sender.get("is_bot", False)
        sender_name = "Bot" if is_bot else (sender.get("first_name") or sender.get("username") or "Usuário")

        content = reply_to.get("text") or reply_to.get("caption", "")
        if not content:
            return ""

        if len(content) > 500:
            content = content[:500] + "…"

        return f"[Contexto — reply à mensagem de {sender_name}]\n\"{content}\"\n---\n"

    def _process_update(self, update: Dict) -> None:
        # Callback queries (inline keyboards)
        if "callback_query" in update:
            cb = update["callback_query"]
            cb_msg = cb.get("message", {})
            cb_chat = str(cb_msg.get("chat", {}).get("id", ""))
            if self._is_authorized(cb_chat):
                thread_id = cb_msg.get("message_thread_id")
                self._ctx = self._get_context(cb_chat, thread_id)
                self._handle_callback(cb)
            return

        msg = update.get("message")
        if not msg:
            return

        chat_id = str(msg.get("chat", {}).get("id", ""))
        chat_type = msg.get("chat", {}).get("type", "private")

        # Authorization already handled in polling loop
        if not self._is_authorized(chat_id):
            return

        # Context and onboarding already handled in polling loop

        user_msg_id = msg.get("message_id")
        reply_ctx = self._extract_reply_context(msg)

        text = msg.get("text", "")
        if text:
            self._handle_text(reply_ctx + text, user_msg_id=user_msg_id)
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
                prompt = f"[Imagem recebida e salva em: {saved}]\n\n{reply_ctx}{caption}"
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
                    prompt = f"[Imagem recebida e salva em: {saved}]\n\n{reply_ctx}{caption}"
                    self._handle_text(prompt, user_msg_id=user_msg_id)
                else:
                    self.send_message("❌ Não consegui baixar a imagem.")
                return

        # Handle voice messages
        voice = msg.get("voice")
        if voice:
            self._handle_voice(msg, user_msg_id=user_msg_id)
            return

        # Handle audio files (forwarded audio, music, etc.)
        audio = msg.get("audio")
        if audio:
            self._handle_voice(msg, user_msg_id=user_msg_id)
            return

    # -- Polling loop --

    def _poll_updates(self) -> List[Dict]:
        data = {
            "offset": self._update_offset,
            "timeout": 30,
            "allowed_updates": ["message", "callback_query"],
        }
        resp = self.tg_request("getUpdates", data, timeout=45)
        if resp and resp.get("ok"):
            results = resp.get("result", [])
            if results:
                logger.info("Received %d updates (offset=%d)", len(results), self._update_offset)
            return results
        logger.warning("getUpdates returned: %s", resp)
        return []

    def _register_commands(self) -> None:
        """Register bot commands with Telegram, scoped by chat type."""
        # Full command set for private chats
        private_commands = [
            {"command": "help", "description": "Mostrar comandos disponiveis"},
            {"command": "status", "description": "Info da sessao e processo"},
            {"command": "new", "description": "Nova sessao"},
            {"command": "sessions", "description": "Listar sessoes"},
            {"command": "switch", "description": "Trocar sessao"},
            {"command": "sonnet", "description": "Usar modelo Sonnet"},
            {"command": "opus", "description": "Usar modelo Opus"},
            {"command": "haiku", "description": "Usar modelo Haiku"},
            {"command": "model", "description": "Escolher modelo"},
            {"command": "agent", "description": "Gerenciar agentes"},
            {"command": "skill", "description": "Gerenciar skills"},
            {"command": "routine", "description": "Criar ou listar rotinas"},
            {"command": "run", "description": "Executar rotina/pipeline manualmente"},
            {"command": "important", "description": "Registrar pontos importantes no diario"},
            {"command": "compact", "description": "Compactar contexto"},
            {"command": "stop", "description": "Cancelar execucao"},
            {"command": "timeout", "description": "Alterar timeout"},
            {"command": "workspace", "description": "Alterar diretorio de trabalho"},
            {"command": "effort", "description": "Nivel de esforco (low/medium/high)"},
            {"command": "audio", "description": "Idioma de transcricao de audio"},
            {"command": "voice", "description": "Ativar/desativar resposta por voz (TTS)"},
            {"command": "clear", "description": "Resetar sessao atual"},
        ]
        # Compact command set for groups (most-used commands only)
        group_commands = [
            {"command": "help", "description": "Mostrar comandos disponiveis"},
            {"command": "status", "description": "Info da sessao e processo"},
            {"command": "new", "description": "Nova sessao"},
            {"command": "stop", "description": "Cancelar execucao"},
            {"command": "model", "description": "Escolher modelo"},
            {"command": "voice", "description": "Ativar/desativar resposta por voz (TTS)"},
            {"command": "clear", "description": "Resetar sessao atual"},
        ]
        # Register scoped commands
        self.tg_request("setMyCommands", {
            "commands": private_commands,
            "scope": {"type": "all_private_chats"},
        })
        self.tg_request("setMyCommands", {
            "commands": group_commands,
            "scope": {"type": "all_group_chats"},
        })
        # Default scope fallback (same as private)
        self.tg_request("setMyCommands", {"commands": private_commands})

    def _start_control_server(self) -> None:
        bot = self

        # Generate and persist a bearer token for this session
        control_token = secrets.token_hex(32)
        try:
            CONTROL_TOKEN_FILE.write_text(control_token, encoding="utf-8")
            CONTROL_TOKEN_FILE.chmod(0o600)
            logger.info("Control server token written to %s", CONTROL_TOKEN_FILE)
        except Exception as exc:
            logger.error("Failed to write control token: %s", exc)

        class _Handler(http.server.BaseHTTPRequestHandler):
            def _check_auth(self) -> bool:
                """Validate X-Bot-Token header. Returns True if authorized."""
                token = self.headers.get("X-Bot-Token", "")
                if token != control_token:
                    self._respond(401, {"error": "unauthorized"})
                    return False
                return True

            def do_GET(self):
                if self.path == "/health":
                    active_sessions = len(bot.sessions.sessions)
                    active_runners = sum(
                        1 for ctx in list(bot._contexts.values())
                        if ctx.runner and ctx.runner.running
                    )
                    uptime = time.time() - bot._start_time
                    self._respond(200, {
                        "status": "ok",
                        "uptime_seconds": round(uptime, 1),
                        "active_sessions": active_sessions,
                        "active_runners": active_runners,
                        "scheduler_alive": bot.scheduler._thread.is_alive() if bot.scheduler._thread else False,
                    })
                else:
                    self._respond(404, {"error": "not found"})

            def do_POST(self):
                if not self._check_auth():
                    return
                try:
                    length = int(self.headers.get("Content-Length", 0))
                    body = json.loads(self.rfile.read(length)) if length else {}
                    if self.path == "/routine/run":
                        name = body.get("name", "")
                        time_slot = body.get("time_slot", "now")
                        md_file = ROUTINES_DIR / f"{name}.md"
                        if not md_file.exists():
                            self._respond(404, {"error": "routine not found"})
                            return
                        fm, routine_body = get_frontmatter_and_body(md_file)
                        if not fm or not routine_body:
                            self._respond(400, {"error": "invalid routine file"})
                            return
                        # Check if this is a pipeline
                        if str(fm.get("type", "routine")) == "pipeline":
                            bot.scheduler._enqueue_pipeline_from_file(
                                md_file, fm, routine_body, name,
                                str(fm.get("model", "sonnet")), time_slot)
                            self._respond(200, {"ok": True, "type": "pipeline"})
                            return
                        task = RoutineTask(
                            name=name,
                            prompt=routine_body,
                            model=str(fm.get("model", "sonnet")),
                            time_slot=time_slot,
                            agent=fm.get("agent"),
                            minimal_context=bool(fm.get("context") == "minimal"),
                        )
                        bot.routine_state.set_status(name, time_slot, "running")
                        bot._enqueue_routine(task)
                        self._respond(200, {"ok": True})
                    elif self.path == "/routine/stop":
                        name = body.get("name", "")
                        # Check pipelines first
                        with bot._active_pipelines_lock:
                            executor = bot._active_pipelines.get(name)
                        if executor:
                            executor.cancel()
                            self._respond(200, {"ok": True, "type": "pipeline"})
                            return
                        with bot._routine_contexts_lock:
                            ctx = bot._routine_contexts.get(name)
                        if ctx and ctx.runner and ctx.runner.running:
                            ctx.runner.cancel()
                            self._respond(200, {"ok": True})
                        else:
                            # Clean stale "running" state if routine already crashed
                            cleaned = False
                            state = bot.routine_state.get_today_state()
                            for slot, info in state.get(name, {}).items():
                                if isinstance(info, dict) and info.get("status") == "running":
                                    bot.routine_state.set_status(name, slot, "failed", "stopped (not running)")
                                    cleaned = True
                            if cleaned:
                                self._respond(200, {"ok": True, "cleaned": True})
                            else:
                                self._respond(404, {"error": "routine not running"})
                    elif self.path == "/pipeline/status":
                        name = body.get("name", "")
                        time_slot = body.get("time_slot", "")
                        if not time_slot:
                            # Find latest time_slot for today
                            state = bot.routine_state.get_today_state()
                            slots = state.get(name, {})
                            time_slot = max(slots.keys()) if slots else ""
                        if time_slot:
                            steps = bot.routine_state.get_pipeline_steps(name, time_slot)
                            self._respond(200, {"ok": True, "steps": steps})
                        else:
                            self._respond(404, {"error": "pipeline not found"})
                    else:
                        self._respond(404, {"error": "unknown endpoint"})
                except Exception as exc:
                    logger.error("Control server error: %s", exc)
                    self._respond(500, {"error": str(exc)})

            def _respond(self, code, data):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass  # suppress default HTTP logging

        try:
            server = http.server.HTTPServer(("127.0.0.1", CONTROL_PORT), _Handler)
            self._control_server = server
            threading.Thread(target=server.serve_forever, daemon=True, name="control-server").start()
            logger.info("Control server listening on 127.0.0.1:%d", CONTROL_PORT)
        except Exception as exc:
            self._control_server = None
            logger.error("Failed to start control server: %s", exc)

    def _notify_startup(self) -> None:
        for cid in self.authorized_ids:
            if not cid.startswith("-"):  # private chats only, not groups
                self.tg_request("sendMessage", {"chat_id": cid, "text": "🟢 Bot online"})

    def run(self) -> None:
        logger.info("Starting bot polling loop...")
        logger.info("Registering commands...")
        try:
            self._register_commands()
        except Exception as exc:
            logger.error("Failed to register commands: %s", exc)
        self._notify_startup()
        logger.info("Entering polling loop")
        _poll_backoff = 0
        while not self._stop_event.is_set():
            try:
                updates = self._poll_updates()
                _poll_backoff = 0  # reset on success
                for update in updates:
                    uid = update.get("update_id", 0)
                    if uid >= self._update_offset:
                        self._update_offset = uid + 1
                        self._save_offset(self._update_offset)
                    try:
                        msg = update.get("message", {})
                        chat_id = str(msg.get("chat", {}).get("id", ""))
                        user_id = str(msg.get("from", {}).get("id", ""))
                        chat_type = msg.get("chat", {}).get("type", "private")
                        thread_id = msg.get("message_thread_id")

                        # Auto-discovery: authorized user in unknown group → authorize group
                        if not self._is_authorized(chat_id) and "callback_query" not in update:
                            if user_id in self.authorized_ids and chat_type in ("group", "supergroup"):
                                self._authorize_chat(chat_id)
                                logger.info("Auto-authorized group %s via user %s", chat_id, user_id)
                            else:
                                logger.debug("Ignoring message from unauthorized chat %s", chat_id)
                                continue

                        # Check if this is a new topic before creating context
                        is_new_topic = (chat_id, thread_id) not in self._contexts
                        logger.info("Update: chat=%s thread=%s type=%s new_topic=%s", chat_id, thread_id, chat_type, is_new_topic)

                        # Set context for this message
                        self._ctx = self._get_context(chat_id, thread_id)

                        # Process update + onboarding in a thread so polling never blocks
                        def _handle(u=update, c=self._ctx, new=is_new_topic, ct=chat_type, tid=thread_id):
                            try:
                                self._ctx = c
                                # Onboarding: first message in a new group topic
                                if new and tid and ct in ("group", "supergroup"):
                                    agents = list_agents()
                                    if agents:
                                        self.cmd_agent_keyboard()
                                    else:
                                        markup = {"inline_keyboard": [[
                                            {"text": "🤖 Criar agente", "callback_data": "agent:create"},
                                            {"text": "⏭ Sem agente", "callback_data": "agent:none"},
                                        ]]}
                                        self.send_message(
                                            "👋 Novo tópico! Escolha um agente para este canal:",
                                            reply_markup=markup)
                                self._process_update(u)
                            except Exception as exc:
                                logger.error("Error processing update: %s", exc, exc_info=True)
                        threading.Thread(target=_handle, daemon=True).start()
                    except Exception as exc:
                        logger.error("Error handling update %s: %s", update.get("update_id"), exc, exc_info=True)
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt, shutting down.")
                break
            except Exception as exc:
                _poll_backoff = min(_poll_backoff + 1, 5)
                wait = min(5 * (2 ** _poll_backoff), 60)
                logger.error("Polling error (backoff=%ds): %s", wait, exc, exc_info=True)
                time.sleep(wait)

        logger.info("Polling loop exited.")

    def _consolidate_all_sessions(self) -> None:
        """Best-effort consolidation of all active sessions on shutdown."""
        with self._contexts_lock:
            contexts = list(self._contexts.items())
        for key, ctx in contexts:
            try:
                session_name = ctx.session_name
                if not session_name:
                    continue
                session = self.sessions.sessions.get(session_name)
                if not session or not session.session_id or session.message_count == 0:
                    continue
                if ctx.runner and ctx.runner.running:
                    continue
                saved_ctx = getattr(self, '_ctx', None)
                self._ctx = ctx
                try:
                    self._consolidate_session()
                finally:
                    self._ctx = saved_ctx
            except Exception as exc:
                logger.error("Shutdown consolidation failed for %s: %s", key, exc)

    def stop(self) -> None:
        logger.info("Stopping bot...")
        # Consolidate all active sessions before shutdown (best-effort)
        try:
            self._consolidate_all_sessions()
        except Exception as exc:
            logger.error("Error during shutdown consolidation: %s", exc)
        self._stop_event.set()
        # Stop the routine scheduler
        self.scheduler.stop()
        if self.scheduler._thread.is_alive():
            self.scheduler._thread.join(timeout=5)
        # Cancel all running contexts
        with self._contexts_lock:
            for ctx in self._contexts.values():
                if ctx.runner and ctx.runner.running:
                    ctx.runner.cancel()
        # Cancel active pipelines
        with self._active_pipelines_lock:
            for executor in self._active_pipelines.values():
                executor.cancel()
        # Shutdown control server
        if getattr(self, "_control_server", None):
            self._control_server.shutdown()
        logger.info("Bot stopped.")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Prevent "nested session" error when bot is started from inside Claude Code
    os.environ.pop("CLAUDECODE", None)

    # Validate required configuration before starting
    _missing = []
    if not TELEGRAM_BOT_TOKEN:
        _missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        _missing.append("TELEGRAM_CHAT_ID")
    if _missing:
        print(f"FATAL: Missing required config: {', '.join(_missing)}", file=sys.stderr)
        print(f"Set them in environment or in {_env_file}", file=sys.stderr)
        sys.exit(1)

    # Global safety net: log uncaught exceptions in daemon threads
    _orig_excepthook = getattr(threading, "excepthook", None)

    def _thread_excepthook(args):
        logger.error("Uncaught exception in thread %s: %s", args.thread and args.thread.name, args.exc_value, exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        if _orig_excepthook:
            _orig_excepthook(args)

    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_excepthook

    if "--run" in sys.argv or len(sys.argv) == 1:
        bot = ClaudeTelegramBot()

        def _sigterm_handler(signum, frame):
            logger.info("Received SIGTERM, initiating graceful shutdown.")
            bot.stop()

        signal.signal(signal.SIGTERM, _sigterm_handler)

        try:
            bot.run()
        except KeyboardInterrupt:
            bot.stop()
