"""Tests for _session_start_recall and the FTS write-through helpers.

Covers:
  - Recall fires only on fresh sessions (message_count == 0, session_id None)
  - Recall scopes hard to session.agent (contract C3 at the bot layer)
  - Fail-open when the index DB is missing
  - Write-through updates the FTS index synchronously from the bot process
  - Active Memory v2 prefers the FTS path when the index has matching rows
  - New-agent bootstrap indexes files without waiting for the daily rebuild
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from tests._botload import load_bot_module

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import vault_index  # noqa: E402


def _seed_agent(vault: Path, agent_id: str) -> Path:
    base = vault / agent_id
    for sub in ("Journal", "Lessons", "Notes", "Skills", "Routines"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    (base / "Journal" / "weekly").mkdir(exist_ok=True)
    (base / f"agent-{agent_id}.md").write_text(
        "---\n"
        f"title: {agent_id}\n"
        f"description: test agent {agent_id}\n"
        "type: agent\n"
        "---\n\nhub\n",
        encoding="utf-8",
    )
    return base


def _seed_journal(agent_dir: Path, date: str, timestamp: str, text: str) -> Path:
    path = agent_dir / "Journal" / f"{date}.md"
    if not path.exists():
        path.write_text(
            "---\n"
            f'title: "Journal {date}"\n'
            "type: journal\n"
            "tags: [journal]\n"
            "---\n\n",
            encoding="utf-8",
        )
    with path.open("a", encoding="utf-8") as f:
        f.write(f"## {timestamp}\n\n{text}\n\n---\n\n")
    return path


class SessionStartRecallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-recall-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-recall-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)
        # VAULT_INDEX_DB is computed at module load from DATA_DIR — the
        # botload harness already redirected DATA_DIR to tmp_home/.claude-bot,
        # so we need to repoint VAULT_INDEX_DB too.
        self.bot.VAULT_INDEX_DB = self.bot.DATA_DIR / "vault-index.sqlite"
        # Seed the vault
        _seed_agent(self.vault, "main")
        _seed_agent(self.vault, "crypto-bro")
        _seed_journal(
            self.vault / "main", "2026-04-10", "15:00",
            "We decided the architecture uses FTS5 with porter stemming "
            "and per-agent isolation enforced by the WHERE clause.",
        )
        _seed_journal(
            self.vault / "crypto-bro", "2026-04-10", "16:00",
            "Bitcoin options expiring on friday look like they need rolling.",
        )

    def _build_index(self) -> None:
        """Build the FTS index at the bot's VAULT_INDEX_DB location."""
        vault_index.rebuild(self.vault, self.bot.VAULT_INDEX_DB)

    def test_fresh_session_gets_recall_block(self) -> None:
        self._build_index()
        session = self.bot.Session(name="test", agent="main")
        # Fresh session: message_count=0, session_id=None
        block = self.bot._session_start_recall("FTS5 porter stemming", session)
        self.assertIsNotNone(block, "fresh session should get a Recent Context block")
        self.assertIn("## Recent Context", block)
        self.assertIn("main/Journal/2026-04-10.md", block)

    def test_recall_scopes_to_session_agent(self) -> None:
        """Isolation: the main agent's session should NOT see crypto-bro's journal."""
        self._build_index()
        main_session = self.bot.Session(name="m", agent="main")
        crypto_session = self.bot.Session(name="c", agent="crypto-bro")

        # Searching for "bitcoin" on the main agent should return nothing
        main_block = self.bot._session_start_recall("bitcoin options friday", main_session)
        self.assertIsNone(
            main_block,
            "main agent must not recall crypto-bro's content (contract C3)",
        )
        # Same search on crypto-bro should hit
        crypto_block = self.bot._session_start_recall(
            "bitcoin options friday", crypto_session,
        )
        self.assertIsNotNone(crypto_block)
        self.assertIn("crypto-bro/Journal/2026-04-10.md", crypto_block)

    def test_recall_skipped_for_resumed_session(self) -> None:
        """A session with message_count > 0 or a non-None session_id skips recall."""
        self._build_index()
        session = self.bot.Session(
            name="test", agent="main",
            session_id="abc123", message_count=5,
        )
        block = self.bot._session_start_recall("FTS5 architecture", session)
        self.assertIsNone(block, "resumed sessions must not trigger recall")

    def test_recall_fail_open_when_index_missing(self) -> None:
        """Without an FTS DB on disk, recall returns None silently."""
        # Do NOT build the index
        session = self.bot.Session(name="test", agent="main")
        block = self.bot._session_start_recall("anything", session)
        self.assertIsNone(block)
        self.assertFalse(
            self.bot.VAULT_INDEX_DB.exists(),
            "test precondition: no index file",
        )

    def test_recall_respects_active_memory_off(self) -> None:
        self._build_index()
        session = self.bot.Session(name="test", agent="main", active_memory=False)
        block = self.bot._session_start_recall("FTS5 architecture", session)
        self.assertIsNone(block)

    def test_recall_respects_global_flag(self) -> None:
        self._build_index()
        session = self.bot.Session(name="test", agent="main")
        original = self.bot.ACTIVE_MEMORY_ENABLED
        self.bot.ACTIVE_MEMORY_ENABLED = False
        try:
            block = self.bot._session_start_recall("FTS5 architecture", session)
            self.assertIsNone(block)
        finally:
            self.bot.ACTIVE_MEMORY_ENABLED = original


