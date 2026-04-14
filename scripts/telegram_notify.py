#!/usr/bin/env python3
"""Send a Telegram message to the correct topic for a given agent.

Resolves chat_id and thread_id from the agent's frontmatter file,
ensuring a single source of truth for routing.

Agent auto-detection (priority order):
    1. --agent flag (explicit override)
    2. AGENT_ID env var (set by the bot harness)
    3. CWD-based detection (extracts from vault/<agent>/... path)

Usage:
    python3 telegram_notify.py "Hello world"
    python3 telegram_notify.py --agent parmeirense "Hello world"
    python3 telegram_notify.py --text "Hello" --parse-mode Markdown
    echo "message body" | python3 telegram_notify.py --stdin
    python3 telegram_notify.py --stdin --silent

Environment (all injected by bot harness into every subprocess):
    TELEGRAM_NOTIFY     — absolute path to this script (use instead of hardcoded path)
    AGENT_ID            — owning agent ID for auto-detection
    AGENT_CHAT_ID       — Telegram chat_id for the owning agent
    AGENT_THREAD_ID     — Telegram thread_id for the owning agent (empty if none)
    TELEGRAM_BOT_TOKEN  — required (read from project .env if not set in env)
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
VAULT_DIR = PROJECT_DIR / "vault"


def _load_env_file(path: Path) -> None:
    """Load key=value pairs from a .env file into os.environ (no overwrite)."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def _parse_frontmatter(path: Path) -> dict:
    """Extract YAML frontmatter as a flat dict (simple key: value parsing)."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("---", 3)
    if end == -1:
        return {}
    fm = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip("\"'")
            if key and val:
                fm[key] = val
    return fm


def _detect_agent_from_cwd() -> str | None:
    """Infer agent ID from the current working directory.

    Expects CWD to be somewhere under vault/<agent>/... — extracts the
    directory name immediately under vault/.
    """
    try:
        cwd = Path.cwd().resolve()
        vault = VAULT_DIR.resolve()
        rel = cwd.relative_to(vault)
        # First component is the agent directory
        parts = rel.parts
        if parts:
            return parts[0]
    except (ValueError, RuntimeError):
        pass
    return None


def detect_agent(explicit: str | None = None) -> str:
    """Return agent ID using the priority chain: explicit > env > CWD.

    Raises ValueError if no agent can be determined.
    """
    if explicit:
        return explicit

    from_env = os.environ.get("AGENT_ID", "").strip()
    if from_env:
        return from_env

    from_cwd = _detect_agent_from_cwd()
    if from_cwd:
        return from_cwd

    raise ValueError(
        "Cannot determine agent. Provide --agent, set AGENT_ID env var, "
        "or run from within vault/<agent>/."
    )


def _find_agent_file(agent_id: str) -> Path:
    """Locate the agent's frontmatter file.

    Checks agent-<id>.md first (v3.4+ convention), then falls back to
    agent-info.md for compatibility.
    """
    primary = VAULT_DIR / agent_id / f"agent-{agent_id}.md"
    if primary.is_file():
        return primary
    fallback = VAULT_DIR / agent_id / "agent-info.md"
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(
        f"Agent file not found: tried {primary} and {fallback}"
    )


def resolve_agent_routing(agent_id: str) -> tuple:
    """Return (chat_id: str, thread_id: int | None) from agent frontmatter."""
    agent_file = _find_agent_file(agent_id)
    fm = _parse_frontmatter(agent_file)

    chat_id = fm.get("chat_id") or fm.get("telegram_chat_id")
    if not chat_id:
        raise ValueError(f"No chat_id in {agent_file}")

    thread_id_raw = fm.get("thread_id") or fm.get("telegram_thread_id")
    thread_id = int(thread_id_raw) if thread_id_raw else None

    return str(chat_id), thread_id


def send_message(token: str, chat_id: str, text: str,
                 thread_id: int = None, parse_mode: str = None,
                 disable_notification: bool = False) -> dict:
    """Send a Telegram message via Bot API."""
    payload = {
        "chat_id": chat_id,
        "text": text,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if disable_notification:
        payload["disable_notification"] = True

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(
        description="Send Telegram message to agent's topic",
        epilog="Agent is auto-detected from AGENT_ID env var or CWD if --agent is omitted.",
    )
    parser.add_argument("--agent", default=None,
                        help="Agent ID (e.g., parmeirense). Auto-detected if omitted.")
    parser.add_argument("--text", help="Message text")
    parser.add_argument("--stdin", action="store_true", help="Read message from stdin")
    parser.add_argument("--parse-mode", choices=["Markdown", "MarkdownV2", "HTML"],
                        default=None, help="Telegram parse mode")
    parser.add_argument("--silent", action="store_true", help="Disable notification sound")
    parser.add_argument("message", nargs="?", default=None,
                        help="Message text (positional alternative to --text)")
    args = parser.parse_args()

    # Resolve message text
    if args.stdin:
        text = sys.stdin.read().strip()
    elif args.text:
        text = args.text
    elif args.message:
        text = args.message
    else:
        print("Error: provide message text, --text, or --stdin", file=sys.stderr)
        sys.exit(1)

    if not text:
        print("Error: empty message", file=sys.stderr)
        sys.exit(1)

    # Resolve agent (auto-detect if not explicit)
    try:
        agent_id = detect_agent(args.agent)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Load env files for TELEGRAM_BOT_TOKEN
    _load_env_file(PROJECT_DIR / ".env")
    _load_env_file(VAULT_DIR / ".env")

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Error: TELEGRAM_BOT_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    # Resolve routing from agent frontmatter
    try:
        chat_id, thread_id = resolve_agent_routing(agent_id)
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    result = send_message(token, chat_id, text,
                          thread_id=thread_id,
                          parse_mode=args.parse_mode,
                          disable_notification=args.silent)

    if result.get("ok"):
        print(f"Sent to chat={chat_id} thread={thread_id} (agent={agent_id})")
    else:
        print(f"Error: {result}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
