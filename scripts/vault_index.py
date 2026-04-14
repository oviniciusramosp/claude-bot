#!/usr/bin/env python3
"""
vault_index.py — SQLite FTS5 full-text index over the per-agent vault.

This module is the single source of truth for vault search. It powers:
  - claude-fallback-bot.py (_active_memory_lookup v2, _session_start_recall,
    write-through from _snapshot_session_to_journal / record_manual_lesson /
    _consolidate_session / _run_agent_create_skill)
  - mcp-server/vault_mcp_server.py (vault_search_text, vault_timeline,
    vault_get_excerpt MCP tools + write-through on vault_append_journal and
    vault_create_note)
  - scripts/vault-index-update.py (daily rebuild routine)
  - scripts/journal-weekly-rollup.py (per-agent summary driver)

Design constraints (from the plan document):
  - Pure stdlib. `sqlite3` + FTS5 are in Python stdlib on every modern build.
    The bot core MUST stay pip-free.
  - Hard per-agent isolation. Every read/write helper takes ``agent`` as a
    required positional argument and builds the ``WHERE entries.agent = ?``
    clause internally — callers never write SQL. This forecloses the class
    of bug where a helper silently leaks cross-agent.
  - Fail-open. If the DB is missing or unreadable, callers see None/empty
    results and the bot behaves exactly like before. Never raise during a
    read for an end-user's journey.
  - Fail-loud on write errors. Write-through failures are logged at WARNING
    by the caller (per the "zero silent errors" rule) but never block the
    upstream journal write — the daily rebuild is the safety net.
  - Additive-only schema migrations. ``index_meta.schema_version`` drives
    future migrations via ``ALTER TABLE ADD COLUMN``. On migration failure
    the DB is renamed to ``vault-index.sqlite.broken-v{n}`` and a fresh
    rebuild is scheduled; the bot logs and keeps running.

See ``.claude/rules/vault-runtime-features.md`` for the contracts C1–C8
that this module enforces.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Import get_frontmatter_and_body from the shared parser. Support both
# "imported as scripts.vault_frontmatter" (when called from the bot via
# ``from scripts.vault_index import ...``) and "imported after sys.path
# manipulation" (when called from scripts/ or mcp-server/).
try:
    from scripts.vault_frontmatter import get_frontmatter_and_body  # type: ignore
except ImportError:
    HERE = Path(__file__).resolve().parent
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from vault_frontmatter import get_frontmatter_and_body  # type: ignore

logger = logging.getLogger("vault-index")

SCHEMA_VERSION = 1

# Default DB location. Callers usually pass an explicit path so tests and
# the MCP sidecar can point at a sandboxed file.
DEFAULT_DB_PATH = Path.home() / ".claude-bot" / "vault-index.sqlite"

# ---------------------------------------------------------------------------
# Kinds — what we index
# ---------------------------------------------------------------------------

KIND_JOURNAL = "journal"
KIND_JOURNAL_WEEKLY = "journal_weekly"
KIND_LESSON = "lesson"
KIND_NOTE = "note"
ALL_KINDS = (KIND_JOURNAL, KIND_JOURNAL_WEEKLY, KIND_LESSON, KIND_NOTE)

# Vault filenames/directories we skip when walking agent folders.
_SKIP_FILENAMES = frozenset({
    "agent-journal.md", "agent-lessons.md", "agent-notes.md",
})
_SKIP_DIRNAMES = frozenset({".activity", ".workspace"})

# Privacy marker — everything between these tags is stripped before being
# stored in FTS. Case-insensitive, DOTALL.
_PRIVATE_TAG_RE = re.compile(r"<private>.*?</private>", re.IGNORECASE | re.DOTALL)

# Journal section splitter. vault_append_journal writes sections as
#     ## HH:MM\n\n{text}\n\n---\n\n
# We also accept ## H:MM and the "Session Snapshot" headings used by
# _snapshot_session_to_journal. The resulting sections are indexed one row
# each so search can return fine-grained anchors, while lessons/notes are
# stored as one row per file.
_JOURNAL_SECTION_HEADING_RE = re.compile(
    r"^##\s+(?:\d{1,2}:\d{2}|Session Snapshot\b.*)$",
    re.MULTILINE,
)

# Weekly rollup filename: vault/<agent>/Journal/weekly/YYYY-Www.md
_WEEKLY_ROLLUP_RE = re.compile(r"(\d{4})-W(\d{2})\.md$")

# Journal daily filename: YYYY-MM-DD.md
_JOURNAL_DAILY_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class IndexStats:
    """Return value from rebuild() / rebuild_agent() / upsert_agent()."""
    agents: List[str]
    rows_inserted: int
    rows_deleted: int
    duration_ms: float


@dataclass
class EntryHit:
    """One row returned by search() / timeline()."""
    id: int
    agent: str
    kind: str
    rel_path: str
    section_path: Optional[str]
    date: Optional[str]
    title: Optional[str]
    snippet: str  # FTS5 snippet for search hits; short excerpt for timeline


@dataclass
class EntryDetail:
    """Full body returned by get_excerpt()."""
    id: int
    agent: str
    kind: str
    rel_path: str
    section_path: Optional[str]
    date: Optional[str]
    title: Optional[str]
    body: str


# ---------------------------------------------------------------------------
# Connection management + schema
# ---------------------------------------------------------------------------


_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent         TEXT NOT NULL,
    kind          TEXT NOT NULL,
    rel_path      TEXT NOT NULL,
    section_path  TEXT,
    date          TEXT,
    title         TEXT,
    tags          TEXT,
    body          TEXT NOT NULL,
    private       INTEGER NOT NULL DEFAULT 0,
    mtime         REAL NOT NULL,
    ingested_at   REAL NOT NULL,
    UNIQUE(agent, rel_path, section_path)
);

CREATE INDEX IF NOT EXISTS entries_agent_date ON entries(agent, date DESC);
CREATE INDEX IF NOT EXISTS entries_agent_kind ON entries(agent, kind);

CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    title, tags, body,
    content='entries',
    content_rowid='id',
    tokenize='porter unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, title, tags, body)
    VALUES (new.id, new.title, new.tags, new.body);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, tags, body)
    VALUES('delete', old.id, old.title, old.tags, old.body);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, title, tags, body)
    VALUES('delete', old.id, old.title, old.tags, old.body);
    INSERT INTO entries_fts(rowid, title, tags, body)
    VALUES (new.id, new.title, new.tags, new.body);
END;

CREATE TABLE IF NOT EXISTS index_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def _check_fts5_available() -> None:
    """Raise RuntimeError if the running sqlite3 build doesn't support FTS5.

    Fail-loud per the zero-silent-errors rule. Callers turn this into a
    WARNING log + fail-open None return, but the root cause must surface.
    """
    probe = sqlite3.connect(":memory:")
    try:
        try:
            probe.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
        except sqlite3.OperationalError as exc:
            raise RuntimeError(
                "sqlite3 FTS5 extension is not available in this Python build. "
                "vault_index requires FTS5. Reinstall Python from python.org or "
                "with a build that includes FTS5 support."
            ) from exc
    finally:
        probe.close()


def connect(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """Open (or create) the index DB with WAL mode and run migrations.

    On migration failure the broken file is renamed to
    ``<db>.broken-v{schema_version}`` and a fresh DB is created in its place.
    The caller sees a working connection either way — the next daily
    rebuild repopulates.
    """
    if db_path is None:
        db_path = DEFAULT_DB_PATH
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    _check_fts5_available()

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn, db_path)
    except Exception as exc:
        conn.close()
        # Rename the broken DB and retry once with a fresh file.
        broken = db_path.with_suffix(db_path.suffix + f".broken-v{SCHEMA_VERSION}")
        try:
            db_path.replace(broken)
            logger.warning(
                "vault-index: schema init failed (%s); renamed %s -> %s and rebuilding fresh",
                exc, db_path, broken,
            )
        except OSError:
            logger.error("vault-index: could not rename broken DB %s: %s", db_path, exc)
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        _ensure_schema(conn, db_path)
    return conn


def _ensure_schema(conn: sqlite3.Connection, db_path: Path) -> None:
    conn.executescript(_CREATE_TABLES_SQL)
    cur = conn.execute("SELECT value FROM index_meta WHERE key = 'schema_version'")
    row = cur.fetchone()
    stored = int(row["value"]) if row else None
    if stored is None:
        conn.execute(
            "INSERT INTO index_meta(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
        return
    if stored == SCHEMA_VERSION:
        return
    if stored > SCHEMA_VERSION:
        # Downgrade: refuse to touch a newer schema.
        raise RuntimeError(
            f"vault-index schema version {stored} is newer than supported {SCHEMA_VERSION}. "
            f"Upgrade claude-bot or delete {db_path} to start fresh."
        )
    # stored < SCHEMA_VERSION: future migrations go here, gated on stored.
    # Migrations MUST be additive (ALTER TABLE ADD COLUMN + CREATE INDEX).
    # No destructive changes. Example pattern for future:
    #
    #   if stored < 2:
    #       conn.execute("ALTER TABLE entries ADD COLUMN ...")
    #       conn.execute("UPDATE index_meta SET value='2' WHERE key='schema_version'")
    #       stored = 2
    conn.execute(
        "UPDATE index_meta SET value = ? WHERE key = 'schema_version'",
        (str(SCHEMA_VERSION),),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Privacy tag stripping
# ---------------------------------------------------------------------------


def strip_private(text: str) -> Tuple[str, bool]:
    """Return (cleaned_text, had_private). Case-insensitive, DOTALL.

    Used before indexing journal/lesson/note bodies. The raw markdown file
    is NEVER modified — only the in-memory copy that goes into the FTS
    column. A ``private=1`` flag is stored on the row so auto-recall can
    skip it too.
    """
    if not text:
        return "", False
    had = bool(_PRIVATE_TAG_RE.search(text))
    if not had:
        return text, False
    cleaned = _PRIVATE_TAG_RE.sub("", text)
    return cleaned, True


# ---------------------------------------------------------------------------
# Journal section parsing
# ---------------------------------------------------------------------------


def _parse_journal_sections(body: str) -> List[Tuple[str, str]]:
    """Split a journal file body into (section_heading, section_text) pairs.

    The format is established by ``vault_append_journal`` in the MCP server
    (``## HH:MM\\n\\n{text}\\n\\n---\\n\\n``) and by
    ``_snapshot_session_to_journal`` (``## Session Snapshot — YYYY-MM-DD HH:MM``).

    Returns an empty list for files with no recognizable sections — callers
    fall back to indexing the whole body as a single row with
    ``section_path=None``.
    """
    if not body or not body.strip():
        return []
    # Find every heading position
    positions: List[Tuple[int, str]] = []
    for m in _JOURNAL_SECTION_HEADING_RE.finditer(body):
        positions.append((m.start(), m.group(0).strip()))
    if not positions:
        return []
    # Slice between consecutive headings
    sections: List[Tuple[str, str]] = []
    for i, (start, heading) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(body)
        chunk = body[start:end]
        # Drop the heading line itself + the standalone '---' separator
        lines = chunk.splitlines()
        content_lines = []
        for j, line in enumerate(lines):
            if j == 0:
                # heading line itself
                continue
            if line.strip() == "---":
                continue
            content_lines.append(line)
        text = "\n".join(content_lines).strip()
        if text:
            sections.append((heading, text))
    return sections


# ---------------------------------------------------------------------------
# File walkers
# ---------------------------------------------------------------------------


def _iter_agent_files(
    vault_dir: Path, agent: str
) -> Iterable[Tuple[str, Path, str]]:
    """Yield (kind, absolute_path, rel_path) for every file we want to index
    under a single agent.

    rel_path is relative to vault_dir, POSIX-style.
    """
    agent_root = vault_dir / agent
    if not agent_root.is_dir():
        return
    # Journals: daily + weekly rollup
    journal_dir = agent_root / "Journal"
    if journal_dir.is_dir():
        for p in sorted(journal_dir.iterdir()):
            if not p.is_file() or p.name in _SKIP_FILENAMES:
                continue
            if _JOURNAL_DAILY_RE.match(p.name):
                yield KIND_JOURNAL, p, p.relative_to(vault_dir).as_posix()
        weekly_dir = journal_dir / "weekly"
        if weekly_dir.is_dir():
            for p in sorted(weekly_dir.iterdir()):
                if not p.is_file() or p.suffix != ".md":
                    continue
                yield KIND_JOURNAL_WEEKLY, p, p.relative_to(vault_dir).as_posix()
    # Lessons
    lessons_dir = agent_root / "Lessons"
    if lessons_dir.is_dir():
        for p in sorted(lessons_dir.iterdir()):
            if not p.is_file() or p.suffix != ".md" or p.name in _SKIP_FILENAMES:
                continue
            yield KIND_LESSON, p, p.relative_to(vault_dir).as_posix()
    # Notes
    notes_dir = agent_root / "Notes"
    if notes_dir.is_dir():
        for p in sorted(notes_dir.iterdir()):
            if not p.is_file() or p.suffix != ".md" or p.name in _SKIP_FILENAMES:
                continue
            yield KIND_NOTE, p, p.relative_to(vault_dir).as_posix()


def _iter_legacy_main_journal_files(vault_dir: Path) -> Iterable[Tuple[str, Path, str]]:
    """Legacy v3.0 journal files directly under ``vault/Journal/`` are
    indexed under agent="main", matching what guard-journal-write.sh does
    at the filesystem level. This lets old installs keep searching their
    pre-v3.1 history without manual migration.
    """
    legacy = vault_dir / "Journal"
    if not legacy.is_dir():
        return
    for p in sorted(legacy.iterdir()):
        if not p.is_file() or not _JOURNAL_DAILY_RE.match(p.name):
            continue
        yield KIND_JOURNAL, p, p.relative_to(vault_dir).as_posix()


# ---------------------------------------------------------------------------
# Row building
# ---------------------------------------------------------------------------


def _rows_for_file(
    vault_dir: Path, agent: str, kind: str, abs_path: Path, rel_path: str,
) -> List[Dict[str, Any]]:
    """Parse a single file into one or more rows ready for the entries table.

    Journals are split per-section; lessons/notes/weekly rollups are one row.
    Private-tagged text is stripped from the indexed body but the row is
    flagged ``private=1`` if any private block existed anywhere in the file.
    """
    try:
        fm, body = get_frontmatter_and_body(abs_path)
    except Exception as exc:
        logger.warning("vault-index: failed to read %s: %s", abs_path, exc)
        return []
    try:
        mtime = abs_path.stat().st_mtime
    except OSError as exc:
        logger.warning("vault-index: stat failed for %s: %s", abs_path, exc)
        return []

    title = str(fm.get("title") or abs_path.stem)
    tags_value = fm.get("tags") or []
    if not isinstance(tags_value, list):
        tags_value = [tags_value]
    tags_json = json.dumps([str(t) for t in tags_value], ensure_ascii=False)

    date_str: Optional[str] = None
    if kind == KIND_JOURNAL:
        m = _JOURNAL_DAILY_RE.match(abs_path.name)
        if m:
            date_str = m.group(1)
    elif kind == KIND_JOURNAL_WEEKLY:
        m = _WEEKLY_ROLLUP_RE.search(abs_path.name)
        if m:
            date_str = f"{m.group(1)}-W{m.group(2)}"
    else:
        date_str = str(fm.get("date") or "") or None

    cleaned_body, had_private = strip_private(body or "")

    rows: List[Dict[str, Any]] = []
    if kind == KIND_JOURNAL:
        sections = _parse_journal_sections(cleaned_body)
        if sections:
            for heading, text in sections:
                rows.append({
                    "agent": agent,
                    "kind": kind,
                    "rel_path": rel_path,
                    "section_path": heading,
                    "date": date_str,
                    "title": title,
                    "tags": tags_json,
                    "body": text,
                    "private": 1 if had_private else 0,
                    "mtime": mtime,
                    "ingested_at": time.time(),
                })
            return rows
        # Fall through: a journal file with no sections yet (just frontmatter)
        if not (cleaned_body or "").strip():
            return []
    rows.append({
        "agent": agent,
        "kind": kind,
        "rel_path": rel_path,
        "section_path": None,
        "date": date_str,
        "title": title,
        "tags": tags_json,
        "body": (cleaned_body or "").strip(),
        "private": 1 if had_private else 0,
        "mtime": mtime,
        "ingested_at": time.time(),
    })
    return rows


def _insert_rows(conn: sqlite3.Connection, rows: List[Dict[str, Any]]) -> int:
    """INSERT OR REPLACE a batch of rows, returning the count actually written.

    The UNIQUE(agent, rel_path, section_path) constraint means a second
    rebuild naturally upserts — no manual delete needed.
    """
    if not rows:
        return 0
    sql = """
        INSERT OR REPLACE INTO entries
            (agent, kind, rel_path, section_path, date, title, tags, body, private, mtime, ingested_at)
        VALUES
            (:agent, :kind, :rel_path, :section_path, :date, :title, :tags, :body, :private, :mtime, :ingested_at)
    """
    conn.executemany(sql, rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Agent discovery — contract C1
# ---------------------------------------------------------------------------


def discover_agents(vault_dir: Path) -> List[str]:
    """Return every agent id under ``vault_dir`` that has an
    ``agent-<id>.md`` hub file.

    This is the ONE place that enumerates agents in the index library.
    Mirrors ``iter_agent_ids()`` at claude-fallback-bot.py:254. We
    duplicate the minimal logic here instead of importing the bot module
    so ``scripts/vault-index-update.py`` can run without pulling in the
    full bot (and its side effects like touching ``~/.claude-bot/``).

    Callers in the bot process SHOULD pass ``agent_ids`` explicitly to
    ``rebuild()`` so the bot's canonical ``iter_agent_ids()`` is used;
    scripts that call ``rebuild(agent_ids=None)`` fall back to this
    stdlib discovery.
    """
    if not vault_dir.is_dir():
        return []
    reserved = frozenset({
        "README.md", "CLAUDE.md", "Tooling.md", ".env", ".gitkeep",
        ".graphs", ".obsidian", ".claude", "Images", "__pycache__",
    })
    ids: List[str] = []
    for entry in sorted(vault_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in reserved:
            continue
        hub = entry / f"agent-{entry.name}.md"
        if hub.is_file():
            ids.append(entry.name)
    return ids


# ---------------------------------------------------------------------------
# Write path — rebuild / upsert
# ---------------------------------------------------------------------------


def rebuild(
    vault_dir: Path,
    db_path: Optional[Path] = None,
    agent_ids: Optional[List[str]] = None,
) -> IndexStats:
    """Drop-and-repopulate the whole index from the vault filesystem.

    When ``agent_ids`` is None, uses ``discover_agents(vault_dir)`` — the
    stdlib equivalent of ``iter_agent_ids()``. Callers inside the bot
    process SHOULD pass the bot's own ``iter_agent_ids()`` result so the
    two stay in lockstep. This is contract C1 in the plan.

    Also indexes legacy ``vault/Journal/*.md`` under agent="main" (contract C4).
    """
    vault_dir = Path(vault_dir)
    if not vault_dir.is_dir():
        raise FileNotFoundError(f"vault_dir does not exist: {vault_dir}")
    t0 = time.monotonic()
    conn = connect(db_path)
    try:
        # Full drop — simplest and matches contract C4 (full rebuild is the
        # authority; deleted/renamed agents disappear naturally).
        deleted = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        conn.execute("DELETE FROM entries")
        conn.commit()

        if agent_ids is None:
            agent_ids = discover_agents(vault_dir)

        total_rows = 0
        for agent in agent_ids:
            agent = (agent or "").strip()
            if not agent:
                continue
            rows: List[Dict[str, Any]] = []
            for kind, abs_path, rel_path in _iter_agent_files(vault_dir, agent):
                rows.extend(_rows_for_file(vault_dir, agent, kind, abs_path, rel_path))
            total_rows += _insert_rows(conn, rows)

        # Legacy pre-v3.1 journal files
        legacy_rows: List[Dict[str, Any]] = []
        for kind, abs_path, rel_path in _iter_legacy_main_journal_files(vault_dir):
            legacy_rows.extend(_rows_for_file(vault_dir, "main", kind, abs_path, rel_path))
        total_rows += _insert_rows(conn, legacy_rows)

        conn.commit()
        dur = (time.monotonic() - t0) * 1000
        return IndexStats(
            agents=list(agent_ids),
            rows_inserted=total_rows,
            rows_deleted=deleted,
            duration_ms=dur,
        )
    finally:
        conn.close()


def rebuild_agent(conn: sqlite3.Connection, vault_dir: Path, agent: str) -> IndexStats:
    """Rebuild one agent's rows transactionally (DELETE WHERE agent=? + INSERT).

    Used when an agent is recreated or after heavy manual edits where a
    full rebuild would be overkill.
    """
    if not agent or not agent.strip():
        raise ValueError("rebuild_agent: agent is required (contract C2)")
    agent = agent.strip()
    vault_dir = Path(vault_dir)
    t0 = time.monotonic()
    cur = conn.execute("SELECT COUNT(*) FROM entries WHERE agent = ?", (agent,))
    deleted = cur.fetchone()[0]
    conn.execute("DELETE FROM entries WHERE agent = ?", (agent,))

    rows: List[Dict[str, Any]] = []
    for kind, abs_path, rel_path in _iter_agent_files(vault_dir, agent):
        rows.extend(_rows_for_file(vault_dir, agent, kind, abs_path, rel_path))
    inserted = _insert_rows(conn, rows)
    conn.commit()
    dur = (time.monotonic() - t0) * 1000
    return IndexStats(
        agents=[agent],
        rows_inserted=inserted,
        rows_deleted=deleted,
        duration_ms=dur,
    )


def upsert_agent(conn: sqlite3.Connection, vault_dir: Path, agent: str) -> IndexStats:
    """Index every file under ``vault/<agent>/`` that isn't yet in the DB
    or whose mtime is newer than the stored ``mtime``.

    Used by contract C6 immediately after new-agent creation so auto-recall
    works from turn 1, without waiting for the 04:05 daily rebuild.
    """
    if not agent or not agent.strip():
        raise ValueError("upsert_agent: agent is required (contract C2)")
    agent = agent.strip()
    vault_dir = Path(vault_dir)
    t0 = time.monotonic()

    # Map (rel_path, section_path) -> stored mtime, per agent
    stored: Dict[Tuple[str, Optional[str]], float] = {}
    cur = conn.execute(
        "SELECT rel_path, section_path, mtime FROM entries WHERE agent = ?",
        (agent,),
    )
    for row in cur.fetchall():
        stored[(row["rel_path"], row["section_path"])] = row["mtime"]

    rows: List[Dict[str, Any]] = []
    for kind, abs_path, rel_path in _iter_agent_files(vault_dir, agent):
        file_rows = _rows_for_file(vault_dir, agent, kind, abs_path, rel_path)
        for r in file_rows:
            key = (r["rel_path"], r["section_path"])
            if key in stored and stored[key] >= r["mtime"]:
                continue
            rows.append(r)
    inserted = _insert_rows(conn, rows)
    conn.commit()
    dur = (time.monotonic() - t0) * 1000
    return IndexStats(
        agents=[agent],
        rows_inserted=inserted,
        rows_deleted=0,
        duration_ms=dur,
    )


def upsert_file(
    conn: sqlite3.Connection,
    vault_dir: Path,
    agent: str,
    rel_path: str,
) -> int:
    """Re-index a single file (write-through from the MCP server and the
    bot's Python writers).

    Raises ``ValueError`` if ``agent`` is empty (contract C2).
    """
    if not agent or not agent.strip():
        raise ValueError("upsert_file: agent is required (contract C2)")
    if not rel_path or not rel_path.strip():
        raise ValueError("upsert_file: rel_path is required")
    agent = agent.strip()
    vault_dir = Path(vault_dir)
    abs_path = vault_dir / rel_path
    if not abs_path.is_file():
        # File vanished (race with deletion) — remove any stale rows.
        conn.execute(
            "DELETE FROM entries WHERE agent = ? AND rel_path = ?",
            (agent, rel_path),
        )
        conn.commit()
        return 0

    # Infer the kind from the path
    parts = rel_path.split("/")
    kind = KIND_NOTE
    if "Journal" in parts:
        kind = KIND_JOURNAL_WEEKLY if "weekly" in parts else KIND_JOURNAL
    elif "Lessons" in parts:
        kind = KIND_LESSON
    elif "Notes" in parts:
        kind = KIND_NOTE

    # Delete any existing rows for this file (handles section changes cleanly)
    conn.execute(
        "DELETE FROM entries WHERE agent = ? AND rel_path = ?",
        (agent, rel_path),
    )
    rows = _rows_for_file(vault_dir, agent, kind, abs_path, rel_path)
    inserted = _insert_rows(conn, rows)
    conn.commit()
    return inserted


def upsert_journal_section(
    conn: sqlite3.Connection,
    vault_dir: Path,
    agent: str,
    rel_path: str,
    timestamp: str,
    text: str,
) -> int:
    """Fast path for the journal append case — insert just the new section
    without reparsing the whole file.

    Used by ``vault_append_journal`` in the MCP server and by
    ``_snapshot_session_to_journal`` in the bot. Falls back silently to
    ``upsert_file`` if the caller passed malformed inputs — the daily
    rebuild is the safety net.
    """
    if not agent or not agent.strip():
        raise ValueError("upsert_journal_section: agent is required (contract C2)")
    if not rel_path:
        raise ValueError("upsert_journal_section: rel_path is required")
    agent = agent.strip()
    vault_dir = Path(vault_dir)

    cleaned, had_private = strip_private(text or "")
    cleaned = cleaned.strip()
    if not cleaned:
        return 0

    # Derive the date from the filename if possible
    fname = Path(rel_path).name
    m = _JOURNAL_DAILY_RE.match(fname)
    date_str = m.group(1) if m else None

    section_heading = f"## {timestamp}" if timestamp else None
    mtime = time.time()
    try:
        abs_path = vault_dir / rel_path
        if abs_path.is_file():
            mtime = abs_path.stat().st_mtime
    except OSError:
        pass

    row = {
        "agent": agent,
        "kind": KIND_JOURNAL,
        "rel_path": rel_path,
        "section_path": section_heading,
        "date": date_str,
        "title": f"Journal {date_str}" if date_str else Path(rel_path).stem,
        "tags": json.dumps(["journal"], ensure_ascii=False),
        "body": cleaned,
        "private": 1 if had_private else 0,
        "mtime": mtime,
        "ingested_at": time.time(),
    }
    inserted = _insert_rows(conn, [row])
    conn.commit()
    return inserted


# ---------------------------------------------------------------------------
# Read path — search / timeline / get
# ---------------------------------------------------------------------------


# Minimal stopword list — kept compact on purpose so the FTS query doesn't
# collapse to an empty string on short prompts. Mirrors the philosophy of
# the bot's _SKILL_HINT_STOPWORDS (we just don't import it to keep the
# module independent from the bot process).
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "from", "into", "about",
    "what", "when", "where", "which", "there", "here", "have", "has", "had",
    "was", "were", "will", "would", "could", "should", "does", "did", "been",
    "being", "some", "such", "than", "then", "them", "they", "their", "your",
    "you", "our", "his", "her", "its", "but", "not", "are", "is",
    # PT-BR helpers since the vault is bilingual
    "uma", "uns", "umas", "dos", "das", "por", "pra", "para", "pelo", "pela",
    "como", "que", "qual", "quais", "quem", "onde", "quando", "mas", "esse",
    "essa", "isso", "este", "esta", "isto", "aquele", "aquela", "aquilo",
    "sobre", "entre", "quer", "meu", "minha", "seu", "sua", "nosso", "nossa",
})

_WORD_RE = re.compile(r"[\w-]+", re.UNICODE)


def _build_fts_match(query: str) -> Optional[str]:
    """Turn a user prompt into an FTS5 MATCH expression.

    Strategy: extract words >=3 chars, drop stopwords, OR them together,
    quote each term so FTS5 treats them as literal strings (avoids having
    to escape reserved tokens like AND/OR/NEAR). Returns None if there are
    no usable tokens.
    """
    if not query:
        return None
    tokens = _WORD_RE.findall(query.lower())
    terms: List[str] = []
    seen = set()
    for tok in tokens:
        if len(tok) < 3:
            continue
        if tok in _STOPWORDS:
            continue
        if tok in seen:
            continue
        seen.add(tok)
        # Quote to dodge FTS5 operators. Double any embedded quotes.
        terms.append('"' + tok.replace('"', '""') + '"')
    if not terms:
        return None
    return " OR ".join(terms)


def search(
    conn: sqlite3.Connection,
    agent: str,
    query: str,
    *,
    kinds: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 20,
    include_private: bool = True,
) -> List[EntryHit]:
    """Full-text search scoped to one agent (contract C3).

    Returns a compact list of hits with FTS5 snippets — callers fetch
    full bodies via ``get_excerpt`` only for the ones that matter,
    mirroring claude-mem's progressive disclosure pattern.

    **Private tag semantics.** ``<private>…</private>`` blocks are
    stripped from the indexed body at rebuild time, so the private TEXT
    is never findable regardless of this flag. The ``private`` column
    records which rows had a private marker SOMEWHERE in the file. By
    default we still return those rows (their public content is fair
    game). Pass ``include_private=False`` to hide files that had any
    private marker at all — used by SessionStart auto-recall for an
    extra layer of caution.
    """
    if not agent or not agent.strip():
        raise ValueError("search: agent is required (contract C2)")
    agent = agent.strip()
    match_expr = _build_fts_match(query or "")
    if not match_expr:
        return []

    sql_parts = [
        "SELECT e.id, e.agent, e.kind, e.rel_path, e.section_path, e.date, e.title,",
        "       snippet(entries_fts, 2, '[', ']', '…', 12) AS snippet",
        "FROM entries_fts",
        "JOIN entries e ON e.id = entries_fts.rowid",
        "WHERE entries_fts MATCH ?",
        "  AND e.agent = ?",
    ]
    params: List[Any] = [match_expr, agent]
    if kinds:
        placeholders = ",".join("?" * len(kinds))
        sql_parts.append(f"  AND e.kind IN ({placeholders})")
        params.extend(kinds)
    if date_from:
        sql_parts.append("  AND (e.date IS NULL OR e.date >= ?)")
        params.append(date_from)
    if date_to:
        sql_parts.append("  AND (e.date IS NULL OR e.date <= ?)")
        params.append(date_to)
    if not include_private:
        sql_parts.append("  AND e.private = 0")
    sql_parts.append("ORDER BY bm25(entries_fts), e.date DESC")
    sql_parts.append("LIMIT ?")
    params.append(int(limit))
    sql = "\n".join(sql_parts)
    try:
        cur = conn.execute(sql, params)
    except sqlite3.OperationalError as exc:
        # Malformed FTS expression → treat as no-match, don't crash the bot.
        logger.warning("vault-index search: FTS error %s (match=%r)", exc, match_expr)
        return []
    return [
        EntryHit(
            id=row["id"],
            agent=row["agent"],
            kind=row["kind"],
            rel_path=row["rel_path"],
            section_path=row["section_path"],
            date=row["date"],
            title=row["title"],
            snippet=row["snippet"] or "",
        )
        for row in cur.fetchall()
    ]


def timeline(
    conn: sqlite3.Connection,
    agent: str,
    anchor_id: int,
    *,
    before: int = 3,
    after: int = 3,
    include_private: bool = True,
) -> List[EntryHit]:
    """Return the N entries immediately before and after ``anchor_id`` in
    the same agent, ordered by date ascending.

    "Before" and "after" are measured by (date DESC, id DESC) — the same
    ordering used for display. Useful for expanding context around a
    search hit.
    """
    if not agent or not agent.strip():
        raise ValueError("timeline: agent is required (contract C2)")
    agent = agent.strip()
    cur = conn.execute(
        "SELECT id, date FROM entries WHERE id = ? AND agent = ?",
        (anchor_id, agent),
    )
    anchor = cur.fetchone()
    if not anchor:
        return []
    anchor_date = anchor["date"] or ""

    def _fetch(direction: str, n: int) -> List[sqlite3.Row]:
        if direction == "before":
            sql = """
                SELECT id, agent, kind, rel_path, section_path, date, title, substr(body, 1, 200) AS snippet
                FROM entries
                WHERE agent = ?
                  AND (date < ? OR (date = ? AND id < ?))
                  {priv}
                ORDER BY date DESC, id DESC
                LIMIT ?
            """
        else:
            sql = """
                SELECT id, agent, kind, rel_path, section_path, date, title, substr(body, 1, 200) AS snippet
                FROM entries
                WHERE agent = ?
                  AND (date > ? OR (date = ? AND id > ?))
                  {priv}
                ORDER BY date ASC, id ASC
                LIMIT ?
            """
        priv_clause = "" if include_private else "AND private = 0"
        sql = sql.format(priv=priv_clause)
        return conn.execute(sql, (agent, anchor_date, anchor_date, anchor_id, n)).fetchall()

    before_rows = list(reversed(_fetch("before", before)))
    after_rows = _fetch("after", after)
    all_rows = before_rows + [anchor] + after_rows

    # Re-fetch anchor's full display row
    anchor_full = conn.execute(
        """SELECT id, agent, kind, rel_path, section_path, date, title, substr(body, 1, 200) AS snippet
           FROM entries WHERE id = ?""",
        (anchor_id,),
    ).fetchone()
    all_rows[before_rows and len(before_rows) or 0] = anchor_full

    results: List[EntryHit] = []
    for row in all_rows:
        if row is None:
            continue
        results.append(EntryHit(
            id=row["id"],
            agent=row["agent"] if "agent" in row.keys() else agent,
            kind=row["kind"] if "kind" in row.keys() else "",
            rel_path=row["rel_path"] if "rel_path" in row.keys() else "",
            section_path=row["section_path"] if "section_path" in row.keys() else None,
            date=row["date"] if "date" in row.keys() else None,
            title=row["title"] if "title" in row.keys() else None,
            snippet=row["snippet"] if "snippet" in row.keys() else "",
        ))
    return results


def get_excerpt(
    conn: sqlite3.Connection,
    agent: str,
    entry_id: int,
    *,
    max_chars: int = 800,
) -> Optional[EntryDetail]:
    """Return the full body (up to ``max_chars``) of a specific entry,
    scoped to one agent."""
    if not agent or not agent.strip():
        raise ValueError("get_excerpt: agent is required (contract C2)")
    agent = agent.strip()
    cur = conn.execute(
        """SELECT id, agent, kind, rel_path, section_path, date, title, body
           FROM entries
           WHERE id = ? AND agent = ?""",
        (entry_id, agent),
    )
    row = cur.fetchone()
    if not row:
        return None
    body = row["body"] or ""
    if len(body) > max_chars:
        body = body[:max_chars].rstrip() + "…"
    return EntryDetail(
        id=row["id"],
        agent=row["agent"],
        kind=row["kind"],
        rel_path=row["rel_path"],
        section_path=row["section_path"],
        date=row["date"],
        title=row["title"],
        body=body,
    )