class ActiveMemoryV2FTSTests(unittest.TestCase):
    """Active Memory v2 should prefer the FTS path when the index has matches."""

    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-amv2-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-amv2-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)
        self.bot.VAULT_INDEX_DB = self.bot.DATA_DIR / "vault-index.sqlite"
        _seed_agent(self.vault, "main")

    def test_fts_hit_returns_active_memory_block(self) -> None:
        _seed_journal(
            self.vault / "main", "2026-04-14", "11:30",
            "A very specific word: tangerine — used for testing FTS path.",
        )
        vault_index.rebuild(self.vault, self.bot.VAULT_INDEX_DB)
        block = self.bot._active_memory_lookup("tangerine testing", agent_id="main")
        self.assertIsNotNone(block)
        self.assertIn("## Active Memory", block)
        self.assertIn("main/Journal/2026-04-14.md", block)

    def test_fts_misses_falls_back_to_graph(self) -> None:
        """When the FTS path returns nothing, the graph-based scoring is
        still used — proving the fallback works for existing installs that
        haven't built the index yet."""
        import json
        # Build a minimal graph.json with one matching node + a file body
        graph_dir = self.vault / ".graphs"
        graph_dir.mkdir(parents=True, exist_ok=True)
        (graph_dir / "graph.json").write_text(json.dumps({
            "nodes": [{
                "id": "notes_unique_marker",
                "label": "Unique Marker",
                "source_file": "main/Notes/unique-marker.md",
                "type": "note",
                "description": "persimmon themed note",
                "tags": ["persimmon"],
            }],
            "edges": [],
        }), encoding="utf-8")
        note = self.vault / "main" / "Notes" / "unique-marker.md"
        note.write_text(
            "---\ntitle: Unique Marker\ntype: note\n---\n\n"
            "This note is about persimmon stuff.\n",
            encoding="utf-8",
        )
        # No FTS DB exists → fallback path must return the graph-based block.
        block = self.bot._active_memory_lookup("persimmon", agent_id="main")
        self.assertIsNotNone(block)
        self.assertIn("main/Notes/unique-marker.md", block)


class VaultIndexUpsertTests(unittest.TestCase):
    """The bot's _vault_index_upsert helper must be fail-open and update
    the index synchronously when the DB exists."""

    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-upsert-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-upsert-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)
        self.bot.VAULT_INDEX_DB = self.bot.DATA_DIR / "vault-index.sqlite"
        _seed_agent(self.vault, "main")

    def test_upsert_is_noop_when_db_missing(self) -> None:
        # Build vault content but no index → upsert is a silent no-op
        self.bot._vault_index_upsert(
            agent="main", rel_path="main/Notes/x.md",
        )
        self.assertFalse(self.bot.VAULT_INDEX_DB.exists())

    def test_upsert_empty_agent_is_noop(self) -> None:
        vault_index.rebuild(self.vault, self.bot.VAULT_INDEX_DB)
        self.bot._vault_index_upsert(agent="", rel_path="main/Notes/x.md")
        # No crash; empty agent is a silent noop at the bot helper layer
        # (contract C2 is enforced inside vault_index where it matters)

    def test_upsert_journal_section_indexes_the_new_section(self) -> None:
        """Simulate the write-through from _snapshot_session_to_journal:
        after upsert_journal_section runs, a search for distinctive words
        in the new section succeeds without touching the raw journal file."""
        vault_index.rebuild(self.vault, self.bot.VAULT_INDEX_DB)
        self.bot._vault_index_upsert(
            agent="main",
            rel_path="main/Journal/2026-04-14.md",
            journal_section=("12:34", "watermelon snapshot appearing in FTS"),
        )
        conn = sqlite3.connect(str(self.bot.VAULT_INDEX_DB))
        try:
            rows = conn.execute("""
                SELECT e.id FROM entries_fts
                JOIN entries e ON e.id = entries_fts.rowid
                WHERE entries_fts MATCH 'watermelon' AND e.agent = 'main'
            """).fetchall()
            self.assertEqual(len(rows), 1)
        finally:
            conn.close()


class BootstrapAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-boot-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-boot-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)
        self.bot.VAULT_INDEX_DB = self.bot.DATA_DIR / "vault-index.sqlite"
        _seed_agent(self.vault, "main")

    def test_bootstrap_indexes_new_agent_synchronously(self) -> None:
        """Contract C6: after creating a new agent and calling
        _vault_index_bootstrap_agent, the new agent's content is queryable
        immediately without waiting for the 04:05 daily rebuild."""
        vault_index.rebuild(self.vault, self.bot.VAULT_INDEX_DB)
        # Create a new agent with content
        _seed_agent(self.vault, "freshie")
        note = self.vault / "freshie" / "Notes" / "welcome.md"
        note.write_text(
            "---\ntitle: Welcome\ntype: note\n---\n\n"
            "A brand new agent note about cantaloupe.\n",
            encoding="utf-8",
        )
        self.bot._vault_index_bootstrap_agent("freshie")

        conn = sqlite3.connect(str(self.bot.VAULT_INDEX_DB))
        try:
            row = conn.execute("""
                SELECT COUNT(*) FROM entries WHERE agent = 'freshie'
            """).fetchone()
            self.assertGreaterEqual(row[0], 1)
            hits = conn.execute("""
                SELECT e.rel_path FROM entries_fts
                JOIN entries e ON e.id = entries_fts.rowid
                WHERE entries_fts MATCH 'cantaloupe' AND e.agent = 'freshie'
            """).fetchall()
            self.assertEqual(len(hits), 1)
        finally:
            conn.close()

    def test_bootstrap_is_noop_when_db_missing(self) -> None:
        # No DB, no crash, no side effects
        _seed_agent(self.vault, "freshie")
        self.bot._vault_index_bootstrap_agent("freshie")
        self.assertFalse(self.bot.VAULT_INDEX_DB.exists())


if __name__ == "__main__":
    unittest.main()
