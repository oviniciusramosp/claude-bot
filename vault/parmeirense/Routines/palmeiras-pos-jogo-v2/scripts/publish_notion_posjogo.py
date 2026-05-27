#!/usr/bin/env python3
"""
palmeiras-pos-jogo-v2 — Step: publish-notion

Publishes the post-match article to Notion and updates the pos-jogo dedup state.

Reads:
  - PIPELINE_DATA_DIR/post-final.json
  - PIPELINE_DATA_DIR/match.json (for match_id + metadata to record in state)
  - vault/.env (NOTION_API_KEY, NOTION_PALMEIRAS_DB_ID)
  - pos-jogo-state.json (re-check dedup before POST)
  - $STEP_OVERRIDE_DRY_RUN (default false)

Writes:
  - $PIPELINE_STEP_OUTPUT_FILE (published.md — Telegram-format text)
  - pos-jogo-state.json updated with new entry (last 100)
  - vault/parmeirense/.workspace/published-index.jsonl (unified store —
    replaces the legacy pos-jogo-history.md write; the legacy file is
    left in place as a backup but is no longer updated).

Critical preserved logic from feed publish:
  1. Concurrent-execution lock
  2. Dual-key dedup (url_fonte + normalized titulo)
  3. Immediate state update right after successful POST
  4. Lock removed even on failure (try/finally)
"""

from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make repo's scripts/ importable for PublishedIndex.
_REPO_SCRIPTS = Path("/Users/viniciusramos/claude-bot/scripts")
if str(_REPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_REPO_SCRIPTS))

VAULT_ROOT = Path("/Users/viniciusramos/claude-bot/vault/parmeirense")
STATE_PATH = VAULT_ROOT / "pos-jogo-state.json"
HISTORY_PATH = VAULT_ROOT / "pos-jogo-history.md"
ENV_PATH = Path("/Users/viniciusramos/claude-bot/vault/.env")
LOCK_PATH = Path("/tmp/palmeiras-pos-jogo-publish.lock")
LOCK_MAX_AGE = 600
# Reuse the feed's scripts dir for shared helpers
FEED_SCRIPTS_DIR = VAULT_ROOT / "Routines" / "palmeiras-feed" / "scripts"
# notion_builder.py lives at Routines/palmeiras-feed/ (parent of scripts/)
FEED_DIR = VAULT_ROOT / "Routines" / "palmeiras-feed"
NOTION_VERSION = "2026-03-11"


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def emit_status(status: str, output_file: Optional[str], reason: str = "") -> None:
    print(json.dumps({"status": status, "output_file": output_file, "reason": reason}))
    sys.exit(0 if status in ("ready", "skipped") else 1)


def fail(reason: str, output: Optional[Path] = None) -> None:
    print(f"ERROR: {reason}", file=sys.stderr)
    LOCK_PATH.unlink(missing_ok=True)
    if output is not None:
        try:
            output.write_text(
                "🐷 Pós-Jogo — falha ao publicar (ver logs).",
                encoding="utf-8",
            )
        except OSError:
            pass
    emit_status("failed", str(output) if output else None, reason)


# ---------------------------------------------------------------------------
# Concurrency lock
# ---------------------------------------------------------------------------

def acquire_lock() -> bool:
    if LOCK_PATH.exists():
        age = time.time() - LOCK_PATH.stat().st_mtime
        if age < LOCK_MAX_AGE:
            print(f"INFO: lock held for {int(age)}s", file=sys.stderr)
            return False
        LOCK_PATH.unlink(missing_ok=True)
    try:
        LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError:
        return False


def release_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Env loader
# ---------------------------------------------------------------------------

def load_env() -> Dict[str, str]:
    if not ENV_PATH.is_file():
        return {}
    out: Dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def normalize_titulo(t: str) -> str:
    t = t.lower().strip()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def is_duplicate(post: Dict[str, Any], state: Dict[str, Any]) -> Optional[str]:
    url = post.get("url_fonte_primaria", "")
    titulo_norm = normalize_titulo(post.get("titulo", ""))
    for p in state.get("partidas_publicadas", []):
        if p.get("url_fonte") == url and url:
            return f"duplicate URL: {url}"
        if normalize_titulo(p.get("titulo", "")) == titulo_norm and titulo_norm:
            return f"duplicate titulo: '{post.get('titulo', '')[:60]}'"
    return None


# ---------------------------------------------------------------------------
# Image upload (delegates to feed's notion_upload.py)
# ---------------------------------------------------------------------------

