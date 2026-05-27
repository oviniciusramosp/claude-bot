#!/usr/bin/env python3
"""Palmeiras Video v2 — Step: build-message

Pipeline: palmeiras-video-v2.md
Step-id: build-message

Reads post-reviewed.json (writer + cover output), writes a Telegram-
ready markdown message to $PIPELINE_STEP_OUTPUT_FILE, and records the
publish in the unified parmeirense published_index BEFORE the harness's
telegram sink runs (so message_id can be backfilled later by a parallel
work-stream via `published_index.py update-telegram-message-id`).

The Telegram message embeds the YouTube link prominently — Telegram's
preview renderer will fetch the video thumbnail automatically from the
youtube.com URL.

Stdout: a single status JSON line, nothing else (telegram-safe stdout).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Make repo's scripts/ importable for PublishedIndex.
_REPO_SCRIPTS = Path("/Users/viniciusramos/claude-bot/scripts")
if str(_REPO_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_REPO_SCRIPTS))


def emit_status(status: str, output_file: Optional[str], reason: str = "",
                post_id: Optional[str] = None) -> None:
    payload: Dict[str, Any] = {"status": status, "output_file": output_file,
                               "reason": reason}
    if post_id:
        payload["post_id"] = post_id
    print(json.dumps(payload))
    sys.exit(0 if status in ("ready", "skipped") else 1)


def fail(reason: str, output: Optional[Path] = None) -> None:
    print(f"ERROR: {reason}", file=sys.stderr)
    if output is not None:
        try:
            output.write_text(
                "🐷 Palmeiras Vídeo — erro ao montar mensagem.",
                encoding="utf-8",
            )
        except OSError:
            pass
    emit_status("failed", str(output) if output else None, reason)


def _telegram_escape(text: str) -> str:
    """Minimal escape for the small subset of Markdown the bot sends.

    The bot uses the legacy "Markdown" mode in telegram_notify.py (not
    MarkdownV2). Only `_` and `*` mid-word are problematic; we let them
    through and trust the writer step to produce safe prose.
    """
    return text or ""


def build_telegram_text(post: Dict[str, Any]) -> str:
    """Render the post as a Telegram message.

    Layout:
        🐷 Palmeiras Vídeo

        *<titulo>*

        <introducao>

        <bloco1>

        <bloco2>

        <link>
    """
    titulo = (post.get("titulo") or "").strip()
    intro = (post.get("introducao") or "").strip()
    blocos = post.get("blocos") or []
    video = post.get("video") or {}
    link = (video.get("link") or "").strip()

    body_parts = []
    body_parts.append("🐷 Palmeiras Vídeo")
    if titulo:
        body_parts.append("")
        body_parts.append(f"*{_telegram_escape(titulo)}*")
    if intro:
        body_parts.append("")
        body_parts.append(_telegram_escape(intro))
    for bloco in blocos:
        if not isinstance(bloco, dict):
            continue
        tipo = bloco.get("tipo")
        if tipo == "paragrafo":
            conteudo = (bloco.get("conteudo") or "").strip()
            if conteudo:
                body_parts.append("")
                body_parts.append(_telegram_escape(conteudo))
    if link:
        body_parts.append("")
        body_parts.append(link)
    return "\n".join(body_parts).rstrip() + "\n"


def record_in_published_index(post: Dict[str, Any]) -> Optional[str]:
    """Append the entry to the unified published_index. Best-effort.

    Returns the generated post_id on success, None on failure (which is
    logged to stderr but not fatal — the Telegram publish proceeds).
    """
    try:
        from published_index import PublishedIndex  # type: ignore
    except ImportError as exc:
        print(f"WARN: published_index import failed: {exc}", file=sys.stderr)
        return None
    try:
        video = post.get("video") or {}
        vid = video.get("video_id") or ""
        if not vid:
            print("WARN: video.video_id missing; skipping index entry",
                  file=sys.stderr)
            return None
        topic_key = post.get("topic_key") or f"yt:{vid}"
        imagem = post.get("imagem") or {}
        cover = imagem.get("url") if imagem else None
        idx = PublishedIndex(agent_id="parmeirense")
        pid = idx.add(
            pipeline="palmeiras-video-v2",
            topic_key=topic_key,
            title=post.get("titulo") or video.get("title") or "",
            source_urls=[video["link"]] if video.get("link") else None,
            cover_image=cover,
            features={
                "topic_type": "video",
                "video_id": vid,
                "youtube_title": video.get("title"),
                "published_at": video.get("published_at"),
            },
        )
        return pid
    except Exception as exc:
        print(f"WARN: published_index write failed (non-fatal): {exc}",
              file=sys.stderr)
        return None


def main() -> int:
    output_str = os.environ.get("PIPELINE_STEP_OUTPUT_FILE", "")
    data_dir_str = os.environ.get("PIPELINE_DATA_DIR", "")
    if not output_str or not data_dir_str:
        fail("PIPELINE_STEP_OUTPUT_FILE / PIPELINE_DATA_DIR env not set")
        return 1
    output = Path(output_str)
    data_dir = Path(data_dir_str)
    output.parent.mkdir(parents=True, exist_ok=True)

    # Prefer post-reviewed.json (cover step output) over post.json.
    post_path = data_dir / "post-reviewed.json"
    if not post_path.exists():
        post_path = data_dir / "post.json"
    if not post_path.exists():
        fail(f"post-reviewed.json / post.json not found in {data_dir}", output)

    raw = post_path.read_text(encoding="utf-8").strip()
    if raw in ("NO_POST", "NO_REPLY") or not raw:
        output.write_text(
            "🐷 Palmeiras Vídeo — sem novidades no canal.",
            encoding="utf-8",
        )
        emit_status("skipped", str(output), reason="upstream NO_POST")
        return 0

    try:
        post = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"{post_path.name} invalid JSON: {exc}", output)
        return 1

    # Record in published_index BEFORE the telegram sink runs.
    pid = record_in_published_index(post)

    # Build the Telegram message.
    text = build_telegram_text(post)
    output.write_text(text, encoding="utf-8")

    video_id = (post.get("video") or {}).get("video_id") or "?"
    emit_status("ready", str(output),
                reason=f"telegram message built for video {video_id}",
                post_id=pid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
