#!/usr/bin/env python3
"""Send a Telegram message (or photo album) to the correct topic for an agent.

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
    python3 telegram_notify.py --images a.png,b.png "Caption for album"
    python3 telegram_notify.py --images one.png "Single photo caption"

Environment (all injected by bot harness into every subprocess):
    TELEGRAM_NOTIFY     — absolute path to this script (use instead of hardcoded path)
    AGENT_ID            — owning agent ID for auto-detection
    AGENT_CHAT_ID       — Telegram chat_id for the owning agent
    AGENT_THREAD_ID     — Telegram thread_id for the owning agent (empty if none)
    TELEGRAM_BOT_TOKEN  — required (read from project .env if not set in env)
"""

import argparse
import json
import mimetypes
import os
import sys
import urllib.request
import urllib.parse
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
VAULT_DIR = PROJECT_DIR / "vault"

# Telegram allows up to 10 media items per sendMediaGroup call.
MEDIA_GROUP_MAX = 10


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


def _build_multipart(fields: dict, files: list) -> tuple[bytes, str]:
    """Hand-build a multipart/form-data body.

    fields: dict of str -> str (regular form fields).
    files:  list of (field_name, filename, content_bytes, content_type).
    Returns (body_bytes, content_type_header).
    """
    boundary = f"----telegramNotify{uuid.uuid4().hex}"
    crlf = b"\r\n"
    body_parts: list[bytes] = []
    boundary_bytes = boundary.encode()

    for name, value in fields.items():
        if value is None:
            continue
        body_parts.append(b"--" + boundary_bytes + crlf)
        body_parts.append(
            f'Content-Disposition: form-data; name="{name}"'.encode() + crlf
        )
        body_parts.append(crlf)
        body_parts.append(str(value).encode("utf-8") + crlf)

    for field_name, filename, content, ctype in files:
        body_parts.append(b"--" + boundary_bytes + crlf)
        disp = (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{filename}"'
        ).encode() + crlf
        body_parts.append(disp)
        body_parts.append(f"Content-Type: {ctype}".encode() + crlf)
        body_parts.append(crlf)
        body_parts.append(content + crlf)

    body_parts.append(b"--" + boundary_bytes + b"--" + crlf)
    body = b"".join(body_parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return body, content_type


def send_photo(token: str, chat_id: str, image_path: Path,
               caption: str = None, thread_id: int = None,
               parse_mode: str = None,
               disable_notification: bool = False) -> dict:
    """Send a single photo via sendPhoto."""
    fields: dict = {"chat_id": chat_id}
    if thread_id is not None:
        fields["message_thread_id"] = str(thread_id)
    if caption:
        fields["caption"] = caption
    if parse_mode:
        fields["parse_mode"] = parse_mode
    if disable_notification:
        fields["disable_notification"] = "true"

    content = image_path.read_bytes()
    ctype = mimetypes.guess_type(str(image_path))[0] or "application/octet-stream"
    files = [("photo", image_path.name, content, ctype)]

    body, content_type = _build_multipart(fields, files)
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    req.add_header("Content-Length", str(len(body)))

    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def send_media_group(token: str, chat_id: str, image_paths: list,
                     caption: str = None, thread_id: int = None,
                     parse_mode: str = None,
                     disable_notification: bool = False) -> dict:
    """Send 2-10 photos as an album via sendMediaGroup.

    Caption (if provided) attaches to the first item only — Telegram's convention.
    """
    if not (2 <= len(image_paths) <= MEDIA_GROUP_MAX):
        raise ValueError(
            f"sendMediaGroup requires 2..{MEDIA_GROUP_MAX} images, got {len(image_paths)}"
        )

    media_array = []
    files = []
    for idx, path in enumerate(image_paths):
        attach_name = f"file{idx}"
        item = {"type": "photo", "media": f"attach://{attach_name}"}
        if idx == 0 and caption:
            item["caption"] = caption
            if parse_mode:
                item["parse_mode"] = parse_mode
        media_array.append(item)

        content = path.read_bytes()
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        files.append((attach_name, path.name, content, ctype))

    fields: dict = {
        "chat_id": chat_id,
        "media": json.dumps(media_array),
    }
    if thread_id is not None:
        fields["message_thread_id"] = str(thread_id)
    if disable_notification:
        fields["disable_notification"] = "true"

    body, content_type = _build_multipart(fields, files)
    url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    req.add_header("Content-Length", str(len(body)))

    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_image_paths(spec: str) -> list[Path]:
    """Parse a comma-separated list of image paths and validate existence."""
    paths = []
    for raw in spec.split(","):
        p = raw.strip()
        if not p:
            continue
        path = Path(p).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")
        paths.append(path)
    if not paths:
        raise ValueError("--images: no valid paths provided")
    return paths


def main():
    parser = argparse.ArgumentParser(
        description="Send Telegram message (or photo album) to agent's topic",
        epilog="Agent is auto-detected from AGENT_ID env var or CWD if --agent is omitted.",
    )
    parser.add_argument("--agent", default=None,
                        help="Agent ID (e.g., parmeirense). Auto-detected if omitted.")
    parser.add_argument("--text", help="Message text")
    parser.add_argument("--stdin", action="store_true", help="Read message from stdin")
    parser.add_argument("--parse-mode", choices=["Markdown", "MarkdownV2", "HTML"],
                        default=None, help="Telegram parse mode")
    parser.add_argument("--silent", action="store_true", help="Disable notification sound")
    parser.add_argument("--images", default=None,
                        help="Comma-separated image paths. 1 image -> sendPhoto; "
                             "2-10 -> sendMediaGroup; 11+ chunked.")
    parser.add_argument("message", nargs="?", default=None,
                        help="Message text / caption (positional alternative to --text)")
    args = parser.parse_args()

    # Resolve message text / caption (optional when sending images)
    text = None
    if args.stdin:
        text = sys.stdin.read().strip()
    elif args.text:
        text = args.text
    elif args.message:
        text = args.message

    if not args.images:
        if not text:
            print("Error: provide message text, --text, or --stdin (or --images)",
                  file=sys.stderr)
            sys.exit(1)

    # Pipeline v2 anti-pattern detection: when this script is invoked from
    # inside a v2 step subprocess (PIPELINE_DATA_DIR is set by the executor
    # for every script/validate/llm step), it's almost always a leak — the
    # v2 convention is that ONLY `publish` steps with declared sinks reach
    # the user, and the publish sink uses bot.send_message() internally,
    # NOT this script. We emit a loud warning to stderr so the leak surfaces
    # in pipeline logs (and grep audits) without breaking legitimate v1
    # routine use (routines don't set PIPELINE_DATA_DIR).
    pipeline_data_dir = os.environ.get("PIPELINE_DATA_DIR", "").strip()
    if pipeline_data_dir:
        step_id = os.environ.get("PIPELINE_STEP_ID", "<unknown>")
        print(
            f"WARN: telegram_notify.py invoked from inside Pipeline v2 step "
            f"'{step_id}' (PIPELINE_DATA_DIR={pipeline_data_dir}). This is a "
            f"leak — only `publish` steps with declared sinks may reach the "
            f"user. See vault/Skills/create-pipeline.md §9 (Telegram-safe "
            f"stdout) for the right pattern. Sending anyway for backcompat.",
            file=sys.stderr,
        )

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

    # Image path: dispatch to sendPhoto / sendMediaGroup (with chunking).
    if args.images:
        try:
            paths = _parse_image_paths(args.images)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        # Chunk into groups of MEDIA_GROUP_MAX. Caption attaches to the
        # first chunk's first item; subsequent chunks have no caption.
        chunks = [paths[i:i + MEDIA_GROUP_MAX]
                  for i in range(0, len(paths), MEDIA_GROUP_MAX)]
        first = True
        for chunk in chunks:
            chunk_caption = text if first else None
            if len(chunk) == 1:
                result = send_photo(
                    token, chat_id, chunk[0],
                    caption=chunk_caption,
                    thread_id=thread_id,
                    parse_mode=args.parse_mode,
                    disable_notification=args.silent,
                )
            else:
                result = send_media_group(
                    token, chat_id, chunk,
                    caption=chunk_caption,
                    thread_id=thread_id,
                    parse_mode=args.parse_mode,
                    disable_notification=args.silent,
                )
            if not result.get("ok"):
                print(f"Error: {result}", file=sys.stderr)
                sys.exit(1)
            first = False

        print(f"Sent {len(paths)} image(s) in {len(chunks)} call(s) "
              f"to chat={chat_id} thread={thread_id} (agent={agent_id})")
        return

    # Text-only path
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
