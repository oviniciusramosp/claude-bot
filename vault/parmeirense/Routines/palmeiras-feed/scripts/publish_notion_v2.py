#!/usr/bin/env python3
"""Palmeiras Feed v2 — Step: publish-notion

Pipeline: palmeiras-feed-v2.md
Pipeline-version: 2
Step-id: publish-notion
Replaces: vault/parmeirense/Routines/palmeiras-feed/steps/palmeiras-feed-publish.md

Reads:
  - PIPELINE_DATA_DIR/post-final.json (writer + image)
  - vault/.env (NOTION_API_KEY, NOTION_PALMEIRAS_DB_ID)
  - feed-state.json (re-check dedup before POST)
  - $STEP_OVERRIDE_DRY_RUN (default false — when true, build payload but skip POST)

Writes:
  - $PIPELINE_STEP_OUTPUT_FILE (published.md — Telegram-format text)
  - feed-state.json updated with new entry (last 200)
  - vault/parmeirense/.workspace/published-index.jsonl (new unified store —
    replaces the legacy posts-history.md write; the legacy file is left
    in place as a backup but is no longer updated).

Critical preserved logic from v1:
  1. Concurrent-execution lock (/tmp/palmeiras-feed-publish.lock)
  2. Dual-key dedup (url_fonte + normalized titulo)
  3. Immediate state update right after successful POST
  4. State size cap = last 200 entries
  5. Lock removed even on failure (try/finally)

Reuses notion_builder.post_to_notion_body() and notion_upload.py helper.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

# Make repo's scripts/ importable for PublishedIndex.
_REPO_SCRIPTS = Path("/Users/viniciusramos/claude-bot/scripts")
if str(_REPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_REPO_SCRIPTS))

VAULT_ROOT = Path("/Users/viniciusramos/claude-bot/vault/parmeirense")
FEED_STATE_PATH = VAULT_ROOT / "feed-state.json"
POSTS_HISTORY_PATH = VAULT_ROOT / "posts-history.md"
ENV_PATH = Path("/Users/viniciusramos/claude-bot/vault/.env")
LOCK_PATH = Path("/tmp/palmeiras-feed-publish.lock")
LOCK_MAX_AGE = 600  # 10 min — older locks are stale
SCRIPTS_DIR = Path(__file__).parent
NOTION_VERSION = "2022-06-28"

# ---------------------------------------------------------------------------
# Status report helpers
# ---------------------------------------------------------------------------

def emit_status(status: str, output_file: Optional[str], reason: str = "",
                post_id: Optional[str] = None) -> None:
    payload: Dict[str, Any] = {"status": status, "output_file": output_file, "reason": reason}
    if post_id:
        # The harness's _execute_publish_step lifts this into sink_config so
        # _sink_telegram can backfill the published-index entry with the
        # delivered message_id (closes the reply-feedback loop).
        payload["post_id"] = post_id
    print(json.dumps(payload))
    sys.exit(0 if status in ("ready", "skipped") else 1)


def fail(reason: str, output: Optional[Path] = None) -> None:
    print(f"ERROR: {reason}", file=sys.stderr)
    if LOCK_PATH.exists():
        try:
            LOCK_PATH.unlink()
        except OSError:
            pass
    if output is not None:
        # Even on failure, write the friendly Telegram message so notify-telegram has something
        try:
            output.write_text(
                "🐷 Palmeiras Feed — falha ao publicar (ver logs).",
                encoding="utf-8",
            )
        except OSError:
            pass
    emit_status("failed", str(output) if output else None, reason)


# ---------------------------------------------------------------------------
# Concurrency lock
# ---------------------------------------------------------------------------

def acquire_lock() -> bool:
    """Returns True if lock acquired, False if another publish is running."""
    if LOCK_PATH.exists():
        age = time.time() - LOCK_PATH.stat().st_mtime
        if age < LOCK_MAX_AGE:
            print(f"INFO: lock held for {int(age)}s — another publish running",
                  file=sys.stderr)
            return False
        # Stale lock
        print(f"INFO: stale lock ({int(age)}s) — removing", file=sys.stderr)
        LOCK_PATH.unlink(missing_ok=True)
    try:
        LOCK_PATH.write_text(str(os.getpid()), encoding="utf-8")
        return True
    except OSError as exc:
        print(f"WARN: could not write lock: {exc}", file=sys.stderr)
        return False


def release_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Env loader
# ---------------------------------------------------------------------------

def load_env() -> Dict[str, str]:
    """Read NOTION_API_KEY + NOTION_PALMEIRAS_DB_ID from vault/.env."""
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
# Title normalization for dual-key dedup
# ---------------------------------------------------------------------------

def normalize_titulo(t: str) -> str:
    t = t.lower().strip()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-z0-9 ]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def is_duplicate(post: Dict[str, Any], state: Dict[str, Any]) -> Optional[str]:
    """Re-check dedup IMMEDIATELY before POST. Returns reason or None."""
    url = post.get("url_fonte_primaria", "")
    titulo_norm = normalize_titulo(post.get("titulo", ""))
    posted = state.get("posts_criados", [])
    for p in posted:
        if p.get("url_fonte") == url and url:
            return f"duplicate URL: {url}"
        if normalize_titulo(p.get("titulo", "")) == titulo_norm and titulo_norm:
            return f"duplicate titulo: '{post.get('titulo', '')[:60]}'"
    return None


# ---------------------------------------------------------------------------
# Notion image upload (delegates to existing helper)
# ---------------------------------------------------------------------------

def upload_image_to_notion(image_url: str) -> Optional[str]:
    """Returns file_upload_id, or None on failure (caller falls back to external)."""
    helper = SCRIPTS_DIR / "notion_upload.py"
    if not helper.is_file():
        print(f"WARN: notion_upload.py missing at {helper}", file=sys.stderr)
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
        print(f"WARN: notion_upload status={data.get('status')} "
              f"err={data.get('error', '?')}", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"WARN: notion_upload exception: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# State updates
# ---------------------------------------------------------------------------

def update_feed_state(state: Dict[str, Any], post: Dict[str, Any],
                       page_id: str, page_url: str) -> None:
    """Append entry; cap at last 200; write back atomically."""
    brt = datetime.timezone(datetime.timedelta(hours=-3))
    entry = {
        "titulo": post.get("titulo", ""),
        "url_fonte": post.get("url_fonte_primaria", ""),
        "imagem_url": (post.get("imagem") or {}).get("url", ""),
        "notion_id": page_id,
        "notion_url": page_url,
        "criado_em": datetime.datetime.now(brt).isoformat(),
    }
    state.setdefault("posts_criados", []).append(entry)
    state["posts_criados"] = state["posts_criados"][-200:]
    tmp = FEED_STATE_PATH.with_suffix(FEED_STATE_PATH.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(FEED_STATE_PATH)


def normalize_url(u: str) -> str:
    """Canonical form for hashing into a topic_key (drop scheme, query, fragment,
    trailing slash, lowercase host)."""
    if not u:
        return ""
    try:
        p = urllib.parse.urlsplit(u.strip())
        host = (p.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = (p.path or "").rstrip("/")
        return f"{host}{path}"
    except Exception:
        return u.strip()


def make_news_topic_key(post: Dict[str, Any]) -> str:
    """topic_key = 'news:<sha256[:16] of normalized primary URL>'."""
    url = post.get("url_fonte_primaria", "") or ""
    norm = normalize_url(url)
    digest = hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]
    return f"news:{digest}"


def record_in_published_index(post: Dict[str, Any], page_id: str, page_url: str) -> Optional[str]:
    """Append the published entry to the unified parmeirense JSONL store.

    Returns the generated ``post_id`` (the harness propagates it into
    ``_sink_telegram`` so the telegram message_id can be backfilled after
    delivery — closes the reply-feedback loop). Returns ``None`` on any
    failure; the publish itself is NOT failed (the Notion POST already
    succeeded and feed-state.json was updated).
    """
    try:
        from published_index import PublishedIndex  # type: ignore
    except ImportError as exc:
        print(f"WARN: published_index import failed: {exc}", file=sys.stderr)
        return None
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
            "topic_type": "news",
            "tone": post.get("tom") or post.get("tone"),
        }
        pid = idx.add(
            pipeline="palmeiras-feed-v2",
            topic_key=make_news_topic_key(post),
            title=post.get("titulo") or "",
            source_urls=source_urls or None,
            notion={"page_id": page_id, "url": page_url} if page_id else None,
            cover_image=cover,
            features={k: v for k, v in features.items() if v is not None},
        )
        return pid
    except Exception as exc:
        print(f"WARN: published-index write failed (non-fatal): {exc}",
              file=sys.stderr)
        return None


def update_posts_history(post: Dict[str, Any]) -> None:
    """Append today's post to posts-history.md; prune entries > 30 days old."""
    brt = datetime.timezone(datetime.timedelta(hours=-3))
    now = datetime.datetime.now(brt)
    today = now.strftime("%Y-%m-%d")
    cutoff = (now - datetime.timedelta(days=30)).strftime("%Y-%m-%d")

    try:
        content = POSTS_HISTORY_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""

    # Prune sections older than cutoff
    lines = content.split("\n")
    pruned: List[str] = []
    keep_section = True
    for ln in lines:
        if ln.startswith("## 20"):
            sect_date = ln.replace("## ", "").strip()
            keep_section = sect_date >= cutoff
        if keep_section:
            pruned.append(ln)
    content = "\n".join(pruned).rstrip()

    titulo = post.get("titulo", "(sem título)")
    intro = (post.get("introducao") or "")[:150] or titulo
    entry = f"- **{titulo}** — {intro}"
    if f"## {today}" not in content:
        content = (content + "\n\n" if content else "") + f"## {today}\n\n"
    else:
        content = content + "\n"
    content = content + entry + "\n"
    POSTS_HISTORY_PATH.write_text(content, encoding="utf-8")


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

    # Prefer post-reviewed.json (image-review step output) over post-final.json
    post_path = data_dir / "post-reviewed.json"
    if not post_path.exists():
        post_path = data_dir / "post-final.json"
    if not post_path.exists():
        fail(f"post-reviewed.json / post-final.json not found in {data_dir}", output)
    raw = post_path.read_text(encoding="utf-8").strip()

    if raw == "NO_POST" or raw == "NO_REPLY" or not raw:
        output.write_text("🐷 Palmeiras Feed — sem novos assuntos para cobrir.",
                          encoding="utf-8")
        emit_status("skipped", str(output), reason="upstream NO_POST")

    try:
        post = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"{post_path.name} invalid JSON: {exc}", output)

    # Acquire lock
    if not acquire_lock():
        output.write_text("🐷 Palmeiras Feed — pulando (publish concorrente em curso).",
                          encoding="utf-8")
        emit_status("skipped", str(output), reason="concurrent_lock")

    try:
        env = load_env()
        notion_token = env.get("NOTION_API_KEY", "")
        db_id = env.get("NOTION_PALMEIRAS_DB_ID", "")
        if not notion_token or not db_id:
            fail("NOTION_API_KEY or NOTION_PALMEIRAS_DB_ID missing in vault/.env", output)

        # Step 1 — upload image
        img = post.get("imagem", {}) or {}
        img_url = img.get("url", "")
        if img_url and not dry_run:
            file_upload_id = upload_image_to_notion(img_url)
            if file_upload_id:
                post["imagem"]["file_upload_id"] = file_upload_id
                # Persist back so notion_builder picks it up
                post_path.write_text(json.dumps(post, ensure_ascii=False, indent=2),
                                      encoding="utf-8")
                print(f"INFO: image uploaded — file_upload_id={file_upload_id}")

        # Step 2 — build Notion page body
        sys.path.insert(0, str(SCRIPTS_DIR.parent))  # for notion_builder import
        try:
            from notion_builder import post_to_notion_body  # type: ignore
        except ImportError as exc:
            fail(f"notion_builder import failed: {exc}", output)

        page_body = post_to_notion_body(post, db_id)

        # Step 3 — re-check dedup BEFORE POST (race-condition guard)
        try:
            state = json.loads(FEED_STATE_PATH.read_text(encoding="utf-8")) \
                    if FEED_STATE_PATH.is_file() else {"posts_criados": []}
        except (OSError, json.JSONDecodeError):
            state = {"posts_criados": []}

        dup = is_duplicate(post, state)
        if dup:
            print(f"INFO: SKIP — {dup}")
            output.write_text("🐷 Palmeiras Feed — sem novos assuntos para cobrir.",
                              encoding="utf-8")
            emit_status("skipped", str(output), reason=dup)

        if dry_run:
            print("INFO: DRY-RUN — not POSTing to Notion")
            output.write_text(
                "🐷 Palmeiras Feed — DRY-RUN (não publicado)\n\n"
                f"• {post.get('titulo', '')}",
                encoding="utf-8",
            )
            emit_status("ready", str(output), reason="dry-run completed (no Notion POST)")

        # Step 4 — POST to Notion
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

        # Step 5 — IMMEDIATELY update state (idempotency)
        update_feed_state(state, post, page_id, page_url)

        # Step 6 — record in the unified published-index.jsonl. The legacy
        # posts-history.md write was removed (the file remains on disk as a
        # backup but is no longer updated — see published_index.py).
        pid = record_in_published_index(post, page_id, page_url)

        # Step 7 — write Telegram-format output
        telegram_msg = (
            f"🐷 Palmeiras Feed\n\n"
            f"• [{post.get('titulo', '')}]({page_url})"
        )
        output.write_text(telegram_msg, encoding="utf-8")
        emit_status("ready", str(output),
                    reason=f"published to Notion: {page_url}",
                    post_id=pid)

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
