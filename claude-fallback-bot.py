#!/usr/bin/env python3
"""
Telegram bot that provides remote access to Claude Code CLI.
Architecture: User <-> Telegram API <-> this script <-> Claude Code CLI (subprocess)
Only uses Python stdlib — no pip dependencies.
"""

BOT_VERSION = "3.6.2"  # fix: SIGTERM consolidation in thread — avoids FileNotFoundError from signal handler

import hmac
import hashlib
import http.server
import json
import socket
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
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make scripts/ importable so we can share helpers between the bot, the
# graph builder, and the optional MCP server. Single source of truth for
# the frontmatter parser lives in scripts/vault_frontmatter.py.
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

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
            elif _k == "ZAI_API_KEY":
                os.environ.setdefault("ZAI_API_KEY", _v)
            elif _k == "ZAI_BASE_URL":
                os.environ.setdefault("ZAI_BASE_URL", _v)
def _detect_claude_path() -> str:
    """Locate the claude CLI binary. Checks env var, then common install paths."""
    env_path = os.environ.get("CLAUDE_PATH")
    if env_path and os.path.isfile(env_path):
        return env_path
    # Common install locations (Apple Silicon brew, Intel brew, npm global, user local)
    for candidate in (
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
        os.path.expanduser("~/.local/bin/claude"),
        os.path.expanduser("~/.npm-global/bin/claude"),
    ):
        if os.path.isfile(candidate):
            return candidate
    # Fallback: search PATH
    from shutil import which
    found = which("claude")
    if found:
        return found
    # Last resort — return Apple Silicon default so error messages are informative
    return "/opt/homebrew/bin/claude"

CLAUDE_PATH = _detect_claude_path()
# Default workspace for interactive sessions on the Main agent. In v3.0 the
# Main agent is just another agent and owns its own folder directly at the
# vault root (vault/main/). No `Agents/` wrapper — the user's diagram shows
# agents as siblings of the shared CLAUDE.md / README.md / Tooling.md.
CLAUDE_WORKSPACE = os.environ.get(
    "CLAUDE_WORKSPACE",
    str(Path(__file__).resolve().parent / "vault" / "main"),
)

DATA_DIR = Path.home() / ".claude-bot"
SESSIONS_FILE = DATA_DIR / "sessions.json"
CONTEXTS_FILE = DATA_DIR / "contexts.json"
LOG_FILE = DATA_DIR / "bot.log"

VAULT_DIR = Path(__file__).resolve().parent / "vault"
ROUTINES_STATE_DIR = DATA_DIR / "routines-state"
TEMP_IMAGES_DIR = Path("/tmp/claude-bot-images")

# ---------------------------------------------------------------------------
# Per-agent path resolution (v3.1 layout)
# ---------------------------------------------------------------------------
# Every agent — including Main — lives directly under vault/<id>/ (no more
# Agents/ wrapper). Each agent owns its own Skills/, Routines/, Journal/,
# Reactions/, Lessons/, Notes/, workspace/. The vault root contains only the
# shared CLAUDE.md / README.md / Tooling.md plus the per-agent directories.
# Isolamento total: each agent only sees its own stuff.
#
# A directory is considered an agent iff it contains an `agent-<id>.md` file
# (the hub/index file that also carries the agent's metadata in frontmatter).
# v3.4: the per-agent hub file is named after the directory itself
# (`agent-main.md`, `agent-crypto-bro.md`, …) so every basename in the vault
# is unique and Obsidian's wikilink resolver picks the right one with bare
# `[[agent-main]]` syntax.
MAIN_AGENT_ID = "main"


# v3.3 sub-index naming: each agent's per-folder index file uses the
# `agent-<folder>` prefix so the LLM knows it's an Obsidian graph hub, not
# regular knowledge content. The bot's routine/skill/reaction iterators
# skip these filenames so the index files never get treated as items.
SUB_INDEX_FILENAMES = {
    "Skills":    "agent-skills.md",
    "Routines":  "agent-routines.md",
    "Journal":   "agent-journal.md",
    "Reactions": "agent-reactions.md",
    "Lessons":   "agent-lessons.md",
    "Notes":     "agent-notes.md",
}
# Names alone (filename only) for fast membership checks inside iterators.
SUB_INDEX_FILENAMES_SET = frozenset(SUB_INDEX_FILENAMES.values())

# Obsidian graph-view color palette for per-agent color groups.
# Each value is a 24-bit RGB integer (r<<16 | g<<8 | b) — the format Obsidian
# stores inside `.obsidian/graph.json`'s `colorGroups.color.rgb` field.
# When a new agent is created via /agent new or the Swift app, the user picks
# one of these names and the bot syncs the graph-view config automatically.
AGENT_COLOR_PALETTE: Dict[str, int] = {
    "grey":   0x9E9E9E,   # 10395294 — neutral default for Main
    "red":    0xEF4444,   # 15680580
    "orange": 0xFF9800,   # 16750848
    "yellow": 0xFBBF24,   # 16498468
    "green":  0x4CAF50,   # 5025616
    "teal":   0x14B8A6,   # 1358502
    "blue":   0x3B82F6,   # 3900150
    "purple": 0x9333EA,   # 9647082
}
DEFAULT_AGENT_COLOR = "grey"


def resolve_agent_color(color: Optional[str]) -> int:
    """Look up a palette name and return the 24-bit RGB int.

    Unknown names fall back to DEFAULT_AGENT_COLOR so the helper is safe to
    call on legacy agent-info.md files that don't carry the field.
    """
    if isinstance(color, str):
        key = color.strip().lower()
        if key in AGENT_COLOR_PALETTE:
            return AGENT_COLOR_PALETTE[key]
    return AGENT_COLOR_PALETTE[DEFAULT_AGENT_COLOR]


def _agent_id_or_main(agent_id: Optional[str]) -> str:
    """Normalize None/empty → 'main'. Trims whitespace."""
    if not agent_id:
        return MAIN_AGENT_ID
    agent_id = str(agent_id).strip()
    return agent_id or MAIN_AGENT_ID


def agent_base(agent_id: Optional[str]) -> Path:
    return VAULT_DIR / _agent_id_or_main(agent_id)


def agent_hub_filename(agent_id: Optional[str]) -> str:
    """Return the agent's hub-file basename: `agent-<id>.md` (v3.4 layout)."""
    return f"agent-{_agent_id_or_main(agent_id)}.md"


def agent_info_path(agent_id: Optional[str]) -> Path:
    """Return the absolute path to the agent's hub file (`<id>/agent-<id>.md`)."""
    return agent_base(agent_id) / agent_hub_filename(agent_id)


def routines_dir(agent_id: Optional[str]) -> Path:
    return agent_base(agent_id) / "Routines"


def skills_dir(agent_id: Optional[str]) -> Path:
    return agent_base(agent_id) / "Skills"


def journal_dir(agent_id: Optional[str]) -> Path:
    return agent_base(agent_id) / "Journal"


def reactions_dir(agent_id: Optional[str]) -> Path:
    return agent_base(agent_id) / "Reactions"


def lessons_dir(agent_id: Optional[str]) -> Path:
    return agent_base(agent_id) / "Lessons"


def notes_dir(agent_id: Optional[str]) -> Path:
    return agent_base(agent_id) / "Notes"


def activity_log_dir(agent_id: Optional[str]) -> Path:
    return journal_dir(agent_id) / ".activity"


def workspace_dir(agent_id: Optional[str]) -> Path:
    # v3.5: dot-prefixed so Obsidian (and other editors that hide dotfiles)
    # skip runtime pipeline data automatically — no userIgnoreFilters needed.
    return agent_base(agent_id) / ".workspace"


# Names at the vault root that are NEVER agents — shared files and internal
# directories. Any other top-level directory that contains `agent-<dir>.md`
# is treated as an agent.
_VAULT_RESERVED_NAMES = frozenset({
    "README.md", "CLAUDE.md", "Tooling.md", ".env", ".gitkeep",
    ".graphs", ".obsidian", ".claude", "Images", "__pycache__",
})