def upload_image_to_notion(image_url: str) -> Optional[str]:
    helper = FEED_SCRIPTS_DIR / "notion_upload.py"
    if not helper.is_file():
        print(f"WARN: notion_upload.py not found at {helper}", file=sys.stderr)
        return None
    try:
        result = subprocess.run(
            ["python3", str(helper), "--url", image_url, "--env", str(ENV_PATH)],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            print(f"WARN: notion_upload exit {result.returncode}: "
                  f"{result.stderr[:200]}", file=sys.stderr)
            return None
        data = json.loads(result.stdout) if result.stdout else {}
        if data.get("status") == "uploaded":
            return data.get("id")
    except Exception as exc:
        print(f"WARN: notion_upload exception: {exc}", file=sys.stderr)
    return None


# ---------------------------------------------------------------------------
# State updates
# ---------------------------------------------------------------------------

def update_state(state: Dict[str, Any], post: Dict[str, Any],
                 match: Dict[str, Any], page_id: str, page_url: str) -> None:
    """Append entry; cap at last 100; write atomically."""
    brt = datetime.timezone(datetime.timedelta(hours=-3))
    entry = {
        "match_id": match.get("match_id"),
        "opponent": match.get("opponent_name", ""),
        "competition": match.get("competition", ""),
        "match_date": match.get("match_date_brt", ""),
        "score": match.get("score_string", ""),
        "result": match.get("result", ""),
        "titulo": post.get("titulo", ""),
        "url_fonte": post.get("url_fonte_primaria", ""),
        "notion_id": page_id,
        "notion_url": page_url,
        "publicado_em": datetime.datetime.now(brt).isoformat(),
    }
    state.setdefault("partidas_publicadas", []).append(entry)
    state["partidas_publicadas"] = state["partidas_publicadas"][-100:]
    tmp = STATE_PATH.with_suffix(STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s or "unknown"


def make_match_topic_key(match: Dict[str, Any]) -> str:
    """Prefer the SofaScore fixture id; fall back to date+opponent slug."""
    fid = match.get("match_id")
    if fid:
        return f"match:{fid}"
    date = (match.get("match_date_brt") or "")[:10]
    opp = _slug(match.get("opponent_name") or "")
    home = "palmeiras"  # club identity is fixed; opponent varies
    return f"match:{date}:{home}-vs-{opp}"


def record_in_published_index(post: Dict[str, Any], match: Dict[str, Any],
                              page_id: str, page_url: str) -> None:
    """Append the published entry to the unified parmeirense JSONL store.

    Best-effort: an error here is logged but does NOT fail the publish (the
    Notion POST already succeeded and pos-jogo-state.json was updated).
    """
    try:
        from published_index import PublishedIndex  # type: ignore
    except ImportError as exc:
        print(f"WARN: published_index import failed: {exc}", file=sys.stderr)
        return
    try:
        idx = PublishedIndex(agent_id="parmeirense")
        source_urls: List[str] = []
        primary = post.get("url_fonte_primaria") or ""
        if primary:
            source_urls.append(primary)
        for f in post.get("fontes") or []:
            url = (f or {}).get("url") or ""
            if url and url not in source_urls:
                source_urls.append(url)
        cover = ((post.get("imagem") or {}).get("url")) or None
        features = {
            "topic_type": "match-recap",
            "match_id": match.get("match_id"),
            "opponent": match.get("opponent_name"),
            "competition": match.get("competition"),
            "result": match.get("result"),
            "score": match.get("score_string"),
            "tone": post.get("tom") or post.get("tone"),
        }
        idx.add(
            pipeline="palmeiras-pos-jogo-v2",
            topic_key=make_match_topic_key(match),
            title=post.get("titulo") or "",
            source_urls=source_urls or None,
            notion={"page_id": page_id, "url": page_url} if page_id else None,
            cover_image=cover,
            features={k: v for k, v in features.items() if v is not None},
        )
    except Exception as exc:
        print(f"WARN: published-index write failed (non-fatal): {exc}",
              file=sys.stderr)


def update_history(post: Dict[str, Any], match: Dict[str, Any]) -> None:
    """Append to rolling 30-day history log; prune old entries."""
    brt = datetime.timezone(datetime.timedelta(hours=-3))
    now = datetime.datetime.now(brt)
    today = now.strftime("%Y-%m-%d")
    cutoff = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        content = HISTORY_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""

    lines = content.split("\n")
    pruned = []
    keep = True
    for ln in lines:
        if ln.startswith("## 20"):
            keep = ln.replace("## ", "").strip() >= cutoff
        if keep:
            pruned.append(ln)
    content = "\n".join(pruned).rstrip()

    titulo = post.get("titulo", "(sem título)")
    opponent = match.get("opponent_name", "")
    score = match.get("score_string", "")
    entry = f"- **{titulo}** [{opponent} {score}]"

    if f"## {today}" not in content:
        content = (content + "\n\n" if content else "") + f"## {today}\n\n"
    else:
        content += "\n"
    content = content + entry + "\n"
    HISTORY_PATH.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    output_str = os.environ.get("PIPELINE_STEP_OUTPUT_FILE", "")
    data_dir_str = os.environ.get("PIPELINE_DATA_DIR", "")
    if not output_str or not data_dir_str:
        fail("env not set")

    output = Path(output_str)
    data_dir = Path(data_dir_str)
    output.parent.mkdir(parents=True, exist_ok=True)

    dry_run = os.environ.get("STEP_OVERRIDE_DRY_RUN", "false").lower() in ("true", "1", "yes")

    # Read post-final.json
    post_path = data_dir / "post-final.json"
    if not post_path.exists():
        fail(f"post-final.json not found at {post_path}", output)
    raw_post = post_path.read_text(encoding="utf-8").strip()

    if raw_post in ("NO_POST", "NO_REPLY", ""):
        output.write_text("🐷 Pós-Jogo — sem matéria para publicar.", encoding="utf-8")
        emit_status("skipped", str(output), reason="upstream NO_POST")

    try:
        post = json.loads(raw_post)
    except json.JSONDecodeError as exc:
        fail(f"post-final.json invalid JSON: {exc}", output)

    # Read match.json
    match_path = data_dir / "match.json"
    try:
        match_raw = match_path.read_text(encoding="utf-8").strip()
        match = json.loads(match_raw) if match_raw not in ("NO_REPLY", "") else {}
    except Exception:
        match = {}

    # Acquire lock
    if not acquire_lock():
        output.write_text("🐷 Pós-Jogo — pulando (publish concorrente).", encoding="utf-8")
        emit_status("skipped", str(output), reason="concurrent_lock")

    try:
        env = load_env()
        notion_token = env.get("NOTION_API_KEY", "")
        db_id = env.get("NOTION_PALMEIRAS_DB_ID", "")
        if not notion_token or not db_id:
            fail("NOTION_API_KEY or NOTION_PALMEIRAS_DB_ID missing in vault/.env", output)

        # Upload image
        img = post.get("imagem", {}) or {}
        img_url = img.get("url", "")
        if img_url and not dry_run:
            file_upload_id = upload_image_to_notion(img_url)
            if file_upload_id:
                post["imagem"]["file_upload_id"] = file_upload_id
                post_path.write_text(json.dumps(post, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
                print(f"INFO: image uploaded — file_upload_id={file_upload_id}")

        # Build Notion page body (reuse feed's notion_builder)
        sys.path.insert(0, str(FEED_DIR))
        try:
            from notion_builder import post_to_notion_body  # type: ignore
        except ImportError as exc:
            fail(f"notion_builder import failed: {exc}", output)

        page_body = post_to_notion_body(post, db_id)

        # Re-check dedup before POST
        try:
            state = json.loads(STATE_PATH.read_text(encoding="utf-8")) \
                    if STATE_PATH.is_file() else {"partidas_publicadas": []}
        except (OSError, json.JSONDecodeError):
            state = {"partidas_publicadas": []}

        dup = is_duplicate(post, state)
        if dup:
            print(f"INFO: SKIP — {dup}")
            output.write_text("🐷 Pós-Jogo — já publicado.", encoding="utf-8")
            emit_status("skipped", str(output), reason=dup)

        if dry_run:
            print("INFO: DRY-RUN — not POSTing to Notion")
            output.write_text(
                f"🐷 Pós-Jogo — DRY-RUN (não publicado)\n\n"
                f"• {post.get('titulo', '')}",
                encoding="utf-8",
            )
            emit_status("ready", str(output), reason="dry-run completed (no Notion POST)")

        # POST to Notion
        body = json.dumps(page_body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            "https://api.notion.com/v1/pages",
            data=body,
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="ignore")[:500]
            fail(f"Notion POST {exc.code}: {err}", output)
        except Exception as exc:
            fail(f"Notion POST exception: {exc}", output)

        page_id = result.get("id", "")
        page_url = result.get("url") or f"https://www.notion.so/{page_id.replace('-', '')}"
        if not page_id:
            fail("Notion response missing page id", output)

        # Update state immediately
        update_state(state, post, match, page_id, page_url)

        # Record in the unified published-index.jsonl. The legacy
        # pos-jogo-history.md write was removed (the file remains on disk
        # as a backup but is no longer updated — see published_index.py).
        record_in_published_index(post, match, page_id, page_url)

        # Format result for Telegram
        opponent = match.get("opponent_name", "")
        score = match.get("score_string", "")
        result_word = match.get("result", "")
        result_icon = {"vitoria": "✅", "derrota": "❌", "empate": "🤝"}.get(result_word, "⚽")

        telegram_msg = (
            f"🐷 Pós-Jogo {result_icon}\n\n"
            f"• [{post.get('titulo', '')}]({page_url})"
        )
        if opponent and score:
            telegram_msg += f"\n\n{opponent} {score}"

        output.write_text(telegram_msg, encoding="utf-8")
        emit_status("ready", str(output), reason=f"published to Notion: {page_url}")

    finally:
        release_lock()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail(f"unhandled exception: {type(exc).__name__}: {exc}")
