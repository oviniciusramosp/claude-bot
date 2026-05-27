#!/usr/bin/env python3
"""Palmeiras Video v2 — Step: scout

Pipeline: palmeiras-video-v2.md
Step-id: scout

Job:
  1. Fetch the official Palmeiras YouTube channel feed via
     scripts/youtube_rss.py (RSS first, PinchTab fallback).
  2. Apply the live-broadcast filter:
       - regular videos: keep ALL
       - lives (is_live_hint=true): keep ONLY when the title (case+accent
         insensitive) matches one of the kept keywords.
  3. Dedup against the unified published_index: drop any candidate whose
     topic_key 'yt:<video_id>' already exists for parmeirense.
  4. Pick the most recent survivor by published_at (single selection
     per tick — this is an event-driven 30-min poll).
  5. Write $PIPELINE_DATA_DIR/selected.json + emit a status line.

Output JSON shape:
    {
      "selected": {
        "video_id":      "...",
        "title":         "...",
        "link":          "https://www.youtube.com/watch?v=...",
        "thumbnail_url": "https://i.ytimg.com/vi/.../hqdefault.jpg",
        "description":   "...",
        "published_at":  "ISO-8601 string"
      },
      "reason": "...",
      "stats": {...}
    }

When nothing survives:
    {"selected": null, "reason": "no new videos", "stats": {...}}
and the downstream cascade skips (writer/cover/publish all gated by
`selected != null` in the pipeline definition).
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional

CHANNEL_ID = "UCBKc-rPDivvwFiWdG-81wxw"
REPO_ROOT = Path("/Users/viniciusramos/claude-bot")
YOUTUBE_RSS_SCRIPT = REPO_ROOT / "scripts" / "youtube_rss.py"
PUBLISHED_INDEX_SCRIPT = REPO_ROOT / "scripts" / "published_index.py"
AGENT_ID = "parmeirense"

# Lives we still want to publish (coletiva, anúncio, apresentação, homenagem).
LIVE_KEEP_RE = re.compile(
    r"(coletiva|anuncio|apresentacao|homenagem)",
    re.IGNORECASE,
)


def _strip_accents(text: str) -> str:
    return (
        unicodedata.normalize("NFD", text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def emit_status(status: str, output_file: Optional[str], reason: str = "") -> None:
    print(json.dumps({"status": status, "output_file": output_file, "reason": reason}))
    sys.exit(0 if status in ("ready", "skipped") else 1)


def fail(reason: str) -> None:
    print(f"ERROR: {reason}", file=sys.stderr)
    emit_status("failed", None, reason)


def fetch_videos() -> List[Dict[str, Any]]:
    """Invoke youtube_rss.py fetch and return parsed entries."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(YOUTUBE_RSS_SCRIPT),
                "fetch",
                "--channel-id",
                CHANNEL_ID,
                "--fallback-pinchtab",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except subprocess.TimeoutExpired:
        fail("youtube_rss.py timed out after 90s")
        return []
    except FileNotFoundError as exc:
        fail(f"youtube_rss.py not found: {exc}")
        return []

    if result.returncode != 0:
        fail(
            f"youtube_rss.py exited {result.returncode}: "
            f"{(result.stderr or '').strip()[:300]}"
        )
        return []

    entries: List[Dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def keep_video(entry: Dict[str, Any]) -> bool:
    """Apply the live-broadcast filter.

    Regular videos: always keep.
    Lives: keep only if title (normalized) matches LIVE_KEEP_RE.
    """
    if not entry.get("is_live_hint"):
        return True
    norm = _strip_accents(entry.get("title", ""))
    return bool(LIVE_KEEP_RE.search(norm))


def already_published(video_id: str) -> bool:
    """Query published_index for 'yt:<video_id>'. Exit 0 = exists."""
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(PUBLISHED_INDEX_SCRIPT),
                "has",
                "--agent",
                AGENT_ID,
                "--topic-key",
                f"yt:{video_id}",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        # Conservative: on dedup failure, assume NOT published so we don't
        # eternally suppress everything. The publish step re-checks.
        return False
    return result.returncode == 0


def _parse_published_at(value: str) -> _dt.datetime:
    """Best-effort ISO-8601 parse; falls back to epoch on failure."""
    if not value:
        return _dt.datetime.fromtimestamp(0, tz=_dt.timezone.utc)
    txt = value.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        ts = _dt.datetime.fromisoformat(txt)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=_dt.timezone.utc)
        return ts
    except ValueError:
        return _dt.datetime.fromtimestamp(0, tz=_dt.timezone.utc)


def write_output(data_dir: Path, payload: Dict[str, Any]) -> Path:
    out_path = data_dir / "selected.json"
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out_path


def main() -> int:
    data_dir_str = os.environ.get("PIPELINE_DATA_DIR", "")
    output_str = os.environ.get("PIPELINE_STEP_OUTPUT_FILE", "")
    if not data_dir_str:
        fail("PIPELINE_DATA_DIR env var is required")
        return 1
    data_dir = Path(data_dir_str)
    data_dir.mkdir(parents=True, exist_ok=True)

    entries = fetch_videos()
    n_total = len(entries)

    # Apply live-filter.
    filtered = [e for e in entries if keep_video(e)]
    n_after_live = len(filtered)

    # Dedup.
    deduped: List[Dict[str, Any]] = []
    n_dedup_skipped = 0
    for entry in filtered:
        vid = entry.get("video_id") or ""
        if not vid:
            continue
        if already_published(vid):
            n_dedup_skipped += 1
            continue
        deduped.append(entry)
    n_after_dedup = len(deduped)

    stats = {
        "fetched": n_total,
        "after_live_filter": n_after_live,
        "after_dedup": n_after_dedup,
        "dedup_skipped": n_dedup_skipped,
    }

    if not deduped:
        payload = {"selected": None, "reason": "no new videos", "stats": stats}
        out_path = write_output(data_dir, payload)
        emit_status("ready", output_str or str(out_path), "no new videos")
        return 0

    # Most-recent first.
    deduped.sort(key=lambda e: _parse_published_at(e.get("published_at", "")), reverse=True)
    chosen = deduped[0]

    selected = {
        "video_id": chosen.get("video_id"),
        "title": chosen.get("title"),
        "link": chosen.get("link"),
        "thumbnail_url": chosen.get("thumbnail_url"),
        "description": chosen.get("description"),
        "published_at": chosen.get("published_at"),
    }
    reason = (
        f"selected {selected['video_id']} from {n_after_dedup} fresh candidate(s)"
        f" (fetched={n_total}, dedup_skipped={n_dedup_skipped})"
    )
    payload = {"selected": selected, "reason": reason, "stats": stats}
    out_path = write_output(data_dir, payload)
    emit_status("ready", output_str or str(out_path), reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