def iter_agent_ids() -> List[str]:
    """Yield every agent directory name directly under VAULT_DIR.

    A directory counts as an agent iff it contains ``agent-<dirname>.md``.
    """
    if not VAULT_DIR.is_dir():
        return []
    ids: List[str] = []
    for entry in sorted(VAULT_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in _VAULT_RESERVED_NAMES:
            continue
        hub = entry / f"agent-{entry.name}.md"
        if hub.is_file():
            ids.append(entry.name)
    return ids
TEMP_AUDIO_DIR = Path("/tmp/claude-bot-audio")
HEAR_BIN_DIR = DATA_DIR / "bin"

FFMPEG_PATH = os.environ.get("FFMPEG_PATH", "/opt/homebrew/bin/ffmpeg")
HEAR_PATH = os.environ.get("HEAR_PATH", "")
HEAR_LOCALE = os.environ.get("HEAR_LOCALE", "pt-BR")

# z.AI (GLM) credentials — second LLM provider via Anthropic-compatible gateway.
# When the requested model is a GLM variant, ClaudeRunner injects these into
# the claude CLI subprocess env so the same binary talks to z.AI instead of
# Anthropic. Empty ZAI_API_KEY => GLM models refuse to start (fail-loud).
ZAI_API_KEY = os.environ.get("ZAI_API_KEY", "")
ZAI_BASE_URL = os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/anthropic")

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

# Model → provider mapping. Provider determines which API the claude CLI talks to.
# "anthropic" = native Anthropic API. "zai" = z.AI gateway (Anthropic-compatible).
MODEL_PROVIDERS = {
    "sonnet": "anthropic",
    "opus": "anthropic",
    "haiku": "anthropic",
    "glm-5.1": "zai",
    "glm-4.7": "zai",
    "glm-4.5-air": "zai",
}
DEFAULT_MODEL = "sonnet"

def model_provider(model: str) -> str:
    """Returns 'zai' for GLM models, 'anthropic' otherwise. Prefix fallback
    so new glm-* variants work without code changes."""
    if model in MODEL_PROVIDERS:
        return MODEL_PROVIDERS[model]
    if model.startswith("glm-") or model.startswith("glm"):
        return "zai"
    return "anthropic"


def _start_zai_proxy(glm_model: str, zai_base_url: str, zai_api_key: str):
    """
    Start a local Anthropic-compatible HTTP proxy that rewrites the model field
    in requests, letting Claude CLI accept any GLM model name even though the CLI
    validates model names client-side against its own known-model list.

    Flow:
      Claude CLI  →  http://127.0.0.1:{port}  →  z.AI /api/anthropic
    Claude CLI sees a valid alias ("claude-sonnet-4-6"); the proxy quietly swaps
    the model to the requested GLM name before forwarding.

    Returns (server, port). Caller must call server.shutdown() after the run.
    """
    class _Handler(http.server.BaseHTTPRequestHandler):
        _glm_model = glm_model
        _base_url = zai_base_url.rstrip("/")
        _api_key = zai_api_key

        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                data["model"] = self.__class__._glm_model
                body = json.dumps(data).encode()
            except Exception:
                pass

            target = self.__class__._base_url + self.path
            hdrs = {
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
                "x-api-key": self.__class__._api_key,
                "anthropic-version": self.headers.get("anthropic-version", "2023-06-01"),
            }
            for h in ("anthropic-beta",):
                if self.headers.get(h):
                    hdrs[h] = self.headers[h]

            req = urllib.request.Request(target, data=body, headers=hdrs, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    self.send_response(resp.status)
                    for k, v in resp.headers.items():
                        if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                            self.send_header(k, v)
                    self.end_headers()
                    while True:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                            self.wfile.flush()
                        except (BrokenPipeError, ConnectionResetError):
                            break
            except urllib.error.HTTPError as exc:
                err_body = exc.read()
                self.send_response(exc.code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(err_body)))
                self.end_headers()
                self.wfile.write(err_body)
            except Exception as exc:
                payload = json.dumps({"error": str(exc)}).encode()
                self.send_response(502)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def log_message(self, fmt, *args):  # suppress noisy proxy logs
            pass

    # Bind on a random free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    srv = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True, name=f"zai-proxy-{port}")
    t.start()
    return srv, port


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
WEBHOOK_PORT = 27183                                # public via Tailscale Funnel; control server stays on CONTROL_PORT (local-only)
REACTION_SECRETS_FILE = DATA_DIR / "reaction-secrets.json"
REACTION_STATS_FILE = DATA_DIR / "reaction-stats.json"
WEBHOOK_MAX_BODY_BYTES = 1_048_576                  # 1 MB cap on webhook payloads
PIPELINE_WORKSPACE_MAX_AGE = 86400  # 24 hours in seconds
PIPELINE_ACTIVITY_FILE = DATA_DIR / "pipeline-activity.json"
SESSION_MAX_AGE_DAYS = 60
AUTO_COMPACT_INTERVAL = 25   # auto-compact every N turns in a session
AUTO_ROTATE_THRESHOLD = 80   # start fresh session after N turns
SKILL_HINTS_ENABLED = True   # inject top-N skill hints from vault/.graphs/graph.json
MAX_LOOP_ITERATIONS = 10     # hard cap for pipeline step loop (Ralph technique)
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

# --- Active Memory (inspired by OpenClaw v2026.4.10) ---
# Proactive vault context injection: before each interactive turn we score
# non-skill nodes in vault/.graphs/graph.json against the user's prompt and
# append a compact "## Active Memory" block with short excerpts from the top
# matches. Deterministic, no LLM cost, fail-open. Complements SKILL_HINTS_ENABLED
# which only surfaces skill names — Active Memory surfaces notes, references,
# indexes, routines, and pipelines, with actual content excerpts.
ACTIVE_MEMORY_ENABLED = True            # global default; can be flipped per session
ACTIVE_MEMORY_MAX_NODES = 3             # how many graph nodes to include per turn
ACTIVE_MEMORY_MAX_CHARS_PER_NODE = 400  # excerpt size from each matched file body
ACTIVE_MEMORY_BUDGET_MS = 200           # hard wall-clock budget; over budget => None
# Node types EXCLUDED from Active Memory: "skill" is already handled by
# _select_relevant_skills (SKILL_HINTS_ENABLED); "history" is churn-y log data.
ACTIVE_MEMORY_EXCLUDED_TYPES = frozenset({"skill", "history"})

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
    "Scan Lessons/ before similar tasks — previous failures drafted there so you don't repeat them. "
    "All vault .md files MUST have YAML frontmatter (title, description, type, created/updated, tags). "
    "Use the description field to scan files before reading them fully. "
    "\n\n"
    "## Journal — Proactive Recording\n"
    "You MUST write to the Journal DURING conversations, not just at the end. "
    "After completing any task or receiving important information, write a journal entry "
    "BEFORE responding to the user. Append to Journal/YYYY-MM-DD.md whenever:\n"
    "- A decision is made or a task is completed\n"
    "- You learn new information about the user's projects, preferences, or environment\n"
    "- A debugging session reaches a conclusion (root cause found, fix applied)\n"
    "- Configuration changes are made (files edited, settings changed, tools installed)\n"
    "- The user explicitly asks you to remember something\n"
    "- A routine or pipeline finishes executing\n"
    "Use the standard format: ## HH:MM — Short summary, followed by bullet points, then ---. "
    "If an agent is active, use the agent's own Journal/ directory instead. "
    "Journal entries are append-only — never overwrite existing content.\n"
    "When CREATING a new journal file, always include proper YAML frontmatter with BOTH "
    "opening AND closing `---` delimiters. The `description` field must summarize the actual "
    "content — never use a generic placeholder like 'Daily log for DATE'. "
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
• `/clone <nome>` — Clonar sessão atual (mesma thread do Claude, branch paralela)
• `/clear` — Resetar sessão atual
• `/compact` — Compactar contexto
• `/cost` — Custo e uso de tokens da sessão
• `/doctor` — Verificar saúde da instalação
• `/lint` — Auditar o vault (frontmatter, links, schedules)
• `/find <expr>` — Buscar no vault por frontmatter (ex: `type=routine model=opus`)
• `/indexes` — Regenerar marker blocks dos índices (`agent-skills.md`, `agent-routines.md`, ...) + sync color groups

⚙️ *Modelo*
• `/sonnet` — Usar Sonnet
• `/opus` — Usar Opus
• `/haiku` — Usar Haiku
• `/glm` — Usar GLM 4.7 (z.AI, requer `ZAI_API_KEY`)
• `/model` — Escolher modelo (teclado)

🔧 *Controle*
• `/stop` — Cancelar execução atual
• `/status` — Info da sessão e processo
• `/timeout <seg>` — Alterar timeout (padrão 600s)
• `/workspace <path>` — Alterar diretório de trabalho
• `/effort <low|medium|high>` — Nível de esforço de raciocínio
• `/btw <msg>` — Injetar mensagem ao Claude em execução (nativo)

📓 *Journal & Memory*
• `/important` — Registrar pontos importantes da sessão no diário
• `/lesson <texto>` — Registrar lição manual no agente atual (`<agente>/Lessons/`)
• `/active-memory [on|off|status]` — Injeção proativa de contexto do vault (padrão: on)

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
# Frontmatter parser (re-exported from scripts/vault_frontmatter.py)
# ---------------------------------------------------------------------------
# Single source of truth for frontmatter parsing lives in scripts/. Three
# in-tree parsers (bot, graph builder, query layer) used to drift; we now
# import from one shared module. The Swift FrontmatterParser remains
# separate but is parity-tested in tests/test_contracts.py.

from vault_frontmatter import (  # noqa: E402
    _indent_of,
    _parse_yaml_value,
    _read_block_scalar,
    _strip_quotes,
    get_frontmatter_and_body,
    parse_frontmatter,
    parse_pipeline_body,
)


_REACTION_STATS_LOCK = threading.Lock()


def _record_reaction_fire(
    reaction_id: str,
    *,
    forwarded: bool,
    routine_enqueued: bool,
    errors: int,
) -> None:
    """Append a fire event to the reaction stats sidecar.

    Stats file schema:
        {
          "reaction-id": {
            "last_fired_at": "2026-04-10T19:15:00+00:00",
            "fire_count": 42,
            "last_status": "ok" | "error",
            "last_forwarded": bool,
            "last_routine_enqueued": bool
          },
          ...
        }
    """
    from datetime import datetime, timezone

    try:
        with _REACTION_STATS_LOCK:
            stats: Dict[str, Any] = {}
            if REACTION_STATS_FILE.exists():
                try:
                    stats = json.loads(REACTION_STATS_FILE.read_text(encoding="utf-8")) or {}
                except Exception:
                    stats = {}
            entry = stats.get(reaction_id) or {}
            entry["last_fired_at"] = datetime.now(timezone.utc).isoformat()
            entry["fire_count"] = int(entry.get("fire_count", 0)) + 1
            entry["last_status"] = "ok" if errors == 0 else "error"
            entry["last_forwarded"] = bool(forwarded)
            entry["last_routine_enqueued"] = bool(routine_enqueued)
            stats[reaction_id] = entry
            REACTION_STATS_FILE.write_text(
                json.dumps(stats, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            try:
                REACTION_STATS_FILE.chmod(0o644)
            except Exception:
                pass
    except Exception as exc:
        logger.error("Failed to record reaction fire for %s: %s", reaction_id, exc)


def _load_reaction_secrets() -> Dict[str, Dict[str, Any]]:
    """Load per-reaction secrets from ~/.claude-bot/reaction-secrets.json.

    File format: {"reaction-id": {"token": "rxn_...", "hmac_secret": "..."}}
    Missing file → returns {}. Malformed → logs and returns {}.
    """
    if not REACTION_SECRETS_FILE.exists():
        return {}
    try:
        return json.loads(REACTION_SECRETS_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.error("Failed to load reaction secrets: %s", exc)
        return {}


def _find_reaction_file(name: str) -> Optional[Path]:
    """Locate a reaction .md file by stem across every Agents/<id>/Reactions/."""
    for aid in iter_agent_ids():
        candidate = reactions_dir(aid) / f"{name}.md"
        if candidate.is_file():
            return candidate
    return None


def load_reaction(name: str) -> Optional[Dict[str, Any]]:
    """Load a reaction by id. Returns merged frontmatter + secrets + body.

    Reactions now live per-agent under Agents/<id>/Reactions/. The reaction
    name space is flat across agents (the first match wins), and the owning
    agent is injected into the returned `action` dict so webhook dispatch
    knows which agent context to use.

    Returns None if file missing, disabled, or frontmatter invalid.
    """
    md_file = _find_reaction_file(name)
    if md_file is None:
        return None
    owner_agent = md_file.parent.parent.name if md_file.parent.parent.parent == VAULT_DIR else MAIN_AGENT_ID
    fm, body = get_frontmatter_and_body(md_file)
    if not fm:
        return None
    if not fm.get("enabled", False):
        return None
    if str(fm.get("type", "")).lower() != "reaction":
        return None

    auth_fm = fm.get("auth") if isinstance(fm.get("auth"), dict) else {}
    action_fm = fm.get("action") if isinstance(fm.get("action"), dict) else {}

    secrets = _load_reaction_secrets().get(name, {})

    # Folder ownership wins over frontmatter for agent routing, matching
    # the rule we already enforce for routines and skills.
    action_agent = action_fm.get("agent") or owner_agent

    return {
        "id": name,
        "title": str(fm.get("title", name)),
        "description": str(fm.get("description", "")),
        "enabled": True,
        "auth": {
            "mode": str(auth_fm.get("mode", "token")).lower(),
            "hmac_header": str(auth_fm.get("hmac_header", "X-Signature")),
            "hmac_algo": str(auth_fm.get("hmac_algo", "sha256")).lower(),
            "token": secrets.get("token"),
            "hmac_secret": secrets.get("hmac_secret"),
        },
        "action": {
            "routine": action_fm.get("routine"),
            "forward": bool(action_fm.get("forward", False)),
            "forward_template": action_fm.get("forward_template"),
            "agent": action_agent,
        },
        "owner_agent": owner_agent,
        "body": body,
    }


# ---------------------------------------------------------------------------
# Pipeline body parser is imported from vault_frontmatter at the top of this
# file (single source of truth shared with the linter and the indexer).
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Routine data structures
# ---------------------------------------------------------------------------

DAY_MAP = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

_INTERVAL_RE = re.compile(r'^(\d+)([mhdw])$')
_INTERVAL_UNITS = {'m': 60, 'h': 3600, 'd': 86400, 'w': 604800}


def _parse_interval(val: str) -> Optional[Dict]:
    """Parse interval string like '4h', '30m', '3d', '2w' into dict with seconds.

    Returns {'value': int, 'unit': str, 'seconds': int} or None if invalid.
    """
    m = _INTERVAL_RE.match(str(val).strip().lower())
    if not m:
        return None
    value, unit = int(m.group(1)), m.group(2)
    if value <= 0:
        return None
    return {'value': value, 'unit': unit, 'seconds': value * _INTERVAL_UNITS[unit]}


@dataclass
class RoutineTask:
    name: str
    prompt: str
    model: str
    time_slot: str
    agent: Optional[str] = None
    minimal_context: bool = False
    voice: bool = False
    effort: Optional[str] = None
    # When set, the raw webhook payload is injected into the routine prompt
    # (see _execute_routine_task). Used by Reactions that trigger routines via
    # the webhook server.
    webhook_payload: Optional[str] = None


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
    effort: Optional[str] = None
    # Ralph loop — re-run the step until `loop_until` appears in the output or
    # `loop_max_iterations` is reached. Inspired by frankbria/ralph-claude-code.
    # None in loop_until disables looping for this step. When enabled, each
    # iteration appends the previous output as context to the next iteration
    # so the agent can make progress. on_no_progress="abort" (default) fails
    # the step if two consecutive iterations produce identical output;
    # "continue" keeps looping regardless.
    loop_until: Optional[str] = None
    loop_max_iterations: int = 5
    loop_on_no_progress: str = "abort"  # "abort" or "continue"

    @property
    def resolved_filename(self) -> str:
        """Return the output filename: custom if set, otherwise {id}.md."""
        return self.output_file if self.output_file else f"{self.id}.md"

    @property
    def has_loop(self) -> bool:
        return bool(self.loop_until)


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
    effort: Optional[str] = None


# ---------------------------------------------------------------------------
# Hot cache per agent (rolling continuity context across sessions)
# ---------------------------------------------------------------------------
#
# Each agent gets a `vault/Agents/{id}/.context.md` file that captures the
# agent's rolling state — active topics, recent decisions, open threads.
#
# - On session start: the body is injected into the frozen context block so
#   the next session resumes with prior context (see _build_frozen_context).
# - After auto-compact: the bot fires a structured "summarize state" prompt
#   and rewrites .context.md with the new snapshot, plus extracts durable
#   concepts to the agent's Notes folder (Agents/<id>/Notes/).
# - On /important: the user can manually trigger a hot-cache update.
#
# Pattern inspired by claude-obsidian's "hot cache" (Karpathy LLM Wiki).

# Hard cap on the size of the hot cache body injected into a fresh session.
# Keeps the prefix-cache window stable and avoids blowing the system prompt.
HOT_CACHE_MAX_CHARS = 6000  # roughly 1500 tokens at 4 chars/token

_AGENT_CONTEXT_LOCK = threading.Lock()


def _agent_context_path(agent_id: str) -> Path:
    """Resolve the rolling context file for an agent."""
    return VAULT_DIR / agent_id / ".context.md"


def _read_agent_context(agent_id: Optional[str]) -> str:
    """Return the body (post-frontmatter) of the agent's .context.md file.

    Returns "" when the agent has no rolling context yet, the file is missing,
    or the agent_id is None (Main Agent has no per-agent context).
    """
    if not agent_id:
        return ""
    path = _agent_context_path(agent_id)
    if not path.is_file():
        return ""
    try:
        _, body = get_frontmatter_and_body(path)
    except Exception as exc:
        logger.error("Failed to read agent context for %s: %s", agent_id, exc)
        return ""
    if len(body) > HOT_CACHE_MAX_CHARS:
        return body[:HOT_CACHE_MAX_CHARS] + "\n…(truncated)"
    return body


def _write_agent_context(agent_id: str, body: str) -> None:
    """Write the rolling state to vault/Agents/{id}/.context.md.

    Creates the file with proper frontmatter on first write so vault_query
    and the linter recognize it as a `type: context` node.
    """
    path = _agent_context_path(agent_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    body = body.strip()
    if len(body) > HOT_CACHE_MAX_CHARS:
        body = body[:HOT_CACHE_MAX_CHARS]
    with _AGENT_CONTEXT_LOCK:
        # Read existing frontmatter to preserve `created`
        created = today
        if path.is_file():
            try:
                fm, _ = get_frontmatter_and_body(path)
                created = str(fm.get("created", today))
            except Exception:
                pass
        text = (
            f"---\n"
            f'title: "Context — {agent_id}"\n'
            f'description: "Rolling state of active topics, recent decisions, '
            f'and open threads for {agent_id}. Auto-maintained by the bot."\n'
            f"type: context\n"
            f"created: {created}\n"
            f"updated: {today}\n"
            f"tags: [context, agent, {agent_id}]\n"
            f"---\n\n"
            f"{body}\n"
        )
        path.write_text(text, encoding="utf-8")


# Regex for extracting durable concepts from the LLM response.
# Format expected: `- {slug} | {high|medium|low} | {one-line summary}`
_DURABLE_CONCEPT_RE = re.compile(
    r"^\s*[-*]\s*([a-z0-9][a-z0-9_-]*)\s*\|\s*(high|medium|low)\s*\|\s*(.+?)\s*$",
    re.IGNORECASE,
)


def _extract_durable_concepts(llm_text: str) -> List[Dict[str, str]]:
    """Parse a hot-cache update response and return a list of durable concepts.

    Looks for a `## Durable concepts` section. Each entry must follow:
        - {slug} | {confidence} | {summary}

    Slugs are normalized to kebab-case. Only entries with valid syntax are
    returned. Confidence values outside high/medium/low are dropped.
    """
    out: List[Dict[str, str]] = []
    in_section = False
    for raw_line in llm_text.split("\n"):
        line = raw_line.rstrip()
        if line.lstrip().startswith("##"):
            in_section = "durable concepts" in line.lower()
            continue
        if not in_section:
            continue
        m = _DURABLE_CONCEPT_RE.match(line)
        if not m:
            continue
        slug = re.sub(r"[^a-z0-9-]+", "-", m.group(1).lower()).strip("-")
        if not slug:
            continue
        out.append(
            {
                "slug": slug,
                "confidence": m.group(2).lower(),
                "summary": m.group(3).strip(),
            }
        )
    return out


def _strip_durable_concepts_section(llm_text: str) -> str:
    """Return llm_text with the `## Durable concepts` section removed.

    Used so the section doesn't bloat the .context.md body — durable concepts
    are stored in Notes/, the context file keeps only Active topics, Recent
    decisions, and Open threads.
    """
    out_lines: List[str] = []
    skipping = False
    for line in llm_text.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("##"):
            skipping = "durable concepts" in stripped.lower()
            if skipping:
                continue
        if skipping:
            continue
        out_lines.append(line)
    return "\n".join(out_lines).rstrip()


def _promote_durable_concept_to_notes(
    concept: Dict[str, str], agent_id: str
) -> Optional[Path]:
    """Create or update Agents/<agent>/Notes/{slug}.md for a high-confidence concept.

    Returns the file path on success, None when skipped or failed.
    Guardrails:
    - Only promotes confidence=high
    - If the file already exists with the same agent attribution, append
      a `## Update YYYY-MM-DD` section instead of overwriting
    - Always tags the note with `agent:{agent_id}` so cross-agent concepts
      can be tracked
    """
    if concept.get("confidence") != "high":
        return None
    slug = concept["slug"]
    summary = concept["summary"]
    agent_notes = notes_dir(agent_id)
    agent_notes.mkdir(parents=True, exist_ok=True)
    path = agent_notes / f"{slug}.md"
    today = time.strftime("%Y-%m-%d")
    try:
        if path.is_file():
            # Append an Update section, never overwrite
            with path.open("a", encoding="utf-8") as f:
                f.write(f"\n## Update {today}\n\n{summary}\n")
        else:
            text = (
                f"---\n"
                f'title: "{slug}"\n'
                f'description: "{summary[:140]}"\n'
                f"type: note\n"
                f"created: {today}\n"
                f"updated: {today}\n"
                f"tags: [note, auto-extracted, {agent_id}]\n"
                f"---\n\n"
                f"[[Notes]]\n\n"
                f"{summary}\n"
            )
            path.write_text(text, encoding="utf-8")
        return path
    except OSError as exc:
        logger.error("Failed to promote concept %s to Notes/: %s", slug, exc)
        return None


# ---------------------------------------------------------------------------
# Routine execution history rollup
# ---------------------------------------------------------------------------

_HISTORY_LOCK = threading.Lock()


def _find_routine_file(name: str) -> Optional[Path]:
    """Locate a routine .md file by stem, searching every agent's Routines/ folder.

    Routine file names are unique across the vault (enforced by convention),
    so the first match wins. Returns None if not found.
    """
    for aid in iter_agent_ids():
        candidate = routines_dir(aid) / f"{name}.md"
        if candidate.is_file():
            return candidate
    return None


def _append_routine_history(
    name: str,
    time_slot: str,
    status: str,
    error: Optional[str],
    kind: str = "routine",
) -> None:
    """Append a queryable history record to Agents/<agent>/Routines/.history/YYYY-MM.md.

    Each terminal-state transition (completed/failed/cancelled) writes one
    `## YYYY-MM-DD HH:MM — name` block under the owning agent. If the routine
    file cannot be located (e.g. deleted mid-run) the record goes to main.
    """
    routine_path = _find_routine_file(name)
    if routine_path is not None:
        # Owning agent is the name of the Agents/<id>/ folder two levels up.
        owner_agent = routine_path.parent.parent.name
    else:
        owner_agent = MAIN_AGENT_ID
    history_dir = routines_dir(owner_agent) / ".history"
    history_dir.mkdir(parents=True, exist_ok=True)
    today = time.strftime("%Y-%m-%d")
    month = time.strftime("%Y-%m")
    history_path = history_dir / f"{month}.md"

    # Pull a few useful fields from the routine file (best-effort — if the
    # file moved or got renamed mid-run we still write the record).
    fm_model = ""
    fm_agent = ""
    if routine_path is not None and routine_path.exists():
        try:
            fm, _ = get_frontmatter_and_body(routine_path)
            fm_model = str(fm.get("model", ""))
            fm_agent = str(fm.get("agent", ""))
        except Exception:
            pass

    icon = {"completed": "✓", "failed": "✗", "cancelled": "⊘"}.get(status, "?")

    record_lines = [
        f"## {today} {time_slot} — {name}",
        f"- status: {status} {icon}",
        f"- kind: {kind}",
    ]
    if fm_model:
        record_lines.append(f"- model: {fm_model}")
    if fm_agent:
        record_lines.append(f"- agent: {fm_agent}")
    if error:
        # Single-line, truncated, indent code-friendly
        clean = error.replace("\n", " ")[:200]
        record_lines.append(f"- error: {clean}")
    record_lines.append("")  # blank line separator
    record = "\n".join(record_lines)

    with _HISTORY_LOCK:
        if not history_path.exists():
            header = (
                f"---\n"
                f"title: \"Execution history {month}\"\n"
                f"description: \"Routine and pipeline execution log for {month}. "
                f"Auto-appended by the bot on terminal status transitions.\"\n"
                f"type: history\n"
                f"created: {today}\n"
                f"updated: {today}\n"
                f"tags: [history, routines]\n"
                f"---\n\n"
            )
            history_path.write_text(header + record + "\n", encoding="utf-8")
        else:
            with history_path.open("a", encoding="utf-8") as f:
                f.write(record + "\n")


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
        # Outside the state lock — history writes use their own lock and
        # touch a different file, so this avoids holding the state lock
        # across disk I/O.
        if status in ("completed", "failed", "cancelled"):
            try:
                _append_routine_history(routine_name, time_slot, status, error, kind="routine")
            except Exception as exc:
                logger.error("History rollup failed for %s: %s", routine_name, exc)

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
        # Outside the state lock — see set_status for rationale.
        if status in ("completed", "failed", "cancelled"):
            try:
                _append_routine_history(name, time_slot, status, error, kind="pipeline")
            except Exception as exc:
                logger.error("History rollup failed for pipeline %s: %s", name, exc)

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


class IntervalStateManager:
    """Tracks cross-day last-run timestamps for interval-based routines.

    Stored in ~/.claude-bot/routines-state/intervals.json:
    { "routine-name": { "last_run_at": <unix_timestamp_float> } }
    """

    def __init__(self) -> None:
        self._path = ROUTINES_STATE_DIR / "intervals.json"
        self._lock = threading.Lock()

    def get_last_run(self, routine_name: str) -> Optional[float]:
        """Returns Unix timestamp of last run, or None if never run."""
        return self._load().get(routine_name, {}).get("last_run_at")

    def record_run(self, routine_name: str) -> None:
        """Record current time as last run for this routine."""
        with self._lock:
            data = self._load()
            data[routine_name] = {"last_run_at": time.time()}
            self._save(data)

    def _load(self) -> Dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save(self, data: Dict) -> None:
        self._path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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


# ---------------------------------------------------------------------------
# Vault Checkpoints (git stash of vault/ changes before routine execution)
# ---------------------------------------------------------------------------

def vault_checkpoint_create(label: str) -> Optional[str]:
    """Stash uncommitted vault/ changes before a routine runs.

    Runs git from the repo root targeting vault/ only, so changes to
    bot code are never stashed. Returns the stash ref ("stash@{0}") or
    None when there are no changes to stash / git not available.
    """
    repo_root = Path(__file__).resolve().parent
    if not (repo_root / ".git").is_dir():
        return None
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    msg = f"[checkpoint] {label} @ {ts}"
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "stash", "push", "-u", "-m", msg, "--", "vault/"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            logger.warning("Checkpoint create failed: %s", result.stderr.strip())
            return None
        if "No local changes" in result.stdout or "nothing to save" in result.stdout:
            return None  # clean working tree — nothing to checkpoint
        logger.info("Checkpoint created for '%s': %s", label, msg)
        return "stash@{0}"
    except Exception as exc:
        logger.warning("Checkpoint create error: %s", exc)
        return None


def vault_checkpoint_restore(stash_ref: str) -> bool:
    """Pop a vault checkpoint to roll back failed routine changes."""
    repo_root = Path(__file__).resolve().parent
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "stash", "pop", stash_ref],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            logger.info("Checkpoint restored: %s", stash_ref)
            return True
        logger.error("Checkpoint restore failed: %s", result.stderr.strip())
        return False
    except Exception as exc:
        logger.error("Checkpoint restore error: %s", exc)
        return False


def vault_checkpoint_drop(stash_ref: str) -> None:
    """Drop a checkpoint after a successful routine (keeps stash list clean)."""
    repo_root = Path(__file__).resolve().parent
    try:
        subprocess.run(
            ["git", "-C", str(repo_root), "stash", "drop", stash_ref],
            capture_output=True, timeout=10,
        )
    except Exception:
        pass


def _iter_routine_files() -> List[Path]:
    """Yield every *.md file under <agent>/Routines/ (skipping the agent-routines.md index)."""
    results: List[Path] = []
    for aid in iter_agent_ids():
        rdir = routines_dir(aid)
        if not rdir.is_dir():
            continue
        for md_file in sorted(rdir.glob("*.md")):
            if md_file.name in SUB_INDEX_FILENAMES_SET:
                continue
            results.append(md_file)
    return results


class RoutineScheduler:
    """Background thread that scans every Agents/<id>/Routines/ every 60s and enqueues matching routines."""

    def __init__(self, state: RoutineStateManager, enqueue_fn, enqueue_pipeline_fn=None,
                 notify_fn=None) -> None:
        self.state = state
        self.interval_state = IntervalStateManager()
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
            f"Corrija o arquivo em `<agente>/Routines/{routine_name}.md`"
        )
        try:
            self._notify_fn(msg)
        except Exception as exc:
            logger.error("Failed to notify about invalid routine %s: %s", routine_name, exc)

    def _check_routines(self) -> None:
        now_time = time.strftime("%H:%M")
        now_day_idx = time.localtime().tm_wday  # 0=Monday
        today_str = time.strftime("%Y-%m-%d")

        # Reset notification tracking at day boundary + daily cleanup
        if self._notified_date != today_str:
            self._notified_invalid_routines.clear()
            self._notified_date = today_str
            _cleanup_stale_pipeline_workspaces()

        for md_file in _iter_routine_files():
            try:
                fm, body = get_frontmatter_and_body(md_file)
                # The folder structure is now the source of truth for agent
                # ownership. Agents/<id>/Routines/foo.md → agent=id.
                owning_agent = md_file.parent.parent.name
                if not fm or not body:
                    continue
                # Skip index files (e.g. agent-routines.md) — they are Obsidian hubs, not routines
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
                # Check expiry
                until = schedule.get("until") or fm.get("until")
                if until and str(until) < today_str:
                    continue
                routine_name = md_file.stem
                model = str(fm.get("model", "sonnet"))
                routine_type = str(fm.get("type", "routine"))
                interval_str = str(schedule.get("interval", "")).strip()

                # Validate frontmatter agent field against folder ownership.
                fm_agent_raw = fm.get("agent")
                if fm_agent_raw and str(fm_agent_raw).strip() and str(fm_agent_raw).strip() != owning_agent:
                    logger.warning(
                        "Routine %s: frontmatter agent=%r disagrees with folder owner %r — using folder",
                        md_file.name, fm_agent_raw, owning_agent,
                    )

                if interval_str:
                    # --- Interval mode: run every N minutes/hours/days/weeks ---
                    interval = _parse_interval(interval_str)
                    if not interval:
                        logger.warning("Routine %s skipped — invalid 'schedule.interval': %s",
                                       md_file.name, interval_str)
                        self._notify_invalid_routine(
                            md_file.stem,
                            [f"Campo `schedule.interval` inválido: `{interval_str}`. Use ex: `30m`, `4h`, `3d`, `2w`"],
                        )
                        continue
                    # Check day filter (optional — limit interval to certain weekdays)
                    days = schedule.get("days", ["*"])
                    if isinstance(days, list) and "*" not in days:
                        if not any(DAY_MAP.get(d.lower().strip(), -1) == now_day_idx for d in days):
                            continue
                    # Check monthdays filter (optional — limit to specific days of month)
                    monthdays = schedule.get("monthdays", [])
                    if monthdays:
                        now_monthday = time.localtime().tm_mday
                        if not any(int(d) == now_monthday for d in monthdays if str(d).isdigit()):
                            continue
                    # Check if enough time has passed since last run
                    last_run = self.interval_state.get_last_run(routine_name)
                    if last_run is not None and (time.time() - last_run) < interval['seconds']:
                        continue
                    t_str = now_time
                    logger.info("Interval routine matched: %s (every %s, type=%s)", routine_name, interval_str, routine_type)
                    self.interval_state.record_run(routine_name)
                    if routine_type == "pipeline" and self._enqueue_pipeline:
                        self._enqueue_pipeline_from_file(md_file, fm, body, routine_name, model, t_str)
                    else:
                        self.state.set_status(routine_name, t_str, "running")
                        _effort_raw = str(fm.get("effort", "")).lower().strip()
                        task = RoutineTask(
                            name=routine_name,
                            prompt=body,
                            model=model,
                            time_slot=t_str,
                            agent=owning_agent,
                            minimal_context=bool(fm.get("context") == "minimal"),
                            voice=bool(fm.get("voice", False)),
                            effort=_effort_raw if _effort_raw in ("low", "medium", "high") else None,
                        )
                        self._enqueue(task)
                else:
                    # --- Clock mode: run at specific times ---
                    if not isinstance(schedule.get("times"), list) or not schedule["times"]:
                        logger.warning("Routine %s skipped — 'schedule.times' must be a non-empty list",
                                       md_file.name)
                        self._notify_invalid_routine(
                            md_file.stem,
                            ["Campo `schedule.times` deve ser uma lista não-vazia (ou use `schedule.interval`)"],
                        )
                        continue
                    # Check day filter
                    days = schedule.get("days", ["*"])
                    if isinstance(days, list) and "*" not in days:
                        if not any(DAY_MAP.get(d.lower().strip(), -1) == now_day_idx for d in days):
                            continue
                    # Check monthdays filter
                    monthdays = schedule.get("monthdays", [])
                    if monthdays:
                        now_monthday = time.localtime().tm_mday
                        if not any(int(d) == now_monthday for d in monthdays if str(d).isdigit()):
                            continue
                    # Check time
                    for t in schedule["times"]:
                        t_str = str(t).strip()
                        if t_str == now_time and not self.state.is_executed(routine_name, t_str):
                            logger.info("Routine matched: %s at %s (type=%s)", routine_name, t_str, routine_type)
                            if routine_type == "pipeline" and self._enqueue_pipeline:
                                self._enqueue_pipeline_from_file(md_file, fm, body, routine_name, model, t_str)
                            else:
                                self.state.set_status(routine_name, t_str, "running")
                                _effort_raw = str(fm.get("effort", "")).lower().strip()
                                task = RoutineTask(
                                    name=routine_name,
                                    prompt=body,
                                    model=model,
                                    time_slot=t_str,
                                    agent=owning_agent,
                                    minimal_context=bool(fm.get("context") == "minimal"),
                                    voice=bool(fm.get("voice", False)),
                                    effort=_effort_raw if _effort_raw in ("low", "medium", "high") else None,
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
        # Folder is the source of truth: Agents/<id>/Routines/foo.md → agent=id.
        owning_agent = md_file.parent.parent.name if md_file.parent.parent.parent == VAULT_DIR else MAIN_AGENT_ID
        fm_agent_raw = fm.get("agent")
        if fm_agent_raw and str(fm_agent_raw).strip() and str(fm_agent_raw).strip() != owning_agent:
            logger.warning(
                "Pipeline %s: frontmatter agent=%r disagrees with folder owner %r — using folder",
                md_file.name, fm_agent_raw, owning_agent,
            )
        default_agent = owning_agent
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
                    # Safety net: strip any trailing wikilink lines (legacy Obsidian
                    # graph metadata). New step files MUST NOT contain wikilinks at
                    # all — the parent pipeline owns the relationship via its
                    # `## Steps` section. See vault/CLAUDE.md "Pipeline graph".
                    if prompt_text:
                        _lines = prompt_text.split("\n")
                        while _lines:
                            _last = _lines[-1].strip()
                            if not _last:
                                _lines.pop()
                                continue
                            if re.match(r'^(?:\(.*\[\[.+\]\].*\)|(?:[\w-]+\s*:\s*)?\[\[.+\]\])$', _last):
                                _lines.pop()
                                continue
                            break
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

            _step_effort = str(s.get("effort", "")).lower().strip()
            # Ralph loop config — flat keys (the pipeline parser is line-based).
            # loop_until: substring that marks "done"; empty/None disables loops.
            loop_until_raw = s.get("loop_until")
            loop_until = str(loop_until_raw) if loop_until_raw not in (None, "") else None
            try:
                loop_max = int(s.get("loop_max_iterations", 5))
            except (TypeError, ValueError):
                loop_max = 5
            if loop_max < 1:
                loop_max = 1
            if loop_max > MAX_LOOP_ITERATIONS:
                logger.warning("Pipeline %s step %s: loop_max_iterations=%d exceeds hard cap %d — clamping",
                               routine_name, step_id, loop_max, MAX_LOOP_ITERATIONS)
                loop_max = MAX_LOOP_ITERATIONS
            _np_raw = str(s.get("loop_on_no_progress", "abort")).lower().strip()
            loop_np = _np_raw if _np_raw in ("abort", "continue") else "abort"
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
                effort=_step_effort if _step_effort in ("low", "medium", "high") else None,
                loop_until=loop_until,
                loop_max_iterations=loop_max,
                loop_on_no_progress=loop_np,
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

        _effort_raw = str(fm.get("effort", "")).lower().strip()
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
            effort=_effort_raw if _effort_raw in ("low", "medium", "high") else None,
        )
        steps_info = [{"id": s.id, "output_type": s.output_type} for s in steps]
        self.state.set_pipeline_status(routine_name, t_str, "running", steps_init=steps_info)
        self._enqueue_pipeline(task)

    def list_today_routines(self) -> List[Dict]:
        """List all routines scheduled for today with their status."""
        now_day_idx = time.localtime().tm_wday
        today_str = time.strftime("%Y-%m-%d")
        state = self.state.get_today_state()
        routines = []

        for md_file in _iter_routine_files():
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
                routine_name = md_file.stem
                interval_str = str(schedule.get("interval", "")).strip()

                if interval_str:
                    # Interval mode: include if day/monthday filters match
                    days = schedule.get("days", ["*"])
                    if isinstance(days, list) and "*" not in days:
                        if not any(DAY_MAP.get(d.lower().strip(), -1) == now_day_idx for d in days):
                            continue
                    monthdays = schedule.get("monthdays", [])
                    if monthdays:
                        now_monthday = time.localtime().tm_mday
                        if not any(int(d) == now_monthday for d in monthdays if str(d).isdigit()):
                            continue
                    today_runs = state.get(routine_name, {})
                    if today_runs:
                        for slot, entry in sorted(today_runs.items()):
                            r_entry = {
                                "name": routine_name,
                                "title": fm.get("title", routine_name),
                                "time": slot,
                                "model": fm.get("model", "sonnet"),
                                "status": entry.get("status", "pending"),
                                "error": entry.get("error"),
                                "type": str(fm.get("type", "routine")),
                                "interval": interval_str,
                            }
                            if entry.get("type") == "pipeline":
                                r_entry["type"] = "pipeline"
                                r_entry["steps"] = entry.get("steps", {})
                            routines.append(r_entry)
                    else:
                        routines.append({
                            "name": routine_name,
                            "title": fm.get("title", routine_name),
                            "time": f"~{interval_str}",
                            "model": fm.get("model", "sonnet"),
                            "status": "pending",
                            "error": None,
                            "type": str(fm.get("type", "routine")),
                            "interval": interval_str,
                        })
                else:
                    # Clock mode
                    days = schedule.get("days", ["*"])
                    if isinstance(days, list) and "*" not in days:
                        if not any(DAY_MAP.get(d.lower().strip(), -1) == now_day_idx for d in days):
                            continue
                    monthdays = schedule.get("monthdays", [])
                    if monthdays:
                        now_monthday = time.localtime().tm_mday
                        if not any(int(d) == now_monthday for d in monthdays if str(d).isdigit()):
                            continue
                    times = schedule.get("times", [])
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


def _track_cost(cost_usd: float, model: Optional[str] = None) -> None:
    """Append cost to weekly tracker in ~/.claude-bot/costs.json, tagged by provider.

    Schema:
        {
          "current_week": "2026-W15",
          "weeks": {
            "2026-W15": {
              "total": 1.23,          # all providers combined (back-compat)
              "days":  {"2026-04-07": 0.12, ...},         # combined (back-compat)
              "providers": {
                "anthropic": {"total": 0.80, "days": {...}},
                "zai":       {"total": 0.43, "days": {...}}
              }
            }
          }
        }

    Old entries (without "providers") are treated as all-anthropic when read.
    """
    provider = model_provider(model) if model else "anthropic"
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
        # Combined totals (back-compat)
        week["total"] = round(week["total"] + cost_usd, 6)
        day = week["days"].setdefault(today, 0.0)
        week["days"][today] = round(day + cost_usd, 6)
        # Per-provider totals
        providers = week.setdefault("providers", {})
        p = providers.setdefault(provider, {"total": 0.0, "days": {}})
        p["total"] = round(p["total"] + cost_usd, 6)
        p_day = p["days"].setdefault(today, 0.0)
        p["days"][today] = round(p_day + cost_usd, 6)
        data["current_week"] = week_key
        # Prune old weeks (keep last 4)
        weeks = sorted(data["weeks"].keys())
        while len(weeks) > 4:
            del data["weeks"][weeks.pop(0)]
        COSTS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_weekly_cost(provider: Optional[str] = None) -> dict:
    """Read current week cost data. Returns {week, total, today}.

    If provider is None, returns combined totals (back-compat).
    If provider is "anthropic" or "zai", returns that provider's slice.
    """
    try:
        if not COSTS_FILE.exists():
            return {"week": "", "total": 0.0, "today": 0.0}
        data = json.loads(COSTS_FILE.read_text(encoding="utf-8"))
        week_key = time.strftime("%G-W%V")
        week = data.get("weeks", {}).get(week_key, {})
        today = time.strftime("%Y-%m-%d")
        if provider is None:
            return {
                "week": week_key,
                "total": week.get("total", 0.0),
                "today": week.get("days", {}).get(today, 0.0),
            }
        p = week.get("providers", {}).get(provider, {})
        return {
            "week": week_key,
            "total": p.get("total", 0.0),
            "today": p.get("days", {}).get(today, 0.0),
        }
    except Exception:
        return {"week": "", "total": 0.0, "today": 0.0}


# ---------------------------------------------------------------------------
# Activity log — vault-based session tracking for journal audit
# ---------------------------------------------------------------------------


def _log_activity(entry: dict) -> None:
    """Append one JSONL line to Agents/<agent>/Journal/.activity/YYYY-MM-DD.jsonl.

    The owning agent is taken from `entry["agent"]` (defaults to "main"). This
    keeps the activity log per-agent so the journal auditor and compound
    engineering tooling can find failures attached to the right agent.
    """
    try:
        agent_id = entry.get("agent") or MAIN_AGENT_ID
        adir = activity_log_dir(agent_id)
        adir.mkdir(parents=True, exist_ok=True)
        today = time.strftime("%Y-%m-%d")
        path = adir / f"{today}.jsonl"
        entry.setdefault("time", time.strftime("%H:%M"))
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("Activity log write failed: %s", exc)


# ---------------------------------------------------------------------------
# Lessons — compound-engineering failure drafts
# ---------------------------------------------------------------------------


def _sanitize_lesson_slug(name: str) -> str:
    """Normalize a routine/pipeline name into a filename-safe slug.

    Collapses any sequence of non [a-zA-Z0-9_-] chars (INCLUDING dots) into a
    single hyphen to prevent path traversal sequences like `..` from surviving.
    """
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip())
    slug = slug.strip("-_") or "unknown"
    return slug[:80]


def record_lesson_draft(trigger_name: str, error_summary: str,
                        kind: str = "routine",
                        agent_id: Optional[str] = None) -> Optional[Path]:
    """Append a draft lesson to Agents/<agent>/Lessons/draft-YYYY-MM-DD-{name}.md on failure.

    Idempotent per day+trigger: if the draft file already exists it appends a new
    `## HH:MM — error` section instead of overwriting. Returns the file Path on
    success, None on failure (errors are logged but never raised).

    `agent_id` defaults to 'main' when omitted; callers that know the owning
    agent (e.g. routine/pipeline execution) should pass it explicitly.
    """
    try:
        agent_lessons = lessons_dir(agent_id)
        agent_lessons.mkdir(parents=True, exist_ok=True)
        today = time.strftime("%Y-%m-%d")
        slug = _sanitize_lesson_slug(trigger_name)
        path = agent_lessons / f"draft-{today}-{slug}.md"
        safe_error = (error_summary or "(no error text)").strip()
        if len(safe_error) > 1500:
            safe_error = safe_error[:1500] + "... [truncated]"
        if path.exists():
            # Append another occurrence — the draft is still pending
            now_hm = time.strftime("%H:%M")
            addendum = (
                f"\n\n## {now_hm} — Additional failure\n\n"
                f"```\n{safe_error}\n```\n"
            )
            with open(path, "a", encoding="utf-8") as f:
                f.write(addendum)
            return path
        # Fresh draft
        frontmatter = (
            "---\n"
            f"title: \"Draft lesson — {trigger_name}\"\n"
            f"description: Auto-draft from {kind} failure; needs user to fill Fix and Detect sections.\n"
            "type: lesson\n"
            "status: draft\n"
            f"trigger: {trigger_name}\n"
            f"kind: {kind}\n"
            f"date: {today}\n"
            f"created: {today}\n"
            f"updated: {today}\n"
            "tags: [lesson, draft, postmortem]\n"
            "---\n\n"
        )
        body = (
            f"# Draft lesson — {trigger_name}\n\n"
            "## What went wrong\n\n"
            f"```\n{safe_error}\n```\n\n"
            "## Fix\n\n"
            "TODO\n\n"
            "## How to detect next time\n\n"
            "TODO\n"
        )
        path.write_text(frontmatter + body, encoding="utf-8")
        logger.info("Lesson draft recorded: %s", path)
        return path
    except Exception as exc:
        logger.error("Failed to record lesson draft for %s: %s", trigger_name, exc)
        return None


# ---------------------------------------------------------------------------
# Skill hint injection — graph.json-based keyword scoring
# ---------------------------------------------------------------------------

# Short common words that must not contribute to the skill match score.
# English + Portuguese — the bot runs bilingual by default.
_SKILL_HINT_STOPWORDS = frozenset({
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "for",
    "on", "at", "by", "be", "as", "are", "was", "with", "that", "this",
    "from", "but", "not", "can", "you", "me", "my", "we", "us", "your",
    "o", "os", "a", "as", "um", "uma", "uns", "umas", "e", "ou", "de",
    "do", "da", "dos", "das", "em", "no", "na", "nos", "nas", "por",
    "para", "com", "como", "que", "se", "foi", "ser", "estar", "ter",
    "isso", "esse", "essa", "eu", "eu", "voce", "você", "ele", "ela",
})


def _select_relevant_skills(prompt: str, agent_id: Optional[str] = None,
                             max_n: int = 3) -> List[str]:
    """Return up to `max_n` skill names scored against the prompt via graph.json.

    **Isolamento total:** only skills belonging to ``agent_id`` (or main) are
    candidates. A node is considered owned by ``agent_id`` when its
    ``source_file`` starts with ``<agent_id>/Skills/``.

    Reads ``vault/.graphs/graph.json`` (zero LLM cost) and scores each matching
    skill node by simple keyword overlap between the prompt and the skill's
    name/description/tags.

    Returns an empty list when the feature is disabled, the graph is missing
    or malformed, or no skill scores above zero. All I/O is wrapped and errors
    are logged — callers should NOT expect exceptions.
    """
    if not SKILL_HINTS_ENABLED:
        return []
    if not prompt or not prompt.strip():
        return []
    graph_path = VAULT_DIR / ".graphs" / "graph.json"
    if not graph_path.is_file():
        return []  # New users won't have a graph yet — silent, expected
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Skill hint: could not read %s: %s", graph_path, exc)
        return []
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(nodes, list):
        logger.warning("Skill hint: graph.json has no 'nodes' list — got %s", type(nodes).__name__)
        return []

    # Tokenize prompt → filtered lowercase word set
    tokens = re.findall(r"[\w-]+", prompt.lower())
    prompt_words = {
        t for t in tokens
        if len(t) > 3 and t not in _SKILL_HINT_STOPWORDS
    }
    if not prompt_words:
        return []

    agent_skills_prefix = f"{_agent_id_or_main(agent_id)}/Skills/"
    scored: List[tuple] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type", "")).lower()
        source_file = str(node.get("source_file", ""))
        # Only this agent's skills qualify.
        if not source_file.startswith(agent_skills_prefix):
            continue
        if node_type and node_type != "skill":
            continue
        name = str(node.get("label") or node.get("name") or "")
        if not name and source_file:
            name = Path(source_file).stem
        description = str(node.get("description", ""))
        tags = node.get("tags", []) or []
        if not isinstance(tags, list):
            tags = []
        haystack = " ".join([name, description, " ".join(str(t) for t in tags)]).lower()
        haystack_tokens = set(re.findall(r"[\w-]+", haystack))
        score = 0
        for w in prompt_words:
            if w in haystack_tokens:
                score += 2
            elif any(w in ht for ht in haystack_tokens):
                score += 1
        if score > 0:
            display_name = Path(source_file).stem if source_file else name
            scored.append((score, display_name))

    scored.sort(key=lambda x: (-x[0], x[1]))
    return [s[1] for s in scored[:max_n]]


# ---------------------------------------------------------------------------
# Active Memory — proactive vault context injection (OpenClaw v2026.4.10 idea)
# ---------------------------------------------------------------------------

# In-process cache for graph.json — mtime-checked so the daily vault-graph-update
# routine transparently refreshes us. Keyed by absolute path so tests pointing
# at different VAULT_DIRs don't collide.
_active_memory_graph_cache: Dict[str, Dict[str, Any]] = {}


def _active_memory_load_graph(graph_path: Path) -> Optional[Dict[str, Any]]:
    """Load graph.json with mtime-based caching. Returns None if missing/broken."""
    try:
        mtime = graph_path.stat().st_mtime
    except OSError:
        return None
    key = str(graph_path)
    cached = _active_memory_graph_cache.get(key)
    if cached and cached.get("mtime") == mtime:
        return cached.get("data")
    try:
        data = json.loads(graph_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Active Memory: could not read %s: %s", graph_path, exc)
        return None
    _active_memory_graph_cache[key] = {"mtime": mtime, "data": data}
    return data


def _active_memory_read_excerpt(source_file: str, max_chars: int) -> str:
    """Read up to max_chars from the BODY of a vault file (stripping frontmatter).

    Best-effort: returns empty string on any error. Files that start with '---'
    have their YAML frontmatter block skipped so the excerpt contains actual prose.
    """
    try:
        path = VAULT_DIR / source_file
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    # Strip YAML frontmatter block if present
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            text = text[end + 4:].lstrip()
    text = text.strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "…"
    # Collapse internal whitespace so the block stays compact in the prompt
    text = re.sub(r"\s+", " ", text)
    return text


def _active_memory_lookup(prompt: str, agent_id: Optional[str] = None) -> Optional[str]:
    """Active Memory: deterministic vault graph lookup before main Claude turn.

    **Isolamento total:** only nodes whose ``source_file`` lives under
    ``<agent_id>/`` (directly at the vault root) are candidates — the Main
    agent's content is NOT implicitly shared with named agents.

    Returns a compact "## Active Memory" block to append to the system prompt,
    or None if disabled / no matches / any error / over budget.

    Inspired by OpenClaw v2026.4.10 Active Memory plugin — but deterministic:
    no LLM call, no token cost, ~50ms typical. Reuses vault/.graphs/graph.json
    (regenerated daily by vault-graph-update). Filters out node types already
    covered elsewhere (skills → _select_relevant_skills; history → churn).

    Fail-open: any exception is logged at WARNING and the helper returns None
    so the main Claude turn proceeds unchanged.
    """
    if not ACTIVE_MEMORY_ENABLED:
        return None
    if not prompt or not prompt.strip():
        return None
    t0 = time.monotonic()

    def _over_budget() -> bool:
        elapsed_ms = (time.monotonic() - t0) * 1000
        if elapsed_ms > ACTIVE_MEMORY_BUDGET_MS:
            logger.warning("Active Memory: budget exceeded (%.1fms)", elapsed_ms)
            return True
        return False

    graph_path = VAULT_DIR / ".graphs" / "graph.json"
    if not graph_path.is_file():
        return None  # New users without a graph — expected, not an error.
    data = _active_memory_load_graph(graph_path)
    if not isinstance(data, dict):
        return None
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return None

    # Tokenize prompt, reusing the same stopword set and rules as the skill hint
    # helper so the two stay aligned without duplicating logic.
    tokens = re.findall(r"[\w-]+", prompt.lower())
    prompt_words = {
        t for t in tokens
        if len(t) > 3 and t not in _SKILL_HINT_STOPWORDS
    }
    if not prompt_words:
        return None

    agent_prefix = f"{_agent_id_or_main(agent_id)}/"
    agent_skills_prefix = f"{agent_prefix}Skills/"
    scored: List[tuple] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        node_type = str(node.get("type", "")).lower()
        if node_type in ACTIVE_MEMORY_EXCLUDED_TYPES:
            continue
        source_file = str(node.get("source_file", ""))
        if not source_file:
            continue
        # Isolamento total: the candidate must live under THIS agent's folder.
        if not source_file.startswith(agent_prefix):
            continue
        # Skill files are already surfaced by the skill-hint helper.
        if source_file.startswith(agent_skills_prefix):
            continue
        label = str(node.get("label") or node.get("id") or Path(source_file).stem)
        description = str(node.get("description", ""))
        tags = node.get("tags", []) or []
        if not isinstance(tags, list):
            tags = []
        haystack = " ".join([label, description, " ".join(str(t) for t in tags)]).lower()
        haystack_tokens = set(re.findall(r"[\w-]+", haystack))
        score = 0
        for w in prompt_words:
            if w in haystack_tokens:
                score += 2
            elif any(w in ht for ht in haystack_tokens):
                score += 1
        if score > 0:
            scored.append((score, {
                "source_file": source_file,
                "label": label,
                "description": description,
                "type": node_type or "note",
            }))

    if not scored:
        return None
    if _over_budget():
        return None

    scored.sort(key=lambda x: (-x[0], x[1]["source_file"]))
    top = [s[1] for s in scored[:ACTIVE_MEMORY_MAX_NODES]]

    lines: List[str] = [
        "## Active Memory",
        "",
        "The vault has these entries that may be relevant to the user's message — "
        "read the full file only if you actually need it:",
        "",
    ]
    for item in top:
        if _over_budget():
            return None
        excerpt = _active_memory_read_excerpt(
            item["source_file"], ACTIVE_MEMORY_MAX_CHARS_PER_NODE
        )
        desc = item["description"] or item["label"]
        if excerpt:
            lines.append(
                f"- [[{item['source_file']}]] ({item['type']}) — {desc} "
                f"· excerpt: \"{excerpt}\""
            )
        else:
            lines.append(
                f"- [[{item['source_file']}]] ({item['type']}) — {desc}"
            )

    elapsed_ms = (time.monotonic() - t0) * 1000
    logger.info(
        "Active Memory: injected %d entries in %.1fms", len(top), elapsed_ms
    )
    return "\n".join(lines)


def record_manual_lesson(text: str, agent_id: Optional[str] = None) -> Optional[Path]:
    """Append a user-supplied lesson to Agents/<agent>/Lessons/manual-YYYY-MM-DD-HHMM.md.

    Returns the file Path on success, None on failure. `agent_id` defaults to
    'main'; callers with an active session should pass `session.agent`.
    """
    try:
        agent_lessons = lessons_dir(agent_id)
        agent_lessons.mkdir(parents=True, exist_ok=True)
        now = time.strftime("%Y-%m-%d-%H%M")
        today = time.strftime("%Y-%m-%d")
        # Collision-safe: if two lessons arrive in the same minute, append a counter
        base_path = agent_lessons / f"manual-{now}.md"
        path = base_path
        counter = 1
        while path.exists():
            counter += 1
            path = agent_lessons / f"manual-{now}-{counter}.md"
        body = (text or "").strip()
        if not body:
            raise ValueError("lesson text is empty")
        frontmatter = (
            "---\n"
            f"title: \"Manual lesson — {now}\"\n"
            "description: User-supplied lesson captured via /lesson command on Telegram.\n"
            "type: lesson\n"
            "status: recorded\n"
            f"date: {today}\n"
            f"created: {today}\n"
            f"updated: {today}\n"
            "tags: [lesson, manual]\n"
            "---\n\n"
        )
        markdown = (
            f"# Manual lesson\n\n"
            "## Context\n\n"
            f"{body}\n\n"
            "## Fix\n\nTODO\n\n"
            "## How to detect next time\n\nTODO\n"
        )
        path.write_text(frontmatter + markdown, encoding="utf-8")
        logger.info("Manual lesson recorded: %s", path)
        return path
    except Exception as exc:
        logger.error("Failed to record manual lesson: %s", exc)
        return None


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
    # `agent` is optional at the type level for sessions.json backcompat:
    # pre-v3.0 sessions persisted `agent=None` to mean "Main". On load we
    # normalize None → "main" so the rest of the code can rely on a string.
    # New sessions should always carry an explicit agent id.
    agent: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    message_count: int = 0
    total_turns: int = 0
    # Active Memory (OpenClaw v2026.4.10 inspired) — per-session toggle for
    # the proactive vault context injection. Default True; users can disable
    # with /active-memory off when they want zero auto-injection.
    active_memory: bool = True


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
                # v3.0 backcompat: pre-v3 sessions stored agent=None for Main.
                # Normalize to the explicit "main" string so downstream helpers
                # can treat every session as having a known owning agent.
                if not filtered.get("agent"):
                    filtered["agent"] = MAIN_AGENT_ID
                # Same story for workspace — older sessions may have pointed
                # at vault/ directly. Rewrite to Agents/main/ only if the file
                # is the legacy vault root.
                ws = filtered.get("workspace")
                legacy_vault_ws = str(VAULT_DIR)
                if ws == legacy_vault_ws or ws == legacy_vault_ws + "/":
                    filtered["workspace"] = str(agent_base(filtered["agent"]))
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

    def create(self, name: str, agent: Optional[str] = None) -> Session:
        agent_id = _agent_id_or_main(agent)
        s = Session(
            name=name,
            agent=agent_id,
            workspace=str(agent_base(agent_id)),
        )
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

    def clone(self, source_name: str, dest_name: str) -> Optional[Session]:
        """Clone an existing session into a new name.

        The clone shares the same Claude session_id, model, workspace, and agent
        — meaning it continues the source's Claude-side conversation thread.
        Cloning lets the user branch a session and try divergent prompts while
        still keeping the original intact as a rollback point.

        message_count is carried over so context utilization stats are accurate
        (the cloned Claude session has the same token history). total_turns and
        created_at are reset because the clone is a NEW Session record.

        Returns the new Session, or None if source is missing / dest already exists.
        """
        if source_name not in self.sessions:
            return None
        if dest_name in self.sessions:
            return None
        src = self.sessions[source_name]
        clone = Session(
            name=dest_name,
            session_id=src.session_id,      # SAME Claude session — continues the thread
            model=src.model,
            workspace=src.workspace,
            agent=src.agent,
            created_at=time.time(),         # fresh creation timestamp for eviction
            message_count=src.message_count,  # carry over so auto-compact stats stay accurate
            total_turns=0,                  # fresh turn counter for this branch
        )
        self.sessions[dest_name] = clone
        self.active_session = dest_name
        self.save()
        return clone

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
# Error Classification & Auto-Recovery
# ---------------------------------------------------------------------------

class ErrorKind(Enum):
    OVERLOADED      = "overloaded"        # retry com backoff
    RATE_LIMIT      = "rate_limit"        # retry com backoff longo
    CONTEXT_TOO_LONG = "context_too_long" # compact + retry
    TIMEOUT         = "timeout"           # retry 1x
    CONNECTION      = "connection"        # retry 1x
    CLI_CRASH       = "cli_crash"         # retry 1x
    AUTH            = "auth"              # sem recovery
    NOT_FOUND       = "not_found"         # sem recovery
    CREDIT          = "credit"            # sem recovery
    UNKNOWN         = "unknown"           # sem recovery


class RecoveryAction(Enum):
    RETRY               = "retry"
    RETRY_AFTER_COMPACT = "retry_after_compact"
    BACKOFF_RETRY       = "backoff_retry"
    ABORT               = "abort"


# (action, backoff_seconds, max_attempts)
_RECOVERY_MAP: Dict[ErrorKind, tuple] = {
    ErrorKind.OVERLOADED:        (RecoveryAction.BACKOFF_RETRY,       30, 1),
    ErrorKind.RATE_LIMIT:        (RecoveryAction.BACKOFF_RETRY,       90, 1),
    ErrorKind.CONTEXT_TOO_LONG:  (RecoveryAction.RETRY_AFTER_COMPACT,  0, 1),
    ErrorKind.TIMEOUT:           (RecoveryAction.RETRY,                5, 1),
    ErrorKind.CONNECTION:        (RecoveryAction.RETRY,                5, 1),
    ErrorKind.CLI_CRASH:         (RecoveryAction.RETRY,                2, 1),
    ErrorKind.AUTH:              (RecoveryAction.ABORT,                0, 0),
    ErrorKind.NOT_FOUND:         (RecoveryAction.ABORT,                0, 0),
    ErrorKind.CREDIT:            (RecoveryAction.ABORT,                0, 0),
    ErrorKind.UNKNOWN:           (RecoveryAction.ABORT,                0, 0),
}


def classify_error(raw: str) -> ErrorKind:
    """Classify a raw CLI error string into an ErrorKind."""
    if not raw:
        return ErrorKind.UNKNOWN
    sl = raw.lower()
    # More specific patterns first
    if "context length" in sl or "too many tokens" in sl or "maximum context" in sl:
        return ErrorKind.CONTEXT_TOO_LONG
    if "overloaded" in sl:
        return ErrorKind.OVERLOADED
    if "rate limit" in sl or "429" in sl:
        return ErrorKind.RATE_LIMIT
    if "authentication" in sl or "401" in sl or "invalid api key" in sl or "x-api-key" in sl:
        return ErrorKind.AUTH
    if "credit" in sl or "billing" in sl or "quota" in sl or "insufficient" in sl:
        return ErrorKind.CREDIT
    if "not found" in sl or "404" in sl:
        return ErrorKind.NOT_FOUND
    if "timeout" in sl or "timed out" in sl:
        return ErrorKind.TIMEOUT
    if "connection" in sl or "network" in sl or "unreachable" in sl or "name or service not known" in sl:
        return ErrorKind.CONNECTION
    if "broken pipe" in sl or "killed" in sl or "segmentation fault" in sl:
        return ErrorKind.CLI_CRASH
    return ErrorKind.UNKNOWN


def get_recovery_plan(kind: ErrorKind) -> tuple:
    """Return (action, backoff_seconds, max_attempts) for an ErrorKind."""
    return _RECOVERY_MAP.get(kind, (RecoveryAction.ABORT, 0, 0))


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

        _proxy_server = None
        try:
            # Strip CLAUDECODE env var to prevent "nested session" errors.
            clean_env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}

            # Provider routing: GLM models go through z.AI's Anthropic-compatible gateway.
            # Claude CLI validates model names client-side, so GLM names ("glm-5.1" etc.)
            # are rejected before any HTTP call is made. Fix: start a local proxy that
            # accepts ANY model name from Claude CLI and rewrites it to the real GLM name
            # before forwarding to z.AI. Claude CLI sees a valid alias ("claude-sonnet-4-6").
            provider = model_provider(model)
            if provider == "zai":
                if not ZAI_API_KEY:
                    self.error_text = (
                        "❌ Modelo GLM solicitado mas ZAI_API_KEY não está configurado. "
                        "Defina em ~/claude-bot/.env (obtenha em https://z.ai/manage-apikey)."
                    )
                    logger.error(self.error_text)
                    self.running = False
                    return
                _proxy_server, _proxy_port = _start_zai_proxy(model, ZAI_BASE_URL, ZAI_API_KEY)
                logger.info("ZAI proxy started on port %d for model %s", _proxy_port, model)
                # Point Claude CLI at our local proxy; use a valid Claude alias so the
                # CLI's local model validation passes.
                clean_env["ANTHROPIC_BASE_URL"] = f"http://127.0.0.1:{_proxy_port}"
                clean_env["ANTHROPIC_AUTH_TOKEN"] = "zai-proxy"
                clean_env.pop("ANTHROPIC_API_KEY", None)
                # GLM-5.1 is ~44 tok/s — bump timeout so long generations don't hang.
                clean_env.setdefault("API_TIMEOUT_MS", "3000000")
                # Replace the GLM model name in cmd with a valid Claude alias so the
                # CLI's local model-name check doesn't abort before making the API call.
                for i, arg in enumerate(cmd):
                    if arg == "--model" and i + 1 < len(cmd):
                        cmd[i + 1] = "claude-sonnet-4-6"
                        break

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
            if _proxy_server is not None:
                _proxy_server.shutdown()
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


def _get_agent_workspace(agent_id: Optional[str]) -> Path:
    """Return (and create if needed) the isolated workspace dir for an agent.

    Each agent (including main) gets its own permanent workspace at
    ``<id>/.workspace/`` so pipeline data persists across runs and CLAUDE.md
    inheritance is controlled via .claude/settings.local.json inside it. The
    dot-prefix hides the folder from Obsidian's graph view automatically
    (dotfiles are hardcoded-ignored) so pipeline runtime data never pollutes
    the knowledge graph.
    """
    ws = workspace_dir(agent_id)
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "data").mkdir(exist_ok=True)
    return ws


def load_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    """Load agent definition from ``<id>/agent-<id>.md``.

    v3.4+ renamed the hub file from ``agent-info.md`` to ``agent-<id>.md``
    so every agent has a unique basename vault-wide (needed for Obsidian's
    shortest-path wikilink resolution). The file's frontmatter carries
    metadata (name, icon, model, color, chat_id, thread_id, …) and the body
    carries path-qualified wikilinks down to the agent's sub-indexes
    (Skills, Routines, Journal, Reactions, Lessons, Notes) plus CLAUDE.md.
    """
    agent_file = agent_info_path(agent_id)
    if not agent_file.is_file():
        return None
    fm, body = get_frontmatter_and_body(agent_file)
    if not fm:
        return None
    fm["_body"] = body
    fm["_id"] = agent_id
    return fm


def list_agents() -> List[Dict[str, Any]]:
    """List every agent at the top of the vault (including main).

    Uses :func:`iter_agent_ids` as the discriminator so reserved vault folders
    (``.graphs``, ``Images``, …) never get treated as agents.
    """
    agents: List[Dict[str, Any]] = []
    for name in iter_agent_ids():
        a = load_agent(name)
        if a:
            agents.append(a)
    return agents


# ---------------------------------------------------------------------------
# Obsidian graph-view color groups — auto-synced from agent metadata
# ---------------------------------------------------------------------------
#
# Obsidian stores its graph config in `vault/.obsidian/graph.json` with a
# `colorGroups` array:
#
#     "colorGroups": [
#         {"query": "path:main/", "color": {"a": 1, "rgb": 10395294}},
#         ...
#     ]
#
# The bot keeps this in sync with each agent's `color` field in
# `agent-info.md`: every time an agent is created or loaded, we rewrite the
# block of color groups tagged with our own marker so it reflects the current
# agent set. Any user-defined groups without the marker are preserved.

def _build_agent_color_group(agent_id: str, rgb: int) -> Dict[str, Any]:
    """Return an Obsidian colorGroup entry for an agent.

    The query is just ``path:<agent>/`` so Obsidian's native path filter
    matches every file in that agent's subtree. Bot-managed groups are
    identified by the format of this query string (see ``_is_agent_group``).
    """
    return {
        "query": f"path:{agent_id}/",
        "color": {"a": 1, "rgb": int(rgb)},
    }


def _is_agent_group(group: Dict[str, Any], known_agent_ids: set) -> bool:
    """Return True if this color group looks like one the bot manages.

    Bot-managed groups are identified either by the clean v3.1 query format
    (``path:<id>/``) or by the short-lived legacy marker format from v3.0
    (``claude-bot-agent:<id>``). Legacy matches are collected so the sync
    can clean them up on first run.
    """
    query = str(group.get("query", "")).strip()
    if "claude-bot-agent:" in query:
        return True
    if not query.startswith("path:"):
        return False
    # Match path:<id>/ — accept with or without trailing slash and extra junk.
    rest = query[5:].strip()
    # Extract the first path segment before any whitespace or slash.
    first = rest.split()[0] if rest.split() else ""
    first = first.rstrip("/")
    return first in known_agent_ids


def sync_obsidian_graph_color_groups() -> bool:
    """Regenerate per-agent color groups in ``vault/.obsidian/graph.json``.

    Walks every agent, reads the ``color`` field from its ``agent-info.md``
    frontmatter, and rewrites the bot-managed colorGroups block. User-defined
    color groups that don't look like agent paths are preserved untouched.

    Fail-open: any error is logged and the function returns False so callers
    can proceed without blocking the main flow. Returns True on success.
    """
    graph_json_path = VAULT_DIR / ".obsidian" / "graph.json"
    try:
        if graph_json_path.is_file():
            raw = graph_json_path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        else:
            # Nothing to sync into if Obsidian has never opened the vault.
            return False
        if not isinstance(data, dict):
            logger.warning("graph.json is not a JSON object — skipping color sync")
            return False

        known_agent_ids = set(iter_agent_ids())

        existing = data.get("colorGroups") or []
        if not isinstance(existing, list):
            existing = []
        # Preserve user groups (anything that isn't an agent path filter).
        preserved = [
            g for g in existing
            if isinstance(g, dict) and not _is_agent_group(g, known_agent_ids)
        ]

        # Build fresh bot-managed groups from current agent metadata.
        new_groups: List[Dict[str, Any]] = []
        for agent_id in sorted(known_agent_ids):
            info = load_agent(agent_id)
            if not info:
                continue
            rgb = resolve_agent_color(info.get("color"))
            new_groups.append(_build_agent_color_group(agent_id, rgb))

        data["colorGroups"] = new_groups + preserved
        graph_json_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Synced %d agent color groups → %s",
                    len(new_groups), graph_json_path)
        return True
    except Exception as exc:
        logger.warning("Obsidian color-group sync failed: %s", exc)
        return False


