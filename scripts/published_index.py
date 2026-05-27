#!/usr/bin/env python3
"""Unified published-index store for vault pipelines.

Append-only JSONL store at:
    vault/<agent_id>/.workspace/published-index.jsonl

One JSON object per line. Replaces the per-pipeline markdown rolling
history files (posts-history.md, pos-jogo-history.md, ...) with a single
typed log that supports dedup, cross-pipeline awareness, and future
learning.

Entry schema (all fields optional except post_id / agent_id / pipeline /
published_at):

    {
      "post_id": "abc123...",          # uuid4 hex if not provided
      "agent_id": "parmeirense",
      "pipeline": "palmeiras-feed-v2",
      "published_at": "2026-05-26T21:05:00-03:00",
      "topic_key": "news:a1b2c3d4...", # for dedup queries
      "title": "Post title",
      "source_urls": ["https://..."],
      "telegram": {
        "chat_id": -100...,
        "thread_id": 17,
        "message_id": 12345
      },
      "notion": {"page_id": "..."},
      "cover_image": "path-or-url",
      "features": {...}                # free-form learning signals
    }

CLI:
    add    --agent ... --pipeline ... [...]         -> prints post_id
    has    --agent ... --topic-key ... [--within-days N]
                                                     -> exit 0 if exists, 1 if not
    query  --agent ... [--pipeline ...] [--since ISO] [--topic-key ...]
                                                     -> JSONL on stdout
    get    --agent ... --post-id ...                 -> single JSON object
    update-telegram-message-id --agent ... --post-id ... --message-id ...

Python API:
    from scripts.published_index import PublishedIndex
    idx = PublishedIndex(agent_id="parmeirense")
    pid = idx.add(pipeline=..., topic_key=..., title=..., ...)
    exists = idx.has(topic_key="news:...", within_days=30)
    rows = list(idx.query(pipeline="palmeiras-feed-v2", since="2026-05-01"))
    row = idx.get(post_id="abc...")
    idx.update_telegram_message_id(post_id, 12345)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fcntl
import json
import os
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

# ---------------------------------------------------------------------------
# Locating the vault root
# ---------------------------------------------------------------------------

# Allow override (mostly for tests) via env var. Otherwise resolve from this
# file's location: <repo>/scripts/published_index.py -> <repo>/vault/.
_DEFAULT_VAULT_ROOT = Path(__file__).resolve().parent.parent / "vault"


def _vault_root() -> Path:
    override = os.environ.get("CLAUDE_BOT_VAULT_ROOT")
    if override:
        return Path(override)
    return _DEFAULT_VAULT_ROOT


def _now_brt_iso() -> str:
    brt = _dt.timezone(_dt.timedelta(hours=-3))
    return _dt.datetime.now(brt).isoformat(timespec="seconds")


def _parse_iso(value: str) -> Optional[_dt.datetime]:
    """Best-effort ISO-8601 parser. Returns None on failure."""
    if not value:
        return None
    txt = value.strip()
    # Allow "Z" suffix (UTC).
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        return _dt.datetime.fromisoformat(txt)
    except ValueError:
        # Try date-only.
        try:
            return _dt.datetime.fromisoformat(txt + "T00:00:00")
        except ValueError:
            return None


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class PublishedIndex:
    """JSONL-backed append-only index of published items, per agent.

    Concurrency: ``fcntl.flock`` (exclusive) guards every write; readers
    snapshot the file under a shared lock. The file is treated as missing-
    == empty for all reads.
    """

    def __init__(self, agent_id: str, vault_root: Optional[Path] = None) -> None:
        if not agent_id:
            raise ValueError("agent_id is required")
        self.agent_id = agent_id
        self.vault_root = Path(vault_root) if vault_root else _vault_root()
        self.workspace_dir = self.vault_root / agent_id / ".workspace"
        self.path = self.workspace_dir / "published-index.jsonl"

    # -- low-level IO ------------------------------------------------------

    def _ensure_dir(self) -> None:
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _exclusive(self) -> Iterator[Any]:
        """Open the index for append with an exclusive flock.

        Creates the file on first use. Yields the opened file object.
        """
        self._ensure_dir()
        # 'a+' so the file is created if missing and the descriptor can
        # be locked even before the first write.
        fh = open(self.path, "a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            yield fh
        finally:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()

    @contextmanager
    def _shared(self) -> Iterator[Optional[Any]]:
        """Open the index for read with a shared flock.

        Yields ``None`` if the file does not exist yet.
        """
        if not self.path.exists():
            yield None
            return
        fh = open(self.path, "r", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH)
            yield fh
        finally:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            finally:
                fh.close()

    def _iter_all(self) -> Iterator[Dict[str, Any]]:
        with self._shared() as fh:
            if fh is None:
                return
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    # Skip corrupted line rather than blow up; recoverable
                    # by hand-editing the JSONL if it ever happens.
                    continue

    # -- public API --------------------------------------------------------

    def add(
        self,
        *,
        pipeline: str,
        topic_key: Optional[str] = None,
        title: Optional[str] = None,
        source_urls: Optional[Iterable[str]] = None,
        telegram: Optional[Dict[str, Any]] = None,
        notion: Optional[Dict[str, Any]] = None,
        cover_image: Optional[str] = None,
        features: Optional[Dict[str, Any]] = None,
        post_id: Optional[str] = None,
        published_at: Optional[str] = None,
    ) -> str:
        """Append an entry. Returns the (possibly generated) ``post_id``."""
        if not pipeline:
            raise ValueError("pipeline is required")
        pid = post_id or uuid.uuid4().hex
        entry: Dict[str, Any] = {
            "post_id": pid,
            "agent_id": self.agent_id,
            "pipeline": pipeline,
            "published_at": published_at or _now_brt_iso(),
        }
        if topic_key:
            entry["topic_key"] = topic_key
        if title:
            entry["title"] = title
        if source_urls is not None:
            entry["source_urls"] = list(source_urls)
        if telegram:
            entry["telegram"] = dict(telegram)
        if notion:
            entry["notion"] = dict(notion)
        if cover_image:
            entry["cover_image"] = cover_image
        if features is not None:
            entry["features"] = dict(features)

        line = json.dumps(entry, ensure_ascii=False) + "\n"
        with self._exclusive() as fh:
            fh.seek(0, os.SEEK_END)
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        return pid

    def has(self, *, topic_key: str, within_days: Optional[int] = None) -> bool:
        """Return True iff an entry for ``topic_key`` exists (optionally
        within the last ``within_days`` days based on ``published_at``)."""
        if not topic_key:
            return False
        cutoff: Optional[_dt.datetime] = None
        if within_days is not None:
            cutoff = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=-3))) - _dt.timedelta(days=within_days)
        for row in self._iter_all():
            if row.get("topic_key") != topic_key:
                continue
            if cutoff is None:
                return True
            ts = _parse_iso(row.get("published_at", ""))
            if ts is None:
                # Conservative: treat unknown timestamp as recent enough.
                return True
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=_dt.timezone.utc)
            if ts >= cutoff:
                return True
        return False

    def query(
        self,
        *,
        pipeline: Optional[str] = None,
        since: Optional[str] = None,
        topic_key: Optional[str] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield entries matching the filters (in file order)."""
        since_dt = _parse_iso(since) if since else None
        if since_dt is not None and since_dt.tzinfo is None:
            since_dt = since_dt.replace(tzinfo=_dt.timezone.utc)
        for row in self._iter_all():
            if pipeline and row.get("pipeline") != pipeline:
                continue
            if topic_key and row.get("topic_key") != topic_key:
                continue
            if since_dt is not None:
                ts = _parse_iso(row.get("published_at", ""))
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_dt.timezone.utc)
                if ts < since_dt:
                    continue
            yield row

    def get(self, *, post_id: str) -> Optional[Dict[str, Any]]:
        if not post_id:
            return None
        for row in self._iter_all():
            if row.get("post_id") == post_id:
                return row
        return None

    def update_telegram_message_id(self, post_id: str, message_id: int) -> bool:
        """Rewrite the entry's ``telegram.message_id`` in place.

        Uses write-to-temp + atomic rename under an exclusive lock so a
        crash in the middle cannot leave a half-written file. Returns
        True if the post was found and rewritten, False otherwise.
        """
        if not post_id:
            return False
        with self._exclusive() as fh:
            fh.seek(0)
            lines = fh.readlines()

            changed = False
            new_lines: List[str] = []
            for raw in lines:
                stripped = raw.strip()
                if not stripped:
                    new_lines.append(raw)
                    continue
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError:
                    new_lines.append(raw)
                    continue
                if row.get("post_id") == post_id:
                    tg = dict(row.get("telegram") or {})
                    tg["message_id"] = int(message_id)
                    row["telegram"] = tg
                    new_lines.append(json.dumps(row, ensure_ascii=False) + "\n")
                    changed = True
                else:
                    new_lines.append(raw if raw.endswith("\n") else raw + "\n")

            if not changed:
                return False

            tmp = tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                dir=str(self.workspace_dir),
                prefix=".published-index.",
                suffix=".tmp",
                delete=False,
            )
            try:
                tmp.writelines(new_lines)
                tmp.flush()
                os.fsync(tmp.fileno())
                tmp.close()
                os.replace(tmp.name, self.path)
            except Exception:
                try:
                    os.unlink(tmp.name)
                except OSError:
                    pass
                raise
            return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_add(args: argparse.Namespace) -> int:
    idx = PublishedIndex(agent_id=args.agent)
    features: Optional[Dict[str, Any]] = None
    if args.features:
        try:
            features = json.loads(args.features)
            if not isinstance(features, dict):
                print("ERROR: --features must be a JSON object", file=sys.stderr)
                return 2
        except json.JSONDecodeError as exc:
            print(f"ERROR: --features invalid JSON: {exc}", file=sys.stderr)
            return 2

    telegram: Dict[str, Any] = {}
    if args.telegram_chat_id is not None:
        telegram["chat_id"] = args.telegram_chat_id
    if args.telegram_thread_id is not None:
        telegram["thread_id"] = args.telegram_thread_id
    if args.telegram_message_id is not None:
        telegram["message_id"] = args.telegram_message_id

    notion: Dict[str, Any] = {}
    if args.notion_page_id:
        notion["page_id"] = args.notion_page_id

    pid = idx.add(
        pipeline=args.pipeline,
        topic_key=args.topic_key,
        title=args.title,
        source_urls=args.source_url or None,
        telegram=telegram or None,
        notion=notion or None,
        cover_image=args.cover_image,
        features=features,
        post_id=args.post_id,
    )
    print(pid)
    return 0