def get_agent_journal_dir(agent_id: Optional[str], create: bool = False) -> Path:
    """Return the journal directory for an agent (main included)."""
    d = journal_dir(agent_id)
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


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
    _auto_agent: Optional[str] = None  # agent ID set by auto-routing (None = manual or unset)
    _manual_override: bool = False  # True when user explicitly switched agent in this context

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
        # Every pipeline runs inside its owning agent's permanent workspace.
        # If the agent folder is missing (edge case — orphan task) fall back
        # to a temp dir so execution doesn't explode, but this is a bug path.
        owning = task.agent or MAIN_AGENT_ID
        if (VAULT_DIR / owning).is_dir():
            self.workspace = _get_agent_workspace(owning)
        else:
            logger.warning(
                "Pipeline %s owning agent folder missing (%s) — using temp workspace",
                task.name, owning,
            )
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
        # Path locking: output_filename → step_id holding the write lock.
        # Prevents two parallel steps from writing to the same output file.
        self._output_file_locks: Dict[str, str] = {}

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
        owning = self.task.agent or MAIN_AGENT_ID
        if (VAULT_DIR / owning).is_dir():
            # Persistent per-pipeline data dir inside the agent's permanent workspace
            data_dir = self.workspace / "data" / self.task.name
        else:
            data_dir = self.workspace / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Initialize pipeline state with all step ids + output types + workspace path
        steps_info = [{"id": s.id, "output_type": s.output_type} for s in self.task.steps]
        self.state.set_pipeline_status(self.task.name, self.task.time_slot, "running",
                                        steps_init=steps_info, workspace=str(self.workspace))

        # Send live progress message to Telegram (skip if notify=none)
        if self.task.notify != "none":
            self._send_progress_message()

        # Checkpoint vault state before pipeline execution
        checkpoint_ref = vault_checkpoint_create(f"pipeline-{self.task.name}")

        start_time = time.time()
        self._start_time = start_time
        try:
            self._run_dag_loop(data_dir)
        except Exception as exc:
            logger.error("Pipeline %s error: %s", self.task.name, exc)
            if checkpoint_ref:
                vault_checkpoint_restore(checkpoint_ref)
            self.state.set_pipeline_status(self.task.name, self.task.time_slot, "failed", error=str(exc)[:200])
            self._finalize_progress(success=False, error=str(exc), elapsed=int(time.time() - start_time))
            return False

        # Determine final status
        all_completed = all(s == "completed" for s in self._step_status.values())
        elapsed = int(time.time() - start_time)

        if all_completed:
            if checkpoint_ref:
                vault_checkpoint_drop(checkpoint_ref)
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
            if checkpoint_ref and status == "failed":
                vault_checkpoint_restore(checkpoint_ref)
            elif checkpoint_ref:
                vault_checkpoint_drop(checkpoint_ref)
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

            # Launch ready steps in parallel — skip any whose output file is
            # currently locked by a running step (will retry next wave).
            threads = []
            for step in ready:
                out_file = step.resolved_filename
                with self._lock:
                    if out_file in self._output_file_locks:
                        # Another step is writing to the same file; defer to next wave
                        logger.debug(
                            "Pipeline %s: step %s deferred — output %s locked by %s",
                            self.task.name, step.id, out_file, self._output_file_locks[out_file],
                        )
                        continue
                    self._step_status[step.id] = "running"
                    self._output_file_locks[out_file] = step.id
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
        # Ralph loop dispatcher — when the step has loop config, use the
        # dedicated loop executor. Otherwise fall through to the normal path.
        if step.has_loop:
            self._execute_loop_step(step, data_dir)
            return

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

        # Determine workspace for Claude CLI — prefer isolated workspace/ subdir
        ws = str(self.workspace)
        agent_id_for_ws = step.agent or self.task.agent or MAIN_AGENT_ID
        isolated = workspace_dir(agent_id_for_ws)
        if isolated.is_dir():
            ws = str(isolated)
        elif agent_base(agent_id_for_ws).is_dir():
            ws = str(agent_base(agent_id_for_ws))

        try:
            # Run Claude CLI in a separate thread so timeouts can actually fire
            runner_thread = threading.Thread(
                target=runner.run,
                kwargs={"prompt": prompt, "model": step.model, "workspace": ws,
                         "system_prompt": None if self.task.minimal_context else SYSTEM_PROMPT,
                         "effort": step.effort or self.task.effort},
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
                # Fallback: check if Claude wrote to the agent's workspace data dir
                # (safety net for when agent workspace differs from pipeline data_dir)
                agent_id = step.agent or self.task.agent or MAIN_AGENT_ID
                if agent_id:
                    ws_root = workspace_dir(agent_id)
                    candidates = [
                        ws_root / "data" / self.task.name / step.resolved_filename,
                        ws_root / "data" / step.resolved_filename,
                        agent_base(agent_id) / "data" / step.resolved_filename,  # legacy
                    ]
                    for candidate in candidates:
                        if candidate.exists() and candidate.stat().st_size > 0:
                            output = candidate.read_text(encoding="utf-8")
                            output_file.write_text(output, encoding="utf-8")
                            logger.info("Pipeline %s: step %s output recovered from %s",
                                        self.task.name, step.id, candidate)
                            break

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
                # Release output-file path lock so deferred steps can proceed
                if self._output_file_locks.get(step.resolved_filename) == step.id:
                    del self._output_file_locks[step.resolved_filename]
            self._remove_step_activity(step.id)

    def _run_step_invocation(self, step: PipelineStep, prompt: str, ws: str) -> str:
        """Run a single ClaudeRunner invocation for a step and return the raw output.

        Shared helper used by both the normal `_execute_step` path (indirectly via
        code below) and the Ralph-loop `_execute_loop_step`. Raises on timeout,
        cancellation, or runner error. Updates the pipeline's active-runners
        registry so `cancel()` can abort mid-loop.
        """
        runner = ClaudeRunner()
        with self._lock:
            self._active_runners[step.id] = runner
        try:
            runner_thread = threading.Thread(
                target=runner.run,
                kwargs={
                    "prompt": prompt, "model": step.model, "workspace": ws,
                    "system_prompt": None if self.task.minimal_context else SYSTEM_PROMPT,
                    "effort": step.effort or self.task.effort,
                },
                daemon=True, name=f"pipeline-loop-runner-{step.id}",
            )
            runner_thread.start()
            hard_deadline = time.time() + step.timeout
            last_activity_write = 0.0
            while runner_thread.is_alive() and time.time() < hard_deadline:
                if self._cancelled.is_set():
                    runner.cancel()
                    break
                idle = time.time() - runner.last_activity
                if idle > step.inactivity_timeout and runner.last_activity > runner.start_time:
                    proc = runner.process
                    if not (proc and proc.poll() is None):
                        runner.cancel()
                        raise TimeoutError(
                            f"Step {step.id} idle for {int(idle)}s "
                            f"(inactivity limit: {step.inactivity_timeout}s)"
                        )
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
            runner_thread.join(timeout=5)

            if self._cancelled.is_set():
                raise RuntimeError("Pipeline cancelled")

            output = runner.result_text or runner.accumulated_text or ""
            if runner.error_text and not output:
                raise RuntimeError(runner.error_text)
            return output
        finally:
            with self._lock:
                self._active_runners.pop(step.id, None)

    def _execute_loop_step(self, step: PipelineStep, data_dir: Path) -> None:
        """Ralph loop — re-run a step until ``step.loop_until`` appears in the
        output or the iteration cap is reached.

        Behaviour:
        - Each iteration appends the previous output as context to the next
          prompt so the agent can make progress
        - If ``step.loop_until`` substring appears in the current iteration's
          output, the loop exits successfully
        - If ``max_iterations`` is reached, the step is marked FAILED with a
          clear error (no silent errors)
        - If ``loop_on_no_progress == "abort"`` and two consecutive iterations
          produce identical output, the loop aborts as FAILED
        - Cancellation via ``cancel()`` aborts the loop immediately
        """
        attempt = self._step_attempts.get(step.id, 0) + 1
        with self._lock:
            self._step_attempts[step.id] = attempt
        self.state.set_step_status(self.task.name, self.task.time_slot, step.id, "running", attempt=attempt)

        logger.info(
            "Pipeline %s: step %s starting LOOP (model=%s, until=%r, max=%d)",
            self.task.name, step.id, step.model, step.loop_until, step.loop_max_iterations,
        )

        # Resolve workspace for Claude CLI (same rules as _execute_step)
        ws = str(self.workspace)
        agent_id_for_ws = step.agent or self.task.agent or MAIN_AGENT_ID
        isolated = workspace_dir(agent_id_for_ws)
        if isolated.is_dir():
            ws = str(isolated)
        elif agent_base(agent_id_for_ws).is_dir():
            ws = str(agent_base(agent_id_for_ws))

        base_prompt = self._build_step_prompt(step, data_dir)
        output = ""
        previous_output = None
        iterations = 0
        cap = min(step.loop_max_iterations, MAX_LOOP_ITERATIONS)
        loop_marker = step.loop_until or ""

        try:
            for i in range(1, cap + 1):
                if self._cancelled.is_set():
                    raise RuntimeError("Pipeline cancelled during loop")

                iterations = i
                if i == 1:
                    iter_prompt = base_prompt
                else:
                    iter_prompt = (
                        f"{base_prompt}\n\n"
                        f"---\n\n"
                        f"[LOOP ITERATION {i}/{cap}] "
                        f"Você está em um loop. Continue a tarefa até escrever "
                        f"exatamente a string `{loop_marker}` no seu output quando "
                        f"a tarefa estiver concluída. Este é o resultado da iteração anterior:\n\n"
                        f"{previous_output or '(vazio)'}\n"
                    )
                logger.info("Pipeline %s: step %s loop iter %d/%d", self.task.name, step.id, i, cap)
                output = self._run_step_invocation(step, iter_prompt, ws)

                # Persist the latest output every iteration so a crash mid-loop
                # leaves the most recent result on disk for debugging.
                try:
                    (data_dir / step.resolved_filename).write_text(output, encoding="utf-8")
                except OSError as ose:
                    logger.error("Pipeline %s: step %s could not write loop output: %s",
                                 self.task.name, step.id, ose)

                # Success: loop marker appeared
                if loop_marker and loop_marker in output:
                    logger.info("Pipeline %s: step %s loop exited on iter %d (marker found)",
                                self.task.name, step.id, i)
                    break

                # No-progress detection
                if previous_output is not None and output == previous_output:
                    if step.loop_on_no_progress == "abort":
                        raise RuntimeError(
                            f"Loop stalled on iter {i}: two consecutive iterations produced "
                            f"identical output (on_no_progress=abort)"
                        )
                    logger.warning("Pipeline %s: step %s no progress on iter %d (continuing)",
                                   self.task.name, step.id, i)

                previous_output = output
            else:
                # Loop ran to completion without finding marker
                raise RuntimeError(
                    f"Loop exceeded max_iterations={cap} without finding marker "
                    f"{loop_marker!r} (Ralph technique)"
                )

            with self._lock:
                self._step_outputs[step.id] = output
                self._step_status[step.id] = "completed"
            self.state.set_step_status(
                self.task.name, self.task.time_slot, step.id, "completed",
                attempt=attempt,
            )
            logger.info("Pipeline %s: step %s loop completed in %d iters",
                        self.task.name, step.id, iterations)
        except Exception as exc:
            err_msg = f"[loop iter {iterations}] {str(exc)[:180]}"
            with self._lock:
                self._step_errors[step.id] = err_msg
                self._step_status[step.id] = "failed"
            self.state.set_step_status(
                self.task.name, self.task.time_slot, step.id, "failed",
                error=err_msg, attempt=attempt,
            )
            logger.error("Pipeline %s: step %s loop failed: %s",
                         self.task.name, step.id, err_msg)
        finally:
            with self._lock:
                if self._output_file_locks.get(step.resolved_filename) == step.id:
                    del self._output_file_locks[step.resolved_filename]
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

        # Activity log
        _log_activity({
            "agent": self.task.agent or "main",
            "type": "pipeline",
            "pipeline": self.task.name,
            "status": "completed",
            "steps": len(self.task.steps),
            "elapsed": elapsed,
        })

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

        # Compound engineering: auto-draft a lesson so we learn from this failure.
        # record_lesson_draft never raises — errors are logged and swallowed.
        lesson_path = record_lesson_draft(
            self.task.name, error, kind="pipeline",
            agent_id=self.task.agent or MAIN_AGENT_ID,
        )
        if lesson_path:
            try:
                try:
                    rel = lesson_path.relative_to(VAULT_DIR)
                except ValueError:
                    rel = lesson_path
                self.bot.send_message(
                    f"📝 Rascunho de lição criado em `{rel}` "
                    f"— complete as seções Fix e Detect.",
                    chat_id=self.ctx.chat_id, thread_id=self.ctx.thread_id,
                    disable_notification=True,
                )
            except Exception as exc:
                logger.error("Pipeline lesson-draft notify failed: %s", exc)

        # Activity log
        _log_activity({
            "agent": self.task.agent or "main",
            "type": "pipeline",
            "pipeline": self.task.name,
            "status": "failed",
            "error": error[:150],
        })


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

        # Active context — thread-local. Each thread (polling, update handler,
        # routine, pipeline, callback, control server) sees its own slot.
        # This prevents cross-talk when multiple Claude runs execute
        # concurrently in different Telegram topics. Reads/writes go through
        # the _ctx property below.
        self._ctx_local = threading.local()

        # Routine scheduler
        self.routine_state = RoutineStateManager()
        _cleanup_stale_pipeline_workspaces()
        self.scheduler = RoutineScheduler(
            self.routine_state, self._enqueue_routine, self._enqueue_pipeline,
            notify_fn=self.send_message,
        )
        self.scheduler.start()

        # Sync the per-agent Obsidian graph-view color groups. Fail-open —
        # the bot works fine without it; the user may just not have Obsidian
        # installed or pointed at this vault.
        try:
            sync_obsidian_graph_color_groups()
        except Exception as exc:
            logger.warning("Initial Obsidian color-group sync skipped: %s", exc)

        # Tracks active routine/pipeline contexts for HTTP stop requests
        self._routine_contexts: Dict[str, "ThreadContext"] = {}
        self._routine_contexts_lock = threading.Lock()
        self._active_pipelines: Dict[str, PipelineExecutor] = {}
        self._active_pipelines_lock = threading.Lock()

        self._start_time = time.time()
        self._start_control_server()
        self._start_webhook_server()

        # Agent ↔ chat mapping: (chat_id, thread_id) → agent dict
        self._agent_chat_map: Dict[tuple, Dict[str, Any]] = self._build_agent_chat_map()

        # Pending dangerous-prompt approvals: {callback_id: {prompt, chat_id, thread_id, user_msg_id, ts}}
        self._pending_approvals: Dict[str, dict] = {}
        self._voice_picks: Dict[str, dict] = {}  # voice/text picker during transcription
        # Tracks mtime of today's journal at session start, per session name.
        # Used to detect journal updates mid-session and nudge Claude without breaking prefix cache.
        self._journal_mtimes: Dict[str, float] = {}

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

    # -- Agent ↔ Chat mapping --

    _AGENT_MAP_TTL = 60  # seconds between automatic refreshes

    def _build_agent_chat_map(self) -> Dict[tuple, Dict[str, Any]]:
        """Build a mapping of (chat_id, thread_id) → agent dict from agent frontmatter.

        Only maps agents that have BOTH chat_id AND thread_id — a chat_id alone
        (without thread_id) would hijack the entire group for one agent.
        """
        mapping: Dict[tuple, Dict[str, Any]] = {}
        for agent in list_agents():
            agent_chat_id = agent.get("chat_id") or agent.get("telegram_chat_id")
            agent_thread_id = agent.get("thread_id")
            if agent_chat_id and agent_thread_id is not None:
                # Normalize: chat_id as str, thread_id as int
                tid = int(agent_thread_id)
                mapping[(str(agent_chat_id), tid)] = agent
        if mapping:
            logger.info("Agent chat map: %s", {k: v["_id"] for k, v in mapping.items()})
        self._agent_map_ts = time.time()
        return mapping

    def _refresh_agent_chat_map(self) -> None:
        """Refresh the agent ↔ chat mapping (call after agent creation/update)."""
        self._agent_chat_map = self._build_agent_chat_map()

    def _find_agent_for_chat(self, chat_id: str, thread_id: Optional[int]) -> Optional[Dict[str, Any]]:
        """Return the agent dict if this (chat_id, thread_id) is mapped to an agent.

        Auto-refreshes the map if older than _AGENT_MAP_TTL seconds.
        """
        if thread_id is None:
            return None  # require thread_id — don't hijack entire groups
        # Lazy refresh: re-scan agents periodically to pick up new/edited agents
        if time.time() - self._agent_map_ts > self._AGENT_MAP_TTL:
            self._refresh_agent_chat_map()
        # Exact match (chat_id as str, thread_id as int)
        return self._agent_chat_map.get((chat_id, int(thread_id)))

    def _auto_activate_agent(self, agent: Dict[str, Any]) -> None:
        """Activate an agent on the current session (workspace + model), silently.

        Thread-safe: acquires context lock before mutating session state.
        """
        ctx = self._ctx
        lock = ctx.lock if ctx else threading.Lock()
        with lock:
            session = self._get_session()
            session.agent = agent["_id"]
            session.model = agent.get("model", session.model)
            isolated = workspace_dir(agent["_id"])
            session.workspace = str(isolated) if isolated.is_dir() else str(agent_base(agent["_id"]))
            # Mark as auto-activated so manual overrides are respected
            if ctx:
                ctx._auto_agent = agent["_id"]
            self.sessions.save()
        logger.info("Auto-activated agent %s for chat context (%s)", agent["_id"], self._ctx)

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
    def _ctx(self) -> Optional[ThreadContext]:
        """Thread-local active context. Each thread has its own slot."""
        return getattr(self._ctx_local, "value", None)

    @_ctx.setter
    def _ctx(self, value: Optional[ThreadContext]) -> None:
        self._ctx_local.value = value

    @property
    def _chat_id(self) -> str:
        if self._ctx:
            return self._ctx.chat_id
        # Fallback for code paths with no per-thread context (e.g. webhook
        # server error notifications). Use the first configured chat ID, not
        # the raw env var (which may be a comma-separated list).
        raw = str(TELEGRAM_CHAT_ID)
        return raw.split(",", 1)[0].strip() if "," in raw else raw

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
        lines.append(f"• Inactivity timeout: {self.timeout_seconds}s")
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
        if model not in MODEL_PROVIDERS and not model.startswith("glm"):
            known = ", ".join(sorted(MODEL_PROVIDERS.keys()))
            self.send_message(f"❌ Modelo desconhecido: `{model}`\nConhecidos: {known}")
            return
        # Guard: if GLM requested but no key, warn now instead of failing on first message.
        if model_provider(model) == "zai" and not ZAI_API_KEY:
            self.send_message(
                "⚠️ `ZAI_API_KEY` não está configurado no `~/claude-bot/.env`.\n"
                "Obtenha uma chave em https://z.ai/manage-apikey e adicione ao arquivo."
            )
            return
        s = self._get_session()
        s.model = model
        self.sessions.save()
        self.send_message(f"✅ Modelo alterado para `{model}`")

    def cmd_model_keyboard(self) -> None:
        rows = [
            [
                {"text": "Sonnet", "callback_data": "model:sonnet"},
                {"text": "Opus", "callback_data": "model:opus"},
                {"text": "Haiku", "callback_data": "model:haiku"},
            ]
        ]
        if ZAI_API_KEY:
            rows.append([
                {"text": "GLM 5.1", "callback_data": "model:glm-5.1"},
                {"text": "GLM 4.7", "callback_data": "model:glm-4.7"},
                {"text": "GLM 4.5 Air", "callback_data": "model:glm-4.5-air"},
            ])
        markup = {"inline_keyboard": rows}
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

    def cmd_active_memory(self, arg: str = "") -> None:
        """Toggle Active Memory (proactive vault context injection) for the current session.

        Usage:
          /active-memory           → show status
          /active-memory status    → show status
          /active-memory on        → enable for current session
          /active-memory off       → disable for current session
        """
        session = self._get_session()
        if not session:
            self.send_message("❌ Nenhuma sessão ativa.")
            return
        arg_norm = (arg or "").strip().lower()
        if arg_norm in ("on", "1", "sim"):
            session.active_memory = True
            self.sessions.save()
            state = "✅ ativada"
        elif arg_norm in ("off", "0", "nao", "não"):
            session.active_memory = False
            self.sessions.save()
            state = "❌ desativada"
        elif arg_norm in ("", "status"):
            state = "✅ ativada" if session.active_memory else "❌ desativada"
        else:
            self.send_message(
                "❌ Uso: `/active-memory [on|off|status]`"
            )
            return
        global_default = "on" if ACTIVE_MEMORY_ENABLED else "off"
        self.send_message(
            f"🧠 *Active Memory*: {state} para sessão `{session.name}`\n"
            f"_Padrão global: {global_default}. "
            f"Injeta contexto relevante do vault antes de cada resposta._"
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

    def cmd_lesson(self, text: str) -> None:
        """Record a manual lesson into <current-agent>/Lessons/.

        Usage: /lesson <text>
        Persists as manual-YYYY-MM-DD-HHMM.md with structured frontmatter
        under the active agent's Lessons folder.
        """
        text = (text or "").strip()
        if not text:
            self.send_message(
                "❌ Use: `/lesson <texto>`\n"
                "_Registra uma lição manual em `<agente>/Lessons/`. "
                "Útil para capturar aprendizados durante a conversa._"
            )
            return
        current = self._get_session()
        agent_for_lesson = current.agent if current else None
        path = record_manual_lesson(text, agent_id=agent_for_lesson)
        if path is None:
            self.send_message("❌ Falha ao gravar lição. Veja o log para detalhes.")
            return
        try:
            rel = path.relative_to(VAULT_DIR)
        except ValueError:
            rel = path
        self.send_message(
            f"📝 Lição registrada em `{rel}`.\n"
            f"_Complete as seções Fix e Detect quando puder._"
        )

    def cmd_clone(self, dest_name: str) -> None:
        """Clone the current active session into a new name and switch to it.

        Usage: /clone <new-name>
        The clone keeps the same Claude session_id (continues the conversation)
        so the user can branch and test divergent prompts. Original stays intact.
        """
        dest_name = (dest_name or "").strip()
        if not dest_name:
            self.send_message(
                "❌ Use: `/clone <nome>`\n"
                "_Clona a sessão atual mantendo o mesmo session\\_id do Claude — "
                "permite testar prompts divergentes sem perder o contexto original._"
            )
            return
        current = self._get_session()
        if current is None:
            self.send_message("❌ Nenhuma sessão ativa para clonar.")
            return
        if dest_name in self.sessions.sessions:
            self.send_message(f"❌ Sessão `{dest_name}` já existe. Escolha outro nome.")
            return
        try:
            clone = self.sessions.clone(current.name, dest_name)
        except Exception as exc:
            logger.error("Clone failed: source=%s dest=%s err=%s", current.name, dest_name, exc)
            self.send_message(f"❌ Falha ao clonar sessão: `{str(exc)[:100]}`")
            return
        if clone is None:
            self.send_message(f"❌ Falha ao clonar sessão `{current.name}` para `{dest_name}`.")
            return
        self.send_message(
            f"🌿 Sessão `{current.name}` clonada para `{clone.name}`.\n"
            f"• Modelo: `{clone.model}`\n"
            f"• Session ID: `{clone.session_id or 'nenhum'}`\n"
            f"_Agora ativa nesta branch. Original intacta em `{current.name}`._"
        )

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

    def _build_frozen_context(self, session: Session) -> tuple:
        """Build a compact context snapshot to inject once on the first message of a session.

        Includes agent CLAUDE.md (truncated), the agent's hot-cache context
        (rolling state from previous sessions), and the last portion of
        today's journal. Frozen at session start — does not change mid-session
        — to preserve prefix cache hits.

        Returns (context_str, journal_mtime) where journal_mtime is 0.0 if no journal exists.
        """
        parts = []
        journal_mtime = 0.0

        # Agent instructions (up to 2000 chars to keep it tight)
        if session.agent:
            agent_claude_md = VAULT_DIR / session.agent / "CLAUDE.md"
            if agent_claude_md.is_file():
                try:
                    content = agent_claude_md.read_text(encoding="utf-8")[:2000]
                    if content.strip():
                        parts.append(f"# Agent Instructions ({session.agent})\n\n{content}")
                except OSError:
                    pass

            # Hot cache: rolling state from previous sessions for this agent.
            # Maintained by `_update_agent_context()` which fires after auto-rotate
            # and on /important. Capped to ~HOT_CACHE_INJECT_TOKENS chars.
            hot_cache_body = _read_agent_context(session.agent)
            if hot_cache_body:
                parts.append(
                    f"# Continuity ({session.agent})\n\n"
                    f"_Rolling context from prior sessions. Use it as memory; "
                    f"do not repeat back unless asked._\n\n{hot_cache_body}"
                )

        # Recent journal entries (last 1500 chars of today's journal)
        journal_path = Path(self._get_journal_path())
        if journal_path.is_file():
            try:
                journal_mtime = journal_path.stat().st_mtime
                journal_text = journal_path.read_text(encoding="utf-8")
                if journal_text.strip():
                    excerpt = journal_text[-1500:].strip()
                    parts.append(f"# Journal — Today's Context\n\n{excerpt}")
            except OSError:
                pass

        context_str = "\n\n---\n\n".join(parts) if parts else ""
        return context_str, journal_mtime

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Normalize text for fuzzy matching: lowercase, strip accents, split on separators."""
        # Strip accents: 'diário' → 'diario', 'création' → 'creation'
        nfkd = unicodedata.normalize("NFKD", text)
        ascii_text = "".join(c for c in nfkd if not unicodedata.combining(c))
        # Replace hyphens/underscores/slashes with spaces so 'journal-entry' → 'journal entry'
        for sep in ("-", "_", "/", "."):
            ascii_text = ascii_text.replace(sep, " ")
        return ascii_text.lower()

    def _find_relevant_skills(self, prompt: str, limit: int = 3) -> List[Dict[str, str]]:
        """Return up to `limit` skills that match the prompt — for the current agent only.

        Hybrid scoring (zero LLM cost):
          +5 per skill tag that appears in the prompt (highest signal — tags
              are deliberately chosen by the skill author)
          +3 per exact word match against the trigger field
          +2 per exact word match against title/description
          +1 per substring match anywhere

        Isolamento total: skills are filtered by `<current-agent>/Skills/`.
        Short words (<= 3 chars) are ignored to avoid noise. Skills with score
        0 are filtered out.

        Returns list of {name, description, path}.
        """
        norm_prompt = self._normalize_text(prompt)
        prompt_words = {w for w in norm_prompt.split() if len(w) > 3}
        if not prompt_words:
            return []
        session = self._get_session()
        current_agent = session.agent if session else None
        agent_skills_prefix = f"{_agent_id_or_main(current_agent)}/Skills/"
        try:
            from vault_query import load_vault
            vi = load_vault(VAULT_DIR)
            skills = [s for s in vi.find(type="skill")
                      if s.rel_path.startswith(agent_skills_prefix)]
        except Exception:
            logger.exception("vault_query load failed in _find_relevant_skills")
            return []

        scored: List[tuple] = []
        for f in skills:
            name = str(f.frontmatter.get("title", f.path.stem))
            desc = f.description
            trigger = str(f.frontmatter.get("trigger", ""))
            tags = [self._normalize_text(t) for t in f.tags]

            score = 0
            # +5 per tag overlap (highest signal)
            for tag in tags:
                if tag and tag in norm_prompt:
                    score += 5
            # +3 per exact match against trigger
            trigger_words = set(self._normalize_text(trigger).split())
            for pw in prompt_words:
                if pw in trigger_words:
                    score += 3
            # +2 per exact match against title/description
            text_words = set(self._normalize_text(f"{name} {desc}").split())
            for pw in prompt_words:
                if pw in text_words:
                    score += 2
                elif any(pw in tw for tw in text_words):
                    score += 1
            if score > 0:
                scored.append((score, {
                    "name": name,
                    "description": desc,
                    "path": str(f.path),
                }))
        scored.sort(key=lambda x: -x[0])
        return [s[1] for s in scored[:limit]]

    def _snapshot_session_to_journal(self, session: Session) -> None:
        """Generate a structured snapshot of the session and append it to today's journal.

        Called synchronously from within the auto-compact background thread — runs before
        /compact so the summary reflects the full context while it still exists.
        """
        if not session.session_id:
            return
        journal_path = Path(self._get_journal_path())
        journal_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = time.strftime("%Y-%m-%d %H:%M")
        snapshot_prompt = (
            "Gere um snapshot compacto desta sessão em markdown puro (sem preâmbulo), "
            "com estes blocos (máx 8 linhas cada):\n"
            "## Goal\n## Progress\n## Decisions\n## Files\n## Next Steps\n\n"
            "Responda APENAS com o markdown do snapshot."
        )
        try:
            runner = ClaudeRunner()
            runner.run(
                prompt=snapshot_prompt,
                model=session.model,
                session_id=session.session_id,
                workspace=session.workspace,
                system_prompt=None,
            )
            snapshot = (runner.result_text or runner.accumulated_text or "").strip()
            if not snapshot:
                return
            header = (
                f"\n\n---\n\n"
                f"## Session Snapshot — {timestamp}\n\n"
                f"_Agent: {session.agent or 'main'} | Session: {session.name} | "
                f"Turns: {session.message_count}_\n\n"
            )
            with journal_path.open("a", encoding="utf-8") as f:
                f.write(header + snapshot + "\n")
            logger.info("Session snapshot appended to %s (%d chars)", journal_path, len(snapshot))
        except Exception as exc:
            logger.error("Session snapshot failed: %s", exc)
            # Non-fatal — compact proceeds regardless

    def _auto_compact(self, session: Session) -> None:
        """Run /compact in background to keep session context manageable.

        First snapshots the session to today's journal, then compacts. After
        compacting, refreshes the agent's hot-cache (.context.md) so the next
        session for the same agent resumes with rolling continuity.
        """
        if not session.session_id:
            return
        sid = session.session_id
        ws = session.workspace
        model = session.model

        def _worker() -> None:
            try:
                logger.info("Auto-compact starting for session %s (turns=%d)",
                            session.name, session.message_count)
                # 1. Snapshot to journal before compacting (preserves episodic memory)
                self._snapshot_session_to_journal(session)
                # 2. Compact
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
                # 3. Refresh agent hot cache for cross-session continuity
                if session.agent:
                    self._update_agent_hot_cache(session)
            except Exception as exc:
                logger.error("Auto-compact failed: %s", exc)

        threading.Thread(target=_worker, daemon=True, name="auto-compact").start()

    def _update_agent_hot_cache(self, session: Session) -> None:
        """Refresh vault/Agents/{id}/.context.md with the agent's rolling state.

        Fires a structured prompt that asks Claude to summarize the current
        session into Active topics / Recent decisions / Open threads, plus
        a Durable concepts section. Writes the first three sections to
        .context.md and promotes high-confidence durable concepts to
        Agents/<agent>/Notes/{slug}.md.

        Best-effort — never raises. Logs failures and moves on.
        """
        if not session.session_id:
            return
        agent_id = session.agent or MAIN_AGENT_ID
        prompt = (
            "You are updating the rolling context file for this agent. Reflect "
            "on the current session and produce a structured snapshot in the "
            "EXACT format below. Be terse — no preamble. Each bullet should be "
            "one short sentence.\n\n"
            "## Active topics\n"
            "- topic 1\n"
            "- topic 2\n\n"
            "## Recent decisions\n"
            "- decision 1\n"
            "- decision 2\n\n"
            "## Open threads\n"
            "- thread 1 (what is mid-flight, awaiting what)\n\n"
            "## Durable concepts\n"
            "(Each bullet must be a fact/concept worth keeping FOREVER, not a "
            "transient status. Use this exact format: "
            "`- {kebab-slug} | {high|medium|low} | {one-line summary}`. "
            "If nothing is durable, leave this section empty.)\n"
        )
        try:
            runner = ClaudeRunner()
            runner.run(
                prompt=prompt,
                model=session.model,
                session_id=session.session_id,
                workspace=session.workspace,
                system_prompt=None,
            )
            snapshot = (runner.result_text or runner.accumulated_text or "").strip()
            if not snapshot:
                logger.info("Hot cache refresh for %s: empty response", agent_id)
                return
            # Extract durable concepts BEFORE stripping the section
            concepts = _extract_durable_concepts(snapshot)
            # Body of .context.md = snapshot minus the durable concepts section
            body = _strip_durable_concepts_section(snapshot)
            _write_agent_context(agent_id, body)
            logger.info(
                "Hot cache refreshed for agent %s (%d chars, %d durable concepts)",
                agent_id, len(body), len(concepts),
            )
            # Promote high-confidence concepts to Notes/
            promoted = 0
            for c in concepts:
                if _promote_durable_concept_to_notes(c, agent_id) is not None:
                    promoted += 1
            if promoted:
                logger.info("Promoted %d durable concept(s) to Notes/ for agent %s",
                            promoted, agent_id)
        except Exception as exc:
            logger.error("Hot cache refresh failed for agent %s: %s", agent_id, exc)

    def cmd_cost(self) -> None:
        self._run_claude_prompt("/cost")

    def cmd_doctor(self) -> None:
        self._run_claude_prompt("/doctor")

    def cmd_lint(self) -> None:
        """Run the vault linter and report results to Telegram."""
        try:
            from vault_lint import lint_vault, _format_text_report
        except Exception as exc:
            logger.exception("Failed to import vault_lint")
            self.send_message(f"❌ Vault lint indisponível: `{exc}`")
            return
        try:
            report = lint_vault(VAULT_DIR)
        except Exception as exc:
            logger.exception("vault_lint failed")
            self.send_message(f"❌ Lint falhou: `{exc}`")
            return
        text = _format_text_report(report)
        # Telegram messages have a hard limit; the report is usually small
        # but let's truncate generously to avoid surprises.
        if len(text) > 3500:
            text = text[:3500] + "\n…(truncated)"
        self.send_message(text)

    def cmd_find(self, expr: str) -> None:
        """Run a frontmatter-aware vault query and report results to Telegram.

        Examples:
          /find type=routine model=opus
          /find type=skill tags__contains=publish
          /find type=pipeline agent=crypto-bro enabled=true

        With no arguments, shows usage. With `--text <query>`, runs a free-text
        search across title/description/tags instead of a structured filter.
        """
        if not expr.strip():
            self.send_message(
                "🔎 *Vault find*\n\n"
                "Uso: `/find <chave>=<valor> [...]`\n\n"
                "Exemplos:\n"
                "• `/find type=routine model=opus`\n"
                "• `/find type=skill tags__contains=publish`\n"
                "• `/find type=pipeline agent=crypto-bro enabled=true`\n"
                "• `/find type=skill trigger__exists=true`\n\n"
                "Sufixos suportados: `__contains`, `__in`, `__startswith`, "
                "`__endswith`, `__exists`."
            )
            return
        try:
            from vault_query import load_vault, parse_filter_expression
        except Exception as exc:
            logger.exception("vault_query import failed")
            self.send_message(f"❌ vault_query indisponível: `{exc}`")
            return
        try:
            vi = load_vault(VAULT_DIR)
            filters = parse_filter_expression(expr)
            results = vi.find(**filters)
        except Exception as exc:
            logger.exception("vault_query find failed")
            self.send_message(f"❌ Find falhou: `{exc}`")
            return
        if not results:
            self.send_message(f"🔎 Nenhum resultado para `{expr}`")
            return
        lines = [f"🔎 *{len(results)} resultado(s)* para `{expr}`\n"]
        # Group by type so the output is scannable
        by_type: Dict[str, List] = {}
        for r in results:
            by_type.setdefault(r.type, []).append(r)
        for t in sorted(by_type.keys()):
            lines.append(f"\n*{t}*")
            for r in by_type[t][:15]:
                desc = r.description[:80] + "…" if len(r.description) > 80 else r.description
                lines.append(f"• `{r.path.stem}` — {desc}")
            if len(by_type[t]) > 15:
                lines.append(f"  …e mais {len(by_type[t]) - 15}")
        text = "\n".join(lines)
        if len(text) > 3500:
            text = text[:3500] + "\n…(truncated)"
        self.send_message(text)

    def cmd_indexes(self) -> None:
        """Regenerate vault index marker blocks and Obsidian graph color groups."""
        try:
            from vault_indexes import regenerate_vault
        except Exception as exc:
            logger.exception("Failed to import vault_indexes")
            self.send_message(f"❌ Vault indexes indisponível: `{exc}`")
            return
        try:
            changed, scanned = regenerate_vault(VAULT_DIR)
        except Exception as exc:
            logger.exception("vault_indexes failed")
            self.send_message(f"❌ Index regen falhou: `{exc}`")
            return
        # Also sync the Obsidian graph color groups from agent metadata.
        colors_synced = sync_obsidian_graph_color_groups()
        if not scanned:
            extra = " + color groups synced" if colors_synced else ""
            self.send_message(f"ℹ️ Nenhum arquivo com marcadores `vault-query` encontrado.{extra}")
            return
        if not changed:
            extra = " · color groups synced" if colors_synced else ""
            self.send_message(f"✅ Todos os {len(scanned)} index files já estão atualizados.{extra}")
            return
        lines = [f"📚 *Vault indexes regenerated* ({len(changed)}/{len(scanned)})"]
        for f in changed:
            try:
                rel = f.relative_to(VAULT_DIR)
            except ValueError:
                rel = f
            lines.append(f"  • `{rel}`")
        if colors_synced:
            lines.append("🎨 Obsidian graph color groups synced from agent metadata")
        self.send_message("\n".join(lines))

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
            self.send_message(f"✅ Timeout de inatividade alterado para {self.timeout_seconds}s")
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

    def cmd_delegate(self, prompt: str) -> None:
        """Spawn an isolated Claude subprocess for a sub-task and inject the result back.

        The subagent runs with session_id=None (fresh context, no conversation history),
        minimal system prompt, and a hard 10-minute wall-clock limit. The result is sent
        to Telegram and optionally injected into the parent session via /btw.
        """
        if not prompt.strip():
            self.send_message("❌ Uso: `/delegate <prompt>`")
            return
        session = self._get_session()
        self.send_message(f"🧬 _Sub-task delegada — aguardando resultado (max 10min)..._")

        def _worker() -> None:
            try:
                sub_runner = ClaudeRunner()
                runner_thread = threading.Thread(
                    target=sub_runner.run,
                    kwargs={
                        "prompt": prompt,
                        "model": session.model,
                        "session_id": None,        # fresh context
                        "workspace": session.workspace,
                        "system_prompt": None,     # minimal — no vault system prompt
                    },
                    daemon=True,
                )
                runner_thread.start()
                runner_thread.join(timeout=600)     # 10-minute hard limit
                if runner_thread.is_alive():
                    sub_runner.cancel()
                    self.send_message("⏱️ _Subagent timeout (10min). Resultado parcial:_")

                result = (sub_runner.result_text or sub_runner.accumulated_text or "").strip()
                if not result:
                    err = sub_runner.stderr_text or sub_runner.error_text or "sem output"
                    self.send_message(f"❌ Subagent sem resultado: `{err[:200]}`")
                    return

                # Truncate very large results before sending
                display = result if len(result) <= 3800 else result[:3800] + "\n\n[…truncado]"
                self.send_message(f"🧬 *Subagent Result:*\n\n{display}")

                # Inject back into the parent session if it's idle
                ctx = self._ctx
                if ctx and ctx.runner and not ctx.runner.running:
                    injection = (
                        f"[SUBAGENT RESULT for: {prompt[:80]}]\n\n{result[:3000]}"
                    )
                    with ctx.pending_lock:
                        ctx.pending.append(injection)
                    logger.info("Subagent result queued for injection into parent session")
            except Exception as exc:
                logger.error("Delegate failed: %s", exc)
                self.send_message(f"❌ Erro no subagent: `{str(exc)[:200]}`")

        threading.Thread(target=_worker, daemon=True, name="subagent-delegate").start()

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
        md_file = _find_routine_file(name)

        if md_file is None:
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
            _effort_raw = str(fm.get("effort", "")).lower().strip()
            # Folder is the source of truth for agent ownership.
            owning_agent = md_file.parent.parent.name if md_file.parent.parent.parent == VAULT_DIR else MAIN_AGENT_ID
            task = RoutineTask(
                name=name,
                prompt=body,
                model=model,
                time_slot=time_slot,
                agent=owning_agent,
                minimal_context=bool(fm.get("context") == "minimal"),
                voice=bool(fm.get("voice", False)),
                effort=_effort_raw if _effort_raw in ("low", "medium", "high") else None,
            )
            self._enqueue_routine(task)
            self.send_message(f"🚀 Rotina `{name}` disparada manualmente.")

    def _run_list_keyboard(self) -> None:
        """Show inline keyboard with all available routines/pipelines."""
        routine_files = _iter_routine_files()
        if not routine_files:
            self.send_message("❌ Nenhuma rotina disponível.")
            return

        buttons = []
        for md_file in routine_files:
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
        """List the skills available to the current agent (isolamento total)."""
        session = self._get_session()
        current_agent = session.agent if session else None
        sdir = skills_dir(current_agent)
        label = current_agent or MAIN_AGENT_ID
        if not sdir.is_dir():
            self.send_message(f"⚡ Nenhuma skill encontrada para `{label}`.")
            return
        lines = [f"⚡ *Skills ({label})*\n"]
        for f in sorted(sdir.glob("*.md")):
            if f.name in SUB_INDEX_FILENAMES_SET:
                continue  # skip the agent-skills.md index
            fm, _ = get_frontmatter_and_body(f)
            title = fm.get("title", f.stem)
            desc = fm.get("description", "")[:60]
            lines.append(f"- *{title}* — {desc}")
        if len(lines) == 1:
            self.send_message(f"⚡ Nenhuma skill encontrada para `{label}`.")
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
            "Liste os agentes no topo do vault (leia o frontmatter de cada agent-info.md). "
            "Pergunte qual deseja editar e o que quer mudar (personalidade, instrucoes, modelo, icone). "
            "Faca a edicao nos arquivos agent-info.md e/ou CLAUDE.md do agente e confirme."
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
            "Execute a skill de criacao de agentes. "
            "Leia Skills/create-agent.md para instrucoes. "
            "Ajude o usuario a criar um novo agente como subdiretório direto do vault. "
            "Faca as perguntas necessarias sobre: nome, personalidade, especializacoes, "
            "modelo padrao, e icone. "
            "Depois gere os arquivos, atualize vault/README.md, e registre no Journal."
        )
        # Inject Telegram context so the skill writes it to frontmatter automatically
        ctx = self._ctx
        if ctx and ctx.thread_id is not None:
            prompt += (
                f"\n\nContexto Telegram (injetado automaticamente pelo bot): "
                f"chat_id={ctx.chat_id!r}, thread_id={ctx.thread_id}. "
                "Inclua esses valores no frontmatter do agente — sem perguntar ao usuario."
            )
        if extra:
            prompt += f"\n\nO usuario disse: {extra}"
        self._run_claude_prompt(prompt)

    def cmd_agent_switch(self, agent_id: str) -> None:
        # Refresh agent chat map on every switch (catches new/updated agents)
        self._refresh_agent_chat_map()
        # Mark as manual override so auto-routing doesn't overwrite
        ctx = self._ctx
        if ctx:
            ctx._manual_override = True
        if agent_id == "none":
            # v3.0: "none" is equivalent to switching back to Main.
            session = self._get_session()
            session.agent = MAIN_AGENT_ID
            session.workspace = str(agent_base(MAIN_AGENT_ID))
            self.sessions.save()
            self.send_message("🤖 Agente resetado para Main.")
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
        isolated = workspace_dir(found["_id"])
        session.workspace = str(isolated) if isolated.is_dir() else str(agent_base(found["_id"]))
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
                          max_total_timeout: int = 3600,
                          inactivity_timeout: Optional[int] = None,
                          routine_mode: bool = False,
                          system_prompt: Optional[str] = SYSTEM_PROMPT,
                          force_tts: bool = False,
                          suppress_text: bool = False) -> None:
        # Resolve inactivity timeout: explicit param > user-configured /timeout value
        if inactivity_timeout is None:
            inactivity_timeout = self.timeout_seconds
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

        # Inject frozen context snapshot on the first message of an interactive session.
        # Frozen = built once, never updated mid-session, so prefix cache hits are preserved.
        if not _retry and not routine_mode and session.message_count == 1:
            frozen, journal_mtime = self._build_frozen_context(session)
            if frozen:
                effective_sp = (effective_sp + "\n\n" + frozen) if effective_sp else frozen
            # Record journal mtime so we can detect updates in later turns
            self._journal_mtimes[session.name] = journal_mtime

        # Detect journal updates mid-session: append a lightweight nudge to the USER PROMPT
        # (not system prompt) so prefix cache on the system prompt is preserved.
        elif not _retry and not routine_mode and session.message_count > 1:
            journal_path = Path(self._get_journal_path())
            try:
                current_mtime = journal_path.stat().st_mtime if journal_path.is_file() else 0.0
                recorded_mtime = self._journal_mtimes.get(session.name, 0.0)
                if current_mtime > recorded_mtime + 1:  # >1s tolerance for fs precision
                    self._journal_mtimes[session.name] = current_mtime
                    prompt = (
                        f"[Nota: o journal de hoje foi atualizado desde o início desta sessão. "
                        f"Se precisar de contexto recente, consulte {journal_path}]\n\n{prompt}"
                    )
            except OSError:
                pass

        # Inject relevant skills metadata for every interactive message (zero LLM cost).
        # Keyword match helps the agent discover and invoke skills proactively.
        if not _retry and not routine_mode and system_prompt is not None:
            relevant_skills = self._find_relevant_skills(prompt)
            if relevant_skills:
                skills_block = "\n\n## Available Skills (consider invoking if relevant):\n"
                for s in relevant_skills:
                    skills_block += f"- **{s['name']}**: {s['description']} (`{s['path']}`)\n"
                effective_sp = (effective_sp + skills_block) if effective_sp else skills_block

        # Active Memory (inspired by OpenClaw v2026.4.10) — proactive vault
        # context injection. Skipped for routines/pipelines (their `context:
        # minimal` already sets system_prompt=None), retries, and sessions
        # where the user ran /active-memory off. Fail-open: any error returns
        # None and this injection is simply skipped.
        if (not _retry
                and not routine_mode
                and system_prompt is not None
                and getattr(session, "active_memory", True)):
            try:
                am_block = _active_memory_lookup(prompt, agent_id=session.agent)
            except Exception as exc:
                logger.warning("Active Memory lookup raised: %s", exc)
                am_block = None
            if am_block:
                effective_sp = (
                    (effective_sp + "\n\n" + am_block) if effective_sp else am_block
                )

        # Graph-based skill hint (user-prompt prefix) — lightweight nudge sourced
        # from vault/.graphs/graph.json. Filters to the current agent's skills
        # only. Skipped for routines/pipelines (they carry their own context)
        # and for retries (already tagged).
        if (SKILL_HINTS_ENABLED and not _retry and not routine_mode
                and prompt is not None):
            try:
                hinted = _select_relevant_skills(prompt, agent_id=session.agent, max_n=3)
            except Exception as exc:
                logger.warning("Skill hint injection failed: %s", exc)
                hinted = []
            if hinted:
                hint_line = (
                    f"<hint>Relevant skills for this task: {', '.join(hinted)}. "
                    f"See Skills/ in your workspace for details.</hint>\n\n"
                )
                prompt = hint_line + prompt

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
            target=self._watchdog,
            args=(runner, no_output_timeout, max_total_timeout, inactivity_timeout),
            daemon=True)
        watchdog_thread.start()

        # Stream updates while runner is active
        self._stream_updates(runner_thread, runner, routine_mode=routine_mode)

        # Auto-recovery: classify error and retry if possible (first attempt only)
        if not _retry and runner.exit_code not in (0, 130, 2) and prompt is not None:
            raw_error = runner.stderr_text or (runner.error_text if not runner.result_text else "")
            if raw_error:
                kind = classify_error(raw_error)
                action, backoff, _ = get_recovery_plan(kind)
                if action != RecoveryAction.ABORT:
                    logger.info(
                        "Auto-recovery: kind=%s action=%s backoff=%ds",
                        kind.value, action.value, backoff,
                    )
                    self.send_message(f"🔄 _{kind.value} — tentando recuperar automaticamente..._")
                    if action == RecoveryAction.RETRY_AFTER_COMPACT:
                        self._auto_compact(session)
                        time.sleep(3)
                    if backoff > 0:
                        time.sleep(backoff)
                    self._run_claude_prompt(
                        prompt,
                        _retry=True,
                        no_output_timeout=no_output_timeout,
                        max_total_timeout=max_total_timeout,
                        inactivity_timeout=inactivity_timeout,
                        routine_mode=routine_mode,
                        system_prompt=system_prompt,
                        force_tts=force_tts,
                        suppress_text=suppress_text,
                    )
                    return

        # Finalize
        self._finalize_response(session, runner, prompt=prompt if not _retry else None,
                                routine_mode=routine_mode, force_tts=tts_this_request,
                                suppress_text=force_tts)

        # Process queued messages for this context
        self._process_pending()

    def _watchdog(self, runner: ClaudeRunner,
                  no_output_timeout: int = 90,
                  max_total_timeout: int = 3600,
                  inactivity_timeout: int = 120) -> None:
        """Watchdog with activity-aware timeouts.

        Three layers of protection:
        1. no_output_timeout — kills if Claude produces NO output at all since start
           (detects CLI boot failures, auth errors). Thinking events count as activity.
        2. inactivity_timeout — kills if no new JSON events for N seconds.
           If the process is still alive (poll() is None), waits 2x the limit before
           killing (the process may be waiting on an API response). If the process
           is dead, kills immediately at 1x.
        3. max_total_timeout — absolute ceiling (default 1h). Safety net against
           infinite loops. Only kills if ALSO inactive for at least 60s, so a
           genuinely productive agent near the ceiling isn't killed mid-sentence.
        """
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

            # Layer 1: No output at all since start (CLI may have failed to boot)
            if not has_output and not is_thinking:
                elapsed_start = now - runner.start_time
                if elapsed_start > no_output_timeout:
                    logger.warning("No-output timeout after %.0fs", elapsed_start)
                    self.send_message(f"⏰ Timeout — Claude não produziu nenhum output em {int(elapsed_start)}s. Cancelando...")
                    runner.cancel()
                    break
                continue

            idle = now - runner.last_activity
            elapsed_total = now - runner.start_time
            proc = runner.process
            process_alive = proc and proc.poll() is None

            # Layer 2: Inactivity timeout (no new JSON events)
            if idle > inactivity_timeout:
                if not process_alive:
                    # Process already dead but thread lingering — clean up
                    logger.warning("Activity timeout after %.0fs of silence (process dead)", idle)
                    self.send_message(f"⏰ Timeout — Claude ficou {int(idle)}s sem atividade. Cancelando...")
                    runner.cancel()
                    break
                elif idle > inactivity_timeout * 2:
                    # Process alive but completely silent for 2x the limit — likely hung
                    logger.warning("Activity timeout after %.0fs of silence (process hung)", idle)
                    self.send_message(f"⏰ Timeout — Claude está sem responder há {int(idle)}s. Cancelando...")
                    runner.cancel()
                    break

            # Layer 3: Absolute ceiling — safety net against infinite loops
            # Only kills if also idle for at least 60s (don't kill mid-work)
            if elapsed_total > max_total_timeout and idle > 60:
                logger.warning("Hard ceiling timeout after %.0fs (idle %.0fs)", elapsed_total, idle)
                self.send_message(f"⏰ Timeout — Claude rodou por {int(elapsed_total//60)}min e está inativo. Cancelando...")
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
            _track_cost(runner.cost_usd, model=session.model)

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

        # Activity log — record this response for journal audit
        if runner.exit_code in (None, 0) and prompt:
            # Skip internal bot prompts — not real user activity
            if prompt.startswith("Consolide esta sessao") or prompt == "/compact":
                pass
            # Skip pipeline step entries — logged separately by _notify_success/_notify_failure
            elif routine_mode and prompt.startswith("[PIPELINE:"):
                pass
            elif routine_mode:
                session = self._get_session()
                m = re.match(r'\[ROTINA:\s*([^\|]+)\|\s*([^\]]+)', prompt)
                routine_name = m.group(1).strip() if m else "unknown"
                _log_activity({
                    "agent": (session.agent if session else None) or "main",
                    "type": "routine",
                    "routine": routine_name,
                    "session": routine_name,
                })
            else:
                # Interactive sessions: log FULL user message + response for reliable journal audit.
                # This is the source of truth — the nightly audit reads these to write journal entries.
                session = self._get_session()
                response = (runner.result_text or runner.accumulated_text or "").strip()
                _log_activity({
                    "agent": (session.agent if session else None) or "main",
                    "type": "interactive",
                    "session": session.name if session else "unknown",
                    "model": session.model if session else "unknown",
                    "user": prompt,
                    "response": response[:500],
                })

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
            isolated = workspace_dir(task.agent)
            session.workspace = str(isolated) if isolated.is_dir() else str(agent_base(task.agent))
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
                  f"Não adicione cabeçalho, confirmação de execução, nem frase dizendo que a rotina rodou.\n\n")
        if task.webhook_payload:
            prompt += (
                f"Webhook payload recebido:\n```\n{task.webhook_payload}\n```\n\n"
            )
        prompt += task_prompt

        # Send progress message so it can be updated on failure/cancellation
        progress_msg_id = self.send_message(f"🔁 _Executando rotina *{task.name}*..._",
                                                   disable_notification=True)

        # Checkpoint vault state before execution — allows rollback on failure
        checkpoint_ref = vault_checkpoint_create(f"routine-{task.name}")

        saved_effort = self.effort
        if task.effort:
            self.effort = task.effort
        try:
            self._run_claude_prompt(prompt, no_output_timeout=300, max_total_timeout=3600,
                                    inactivity_timeout=300,
                                    routine_mode=True,
                                    system_prompt=None if task.minimal_context else SYSTEM_PROMPT,
                                    force_tts=task.voice or inline_tts)
            # Check if there was an error or cancellation
            runner = self.runner
            if runner.exit_code == 130:
                # Manually cancelled — restore checkpoint
                if checkpoint_ref:
                    vault_checkpoint_restore(checkpoint_ref)
                self.routine_state.set_status(task.name, task.time_slot, "cancelled")
                if progress_msg_id:
                    self.edit_message(progress_msg_id, f"🛑 Rotina *{task.name}* cancelada.")
            elif runner.error_text:
                # Error — restore checkpoint
                if checkpoint_ref:
                    vault_checkpoint_restore(checkpoint_ref)
                self.routine_state.set_status(task.name, task.time_slot, "failed", runner.error_text[:200])
                if progress_msg_id:
                    self.edit_message(progress_msg_id, f"❌ Rotina *{task.name}* falhou: {runner.error_text[:200]}")
                # Compound engineering: draft a lesson from this failure
                lesson_path = record_lesson_draft(
                    task.name, runner.error_text, kind="routine",
                    agent_id=task.agent or MAIN_AGENT_ID,
                )
                if lesson_path:
                    try:
                        try:
                            rel = lesson_path.relative_to(VAULT_DIR)
                        except ValueError:
                            rel = lesson_path
                        self.send_message(
                            f"📝 Rascunho de lição: `{rel}`",
                            disable_notification=True,
                        )
                    except Exception as exc:
                        logger.error("Routine lesson-draft notify failed: %s", exc)
            else:
                # Success — commit checkpoint (drop stash, keep new state)
                if checkpoint_ref:
                    vault_checkpoint_drop(checkpoint_ref)
                self.routine_state.set_status(task.name, task.time_slot, "completed")
                # Success: delete progress message (output was already sent by _finalize_response)
                if progress_msg_id:
                    self.delete_message(progress_msg_id)
        except Exception as exc:
            logger.error("Routine %s failed: %s", task.name, exc)
            if checkpoint_ref:
                vault_checkpoint_restore(checkpoint_ref)
            self.routine_state.set_status(task.name, task.time_slot, "failed", str(exc)[:200])
            if progress_msg_id:
                self.edit_message(progress_msg_id, f"❌ Rotina *{task.name}* falhou: {str(exc)[:300]}")
            else:
                self.send_message(f"❌ Rotina *{task.name}* falhou: {str(exc)[:300]}")
            # Compound engineering: draft a lesson from this failure
            lesson_path = record_lesson_draft(
                task.name, str(exc), kind="routine",
                agent_id=task.agent or MAIN_AGENT_ID,
            )
            if lesson_path:
                try:
                    try:
                        rel = lesson_path.relative_to(VAULT_DIR)
                    except ValueError:
                        rel = lesson_path
                    self.send_message(
                        f"📝 Rascunho de lição: `{rel}`",
                        disable_notification=True,
                    )
                except Exception as notify_exc:
                    logger.error("Routine lesson-draft notify failed: %s", notify_exc)
        finally:
            self.effort = saved_effort

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
                "/glm": lambda: self.cmd_model_switch("glm-4.7"),
                "/model": lambda: self.cmd_model_keyboard(),
                "/new": lambda: self.cmd_new(arg if arg else None),
                "/sessions": lambda: self.cmd_sessions_list(),
                "/switch": lambda: self.cmd_switch(arg) if arg else self.send_message("❌ Use: `/switch <nome>`"),
                "/delete": lambda: self.cmd_delete(arg) if arg else self.send_message("❌ Use: `/delete <nome>`"),
                "/clone": lambda: self.cmd_clone(arg),
                "/lesson": lambda: self.cmd_lesson(arg),
                "/compact": lambda: self.cmd_compact(),
                "/cost": lambda: self.cmd_cost(),
                "/doctor": lambda: self.cmd_doctor(),
                "/lint": lambda: self.cmd_lint(),
                "/find": lambda: self.cmd_find(arg),
                "/indexes": lambda: self.cmd_indexes(),
                "/stop": lambda: self.cmd_stop(arg),
                "/timeout": lambda: self.cmd_timeout(arg) if arg else self.send_message(f"ℹ️ Timeout atual: {self.timeout_seconds}s"),
                "/workspace": lambda: self.cmd_workspace(arg) if arg else self.send_message("❌ Use: `/workspace <path>`"),
                "/effort": lambda: self.cmd_effort(arg) if arg else self.send_message(f"ℹ️ Effort atual: {self.effort or 'padrão'}"),
                "/btw": lambda: self.cmd_btw(arg) if arg else self.send_message("❌ Use: `/btw <mensagem>`"),
                "/delegate": lambda: self.cmd_delegate(arg) if arg else self.send_message("❌ Use: `/delegate <prompt>`"),
                "/clear": lambda: self.cmd_clear(),
                "/important": lambda: self.cmd_important(),
                "/routine": lambda: self.cmd_routine(arg),
                "/run": lambda: self.cmd_run(arg),
                "/agent": lambda: self.cmd_agent(arg),
                "/skill": lambda: self.cmd_skill(arg),
                "/audio": lambda: self.cmd_audio(),
                "/voice": lambda: self.cmd_voice(arg),
                "/active-memory": lambda: self.cmd_active_memory(arg),
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
                        md_file = _find_routine_file(name)
                        if md_file is None:
                            self._respond(404, {"error": "routine not found"})
                            return
                        fm, routine_body = get_frontmatter_and_body(md_file)
                        if not fm or not routine_body:
                            self._respond(400, {"error": "invalid routine file"})
                            return
                        owning_agent = md_file.parent.parent.name if md_file.parent.parent.parent == VAULT_DIR else MAIN_AGENT_ID
                        # Check if this is a pipeline
                        if str(fm.get("type", "routine")) == "pipeline":
                            bot.scheduler._enqueue_pipeline_from_file(
                                md_file, fm, routine_body, name,
                                str(fm.get("model", "sonnet")), time_slot)
                            self._respond(200, {"ok": True, "type": "pipeline"})
                            return
                        _effort_raw = str(fm.get("effort", "")).lower().strip()
                        task = RoutineTask(
                            name=name,
                            prompt=routine_body,
                            model=str(fm.get("model", "sonnet")),
                            time_slot=time_slot,
                            agent=owning_agent,
                            minimal_context=bool(fm.get("context") == "minimal"),
                            effort=_effort_raw if _effort_raw in ("low", "medium", "high") else None,
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

    def _start_webhook_server(self) -> None:
        """Start a dedicated HTTP server for webhook/Reaction endpoints.

        Runs on WEBHOOK_PORT (separate from the control server) so that only
        webhook routes are exposed when the user enables Tailscale Funnel.
        The control server (CONTROL_PORT) stays 100% local.
        """
        bot = self

        def _render_template(template: str, payload_obj: Any, raw_body: str) -> str:
            """Replace {{key}} placeholders with values from parsed JSON payload.

            Supports dotted paths (e.g. {{data.ticker}}). Unknown keys are left
            as empty strings. {{raw}} inserts the full raw body.
            """
            def _resolve(path: str) -> str:
                if path == "raw":
                    return raw_body
                cur: Any = payload_obj
                for part in path.split("."):
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    else:
                        return ""
                if cur is None:
                    return ""
                if isinstance(cur, (dict, list)):
                    return json.dumps(cur, ensure_ascii=False)
                return str(cur)

            def _sub(match: "re.Match[str]") -> str:
                return _resolve(match.group(1).strip())

            return re.sub(r"\{\{\s*([\w\.]+)\s*\}\}", _sub, template)

        class _WebhookHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health":
                    self._respond(200, {"status": "ok", "service": "webhook"})
                else:
                    self._respond(404, {"error": "not found"})

            def do_POST(self):
                if not self.path.startswith("/webhook/"):
                    return self._respond(404, {"error": "not found"})
                self._handle_webhook()

            def _handle_webhook(self):
                reaction_id = self.path[len("/webhook/"):].split("?", 1)[0].strip("/")
                if not reaction_id:
                    return self._respond(401, {"error": "unauthorized"})

                # Read body (capped)
                try:
                    length = int(self.headers.get("Content-Length", "0") or "0")
                except ValueError:
                    length = 0
                if length > WEBHOOK_MAX_BODY_BYTES:
                    return self._respond(413, {"error": "payload too large"})
                raw_bytes = self.rfile.read(length) if length > 0 else b""
                raw_body = raw_bytes.decode("utf-8", errors="replace")

                # Load reaction (missing/disabled → uniform 401 so we don't leak existence)
                reaction = load_reaction(reaction_id)
                if not reaction:
                    return self._respond(401, {"error": "unauthorized"})

                # Parse query string for token auth via ?token=
                query_token = ""
                if "?" in self.path:
                    try:
                        qs = urllib.parse.parse_qs(self.path.split("?", 1)[1])
                        query_token = (qs.get("token") or [""])[0]
                    except Exception:
                        query_token = ""

                auth = reaction["auth"]
                mode = auth.get("mode", "token")
                if mode == "token":
                    expected = auth.get("token") or ""
                    provided = self.headers.get("X-Reaction-Token", "") or query_token
                    if not expected or not hmac.compare_digest(expected, provided):
                        return self._respond(401, {"error": "unauthorized"})
                elif mode == "hmac":
                    secret = auth.get("hmac_secret") or ""
                    header_name = auth.get("hmac_header") or "X-Signature"
                    algo = auth.get("hmac_algo") or "sha256"
                    provided_sig = self.headers.get(header_name, "") or ""
                    if not secret or not provided_sig:
                        return self._respond(401, {"error": "unauthorized"})
                    # Strip "sha256=" prefix convention
                    if provided_sig.lower().startswith(f"{algo}="):
                        provided_sig = provided_sig.split("=", 1)[1]
                    try:
                        digestmod = getattr(hashlib, algo)
                    except AttributeError:
                        return self._respond(401, {"error": "unauthorized"})
                    computed = hmac.new(secret.encode("utf-8"), raw_bytes, digestmod).hexdigest()
                    if not hmac.compare_digest(computed, provided_sig):
                        return self._respond(401, {"error": "unauthorized"})
                else:
                    return self._respond(401, {"error": "unauthorized"})

                # Parse payload as JSON if possible (for template interpolation)
                payload_obj: Any = None
                try:
                    if raw_body.strip():
                        payload_obj = json.loads(raw_body)
                except Exception:
                    payload_obj = None

                action = reaction["action"]
                forwarded = False
                routine_enqueued = False
                errors: List[str] = []

                # 1) Forward to Telegram
                if action.get("forward"):
                    try:
                        template = action.get("forward_template") or "{{raw}}"
                        text = _render_template(template, payload_obj, raw_body)
                        # Resolve agent → chat_id/thread_id
                        chat_id: Optional[str] = None
                        thread_id: Optional[str] = None
                        agent_id = action.get("agent")
                        if agent_id:
                            agent_md = agent_info_path(str(agent_id))
                            if agent_md.exists():
                                a_fm, _ = get_frontmatter_and_body(agent_md)
                                acid = a_fm.get("chat_id") or a_fm.get("telegram_chat_id")
                                atid = a_fm.get("thread_id") or a_fm.get("telegram_thread_id")
                                if acid:
                                    chat_id = str(acid)
                                if atid is not None:
                                    thread_id = str(atid)
                        header = f"🪝 *{reaction['title']}*\n\n"
                        bot.send_message(header + text, chat_id=chat_id, thread_id=thread_id)
                        forwarded = True
                    except Exception as exc:
                        logger.error("Reaction %s forward failed: %s", reaction_id, exc)
                        errors.append(f"forward: {exc}")

                # 2) Execute routine/pipeline
                routine_name = action.get("routine")
                if routine_name:
                    try:
                        md_file = _find_routine_file(routine_name)
                        if md_file is None:
                            raise FileNotFoundError(f"routine {routine_name} not found")
                        r_fm, r_body = get_frontmatter_and_body(md_file)
                        if not r_fm or not r_body:
                            raise ValueError(f"invalid routine {routine_name}")
                        owning_agent = md_file.parent.parent.name if md_file.parent.parent.parent == VAULT_DIR else MAIN_AGENT_ID
                        time_slot = f"webhook-{int(time.time())}"
                        if str(r_fm.get("type", "routine")) == "pipeline":
                            # Pipelines don't yet support payload injection — log a warning
                            # but still run them so the user gets an immediate trigger.
                            logger.warning(
                                "Reaction %s triggers pipeline %s — payload is NOT injected (unsupported)",
                                reaction_id, routine_name)
                            bot.scheduler._enqueue_pipeline_from_file(
                                md_file, r_fm, r_body, routine_name,
                                str(r_fm.get("model", "sonnet")), time_slot)
                        else:
                            _effort_raw = str(r_fm.get("effort", "")).lower().strip()
                            task = RoutineTask(
                                name=routine_name,
                                prompt=r_body,
                                model=str(r_fm.get("model", "sonnet")),
                                time_slot=time_slot,
                                agent=owning_agent,
                                minimal_context=bool(r_fm.get("context") == "minimal"),
                                voice=bool(r_fm.get("voice", False)),
                                effort=_effort_raw if _effort_raw in ("low", "medium", "high") else None,
                                webhook_payload=raw_body,
                            )
                            bot.routine_state.set_status(routine_name, time_slot, "running")
                            bot._enqueue_routine(task)
                        routine_enqueued = True
                    except Exception as exc:
                        logger.error("Reaction %s routine trigger failed: %s", reaction_id, exc)
                        errors.append(f"routine: {exc}")
                        # Visibility: notify the user so errors never happen silently
                        try:
                            bot.send_message(
                                f"⚠️ Reaction *{reaction['title']}* falhou ao executar rotina: `{exc}`"
                            )
                        except Exception:
                            pass

                logger.info(
                    "Reaction %s fired (forward=%s, routine=%s, errors=%d)",
                    reaction_id, forwarded, routine_enqueued, len(errors),
                )
                _record_reaction_fire(
                    reaction_id,
                    forwarded=forwarded,
                    routine_enqueued=routine_enqueued,
                    errors=len(errors),
                )
                self._respond(200, {
                    "ok": True,
                    "forwarded": forwarded,
                    "routine_enqueued": routine_enqueued,
                    "errors": errors,
                })

            def _respond(self, code, data):
                try:
                    body = json.dumps(data).encode()
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except Exception as exc:
                    logger.error("Webhook response error: %s", exc)

            def log_message(self, *args):
                pass  # suppress default HTTP logging

        try:
            server = http.server.HTTPServer(("127.0.0.1", WEBHOOK_PORT), _WebhookHandler)
            self._webhook_server = server
            threading.Thread(target=server.serve_forever, daemon=True, name="webhook-server").start()
            logger.info("Webhook server listening on 127.0.0.1:%d", WEBHOOK_PORT)
        except Exception as exc:
            self._webhook_server = None
            logger.error("Failed to start webhook server: %s", exc)

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
                        def _handle(u=update, c=self._ctx, new=is_new_topic, ct=chat_type, tid=thread_id, cid=chat_id):
                            try:
                                self._ctx = c
                                # Auto-routing: check if this chat/thread is mapped to an agent
                                if ct in ("group", "supergroup"):
                                    mapped_agent = self._find_agent_for_chat(cid, tid)
                                    if mapped_agent and not c._manual_override:
                                        # Ensure agent is active (covers new topics + bot restarts)
                                        session = self._get_session()
                                        if session.agent != mapped_agent["_id"]:
                                            self._auto_activate_agent(mapped_agent)
                                    elif new and tid:
                                        # No mapping — show onboarding keyboard for new topics
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

        _shutdown_thread: list = [None]  # mutable cell so the join below can access it

        def _sigterm_handler(signum, frame):
            logger.info("Received SIGTERM, initiating graceful shutdown.")
            # Run bot.stop() in a thread — calling subprocess.Popen() (used by
            # _consolidate_all_sessions) from within a signal handler is unsafe
            # on macOS (posix_spawn/fork+exec restrictions) and causes a spurious
            # FileNotFoundError even when the binary exists.
            t = threading.Thread(target=bot.stop, name="graceful-shutdown", daemon=False)
            _shutdown_thread[0] = t
            t.start()

        signal.signal(signal.SIGTERM, _sigterm_handler)

        try:
            bot.run()
        except KeyboardInterrupt:
            bot.stop()

        # If shutdown was triggered by SIGTERM, wait for the consolidation thread
        # to finish before the process exits so session notes are not lost.
        t = _shutdown_thread[0]
        if t and t.is_alive():
            t.join(timeout=30)