def _cli_has(args: argparse.Namespace) -> int:
    idx = PublishedIndex(agent_id=args.agent)
    exists = idx.has(topic_key=args.topic_key, within_days=args.within_days)
    return 0 if exists else 1


def _cli_query(args: argparse.Namespace) -> int:
    idx = PublishedIndex(agent_id=args.agent)
    for row in idx.query(pipeline=args.pipeline, since=args.since, topic_key=args.topic_key):
        print(json.dumps(row, ensure_ascii=False))
    return 0


def _cli_get(args: argparse.Namespace) -> int:
    idx = PublishedIndex(agent_id=args.agent)
    row = idx.get(post_id=args.post_id)
    if row is None:
        print("ERROR: post_id not found", file=sys.stderr)
        return 1
    print(json.dumps(row, ensure_ascii=False))
    return 0


def _cli_update_tg(args: argparse.Namespace) -> int:
    idx = PublishedIndex(agent_id=args.agent)
    ok = idx.update_telegram_message_id(args.post_id, args.message_id)
    if not ok:
        print("ERROR: post_id not found", file=sys.stderr)
        return 1
    print("ok")
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Unified published-index for vault pipelines.")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="Append a new entry; prints post_id")
    p_add.add_argument("--agent", required=True)
    p_add.add_argument("--pipeline", required=True)
    p_add.add_argument("--topic-key")
    p_add.add_argument("--title")
    p_add.add_argument("--source-url", action="append")
    p_add.add_argument("--telegram-message-id", type=int)
    p_add.add_argument("--telegram-chat-id", type=int)
    p_add.add_argument("--telegram-thread-id", type=int)
    p_add.add_argument("--notion-page-id")
    p_add.add_argument("--cover-image")
    p_add.add_argument("--features", help="JSON object string")
    p_add.add_argument("--post-id")
    p_add.set_defaults(func=_cli_add)

    p_has = sub.add_parser("has", help="Exit 0 if topic-key present, 1 otherwise")
    p_has.add_argument("--agent", required=True)
    p_has.add_argument("--topic-key", required=True)
    p_has.add_argument("--within-days", type=int)
    p_has.set_defaults(func=_cli_has)

    p_q = sub.add_parser("query", help="Stream matching entries as JSONL")
    p_q.add_argument("--agent", required=True)
    p_q.add_argument("--pipeline")
    p_q.add_argument("--since", help="ISO date or datetime")
    p_q.add_argument("--topic-key")
    p_q.set_defaults(func=_cli_query)

    p_g = sub.add_parser("get", help="Print a single entry by post_id")
    p_g.add_argument("--agent", required=True)
    p_g.add_argument("--post-id", required=True)
    p_g.set_defaults(func=_cli_get)

    p_u = sub.add_parser(
        "update-telegram-message-id",
        help="Rewrite an entry's telegram.message_id (safe-rewrite)",
    )
    p_u.add_argument("--agent", required=True)
    p_u.add_argument("--post-id", required=True)
    p_u.add_argument("--message-id", type=int, required=True)
    p_u.set_defaults(func=_cli_update_tg)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
