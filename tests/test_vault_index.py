"""Tests for scripts/vault_index.py — SQLite FTS5 index over the vault.

Every contract from .claude/rules/vault-runtime-features.md ("Future-proof
contract for all agents") has at least one test here. If you change the
index library, these tests must stay green — they are the wall that
guarantees future agents are automatically covered without manual setup.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import vault_index  # noqa: E402


def _make_agent(vault: Path, agent_id: str) -> Path:
    """Create a minimal v3.4 agent folder with the hub file so
    discover_agents() picks it up."""
    base = vault / agent_id
    for sub in ("Journal", "Lessons", "Notes", "Skills", "Routines"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    (base / "Journal" / "weekly").mkdir(exist_ok=True)
    hub = base / f"agent-{agent_id}.md"
    hub.write_text(
        "---\n"
        f"title: {agent_id}\n"
        f"description: test agent {agent_id}\n"
        "type: agent\n"
        "---\n\n"
        "hub\n",
        encoding="utf-8",
    )
    return base


def _write_journal(agent_dir: Path, date: str, sections: list[tuple[str, str]]) -> Path:
    path = agent_dir / "Journal" / f"{date}.md"
    header = (
        "---\n"
        f'title: "Journal {date}"\n'
        "type: journal\n"
        f"created: {date}\n"
        f"updated: {date}\n"
        "tags: [journal]\n"
        "---\n\n"
    )
    parts = [header]
    for timestamp, text in sections:
        parts.append(f"## {timestamp}\n\n{text}\n\n---\n\n")
    path.write_text("".join(parts), encoding="utf-8")
    return path


def _write_lesson(agent_dir: Path, name: str, body: str) -> Path:
    path = agent_dir / "Lessons" / f"{name}.md"
    path.write_text(
        "---\n"
        f'title: "{name}"\n'
        "type: lesson\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


def _write_note(agent_dir: Path, slug: str, body: str) -> Path:
    path = agent_dir / "Notes" / f"{slug}.md"
    path.write_text(
        "---\n"
        f'title: "{slug}"\n'
        "type: note\n"
        "---\n\n"
        f"{body}\n",
        encoding="utf-8",
    )
    return path


class RebuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cb-vi-"))
        self.vault = self.tmp / "vault"
        self.db = self.tmp / "idx.sqlite"
        self.vault.mkdir()

    def test_rebuild_indexes_all_agents(self) -> None:
        """Two agents, each with journal + lesson + note — all rows present."""
        main = _make_agent(self.vault, "main")
        crypto = _make_agent(self.vault, "crypto-bro")
        _write_journal(main, "2026-04-14", [("10:30", "main journal entry about apples")])
        _write_lesson(main, "main-lesson", "lesson body about bananas")
        _write_note(main, "main-note", "note body about cherries")
        _write_journal(crypto, "2026-04-14", [("11:00", "crypto journal entry about dragons")])
        _write_lesson(crypto, "crypto-lesson", "lesson about emus")
        _write_note(crypto, "crypto-note", "note about foxes")

        stats = vault_index.rebuild(self.vault, self.db)
        self.assertEqual(sorted(stats.agents), ["crypto-bro", "main"])
        self.assertEqual(stats.rows_inserted, 6)

        conn = vault_index.connect(self.db)
        try:
            count = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            self.assertEqual(count, 6)
            agents = [r[0] for r in conn.execute(
                "SELECT DISTINCT agent FROM entries ORDER BY agent").fetchall()]
            self.assertEqual(agents, ["crypto-bro", "main"])
        finally:
            conn.close()

    def test_rebuild_uses_iter_agent_ids_when_explicit(self) -> None:
        """Contract C1: callers can pass an explicit agent list and the index
        library indexes ONLY those agents.

        This locks the future-proof contract: the bot passes its canonical
        iter_agent_ids() result, and the index library never second-guesses it.
        """
        _make_agent(self.vault, "foo")
        _make_agent(self.vault, "bar")
        _make_agent(self.vault, "baz")  # exists but not in explicit list
        foo_dir = self.vault / "foo"
        bar_dir = self.vault / "bar"
        baz_dir = self.vault / "baz"
        _write_note(foo_dir, "foo-note", "foo content")
        _write_note(bar_dir, "bar-note", "bar content")
        _write_note(baz_dir, "baz-note", "baz content")

        stats = vault_index.rebuild(self.vault, self.db, agent_ids=["foo", "bar"])
        self.assertEqual(sorted(stats.agents), ["bar", "foo"])

        conn = vault_index.connect(self.db)
        try:
            agents = sorted({r[0] for r in conn.execute(
                "SELECT DISTINCT agent FROM entries").fetchall()})
            self.assertEqual(agents, ["bar", "foo"])
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM entries WHERE agent = 'baz'").fetchone()[0],
                0,
                "Contract C1 violated: agent outside explicit list was indexed",
            )
        finally:
            conn.close()

    def test_new_agent_auto_indexed(self) -> None:
        """FUTURE-PROOF GUARANTEE: rebuild with agent_ids=None picks up every
        directory that iter_agent_ids() would match — including agents that
        didn't exist during the previous rebuild.

        Adding an agent today must require zero code or config changes to
        surface it in tomorrow's rebuild.
        """
        _make_agent(self.vault, "agent-a")
        _make_agent(self.vault, "agent-b")
        _write_note(self.vault / "agent-a", "a-note", "content a")
        _write_note(self.vault / "agent-b", "b-note", "content b")
        vault_index.rebuild(self.vault, self.db)

        # Create a THIRD agent with no code change
        _make_agent(self.vault, "agent-c")
        _write_note(self.vault / "agent-c", "c-note", "content c about newborn")

        stats = vault_index.rebuild(self.vault, self.db)
        self.assertIn("agent-c", stats.agents)

        conn = vault_index.connect(self.db)
        try:
            hits = vault_index.search(conn, "agent-c", "newborn")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].rel_path, "agent-c/Notes/c-note.md")
        finally:
            conn.close()

    def test_search_respects_agent_isolation(self) -> None:
        """Contract C3: a query on agent A must NEVER return agent B's rows,
        even when the prompt matches both."""
        _make_agent(self.vault, "main")
        _make_agent(self.vault, "crypto-bro")
        _write_note(self.vault / "main", "m", "zebra pattern content")
        _write_note(self.vault / "crypto-bro", "c", "zebra pattern content")
        vault_index.rebuild(self.vault, self.db)

        conn = vault_index.connect(self.db)
        try:
            main_hits = vault_index.search(conn, "main", "zebra")
            crypto_hits = vault_index.search(conn, "crypto-bro", "zebra")
            self.assertEqual(len(main_hits), 1)
            self.assertEqual(len(crypto_hits), 1)
            self.assertTrue(main_hits[0].rel_path.startswith("main/"))
            self.assertTrue(crypto_hits[0].rel_path.startswith("crypto-bro/"))
        finally:
            conn.close()

    def test_upsert_agent_indexes_brand_new_folder(self) -> None:
        """Contract C6: post-/agent new bootstrap indexes a brand-new agent
        folder synchronously, without a full rebuild."""
        _make_agent(self.vault, "main")
        _write_note(self.vault / "main", "m", "existing content")
        vault_index.rebuild(self.vault, self.db)

        # Create a new agent and call upsert_agent directly (simulates the
        # bot's _run_agent_create_skill bootstrap path).
        _make_agent(self.vault, "fresh")
        _write_note(self.vault / "fresh", "f", "brand new fresh content xylophone")

        conn = vault_index.connect(self.db)
        try:
            stats = vault_index.upsert_agent(conn, self.vault, "fresh")
            self.assertGreaterEqual(stats.rows_inserted, 1)
            hits = vault_index.search(conn, "fresh", "xylophone")
            self.assertEqual(len(hits), 1)
            # Main's rows are untouched
            main_count = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE agent = 'main'").fetchone()[0]
            self.assertGreaterEqual(main_count, 1)
        finally:
            conn.close()

    def test_helpers_raise_on_empty_agent(self) -> None:
        """Contract C2: every helper refuses to run without an agent_id."""
        _make_agent(self.vault, "main")
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            with self.assertRaises(ValueError):
                vault_index.search(conn, "", "anything")
            with self.assertRaises(ValueError):
                vault_index.timeline(conn, "", 1)
            with self.assertRaises(ValueError):
                vault_index.get_excerpt(conn, "", 1)
            with self.assertRaises(ValueError):
                vault_index.upsert_file(conn, self.vault, "", "main/Notes/x.md")
            with self.assertRaises(ValueError):
                vault_index.upsert_agent(conn, self.vault, "")
            with self.assertRaises(ValueError):
                vault_index.rebuild_agent(conn, self.vault, "")
        finally:
            conn.close()

    def test_upsert_journal_section_fast_path(self) -> None:
        """upsert_journal_section writes a single row without reading the
        on-disk file, so the MCP server's vault_append_journal write-through
        doesn't pay a reparse cost per turn."""
        _make_agent(self.vault, "main")
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            inserted = vault_index.upsert_journal_section(
                conn, self.vault, "main",
                rel_path="main/Journal/2026-04-14.md",
                timestamp="15:45",
                text="A distinctive phrase for the fast path test — pomegranate.",
            )
            self.assertEqual(inserted, 1)
            hits = vault_index.search(conn, "main", "pomegranate")
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0].section_path, "## 15:45")
        finally:
            conn.close()

    def test_private_tags_stripped_from_fts(self) -> None:
        main = _make_agent(self.vault, "main")
        _write_journal(main, "2026-04-14", [
            ("10:00", "public content kiwi\n<private>secret banana</private> visible"),
        ])
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            # Public keyword matches
            hits_pub = vault_index.search(conn, "main", "kiwi")
            self.assertEqual(len(hits_pub), 1)
            # Private keyword is NOT findable
            hits_priv = vault_index.search(conn, "main", "banana")
            self.assertEqual(len(hits_priv), 0)
            # Row is flagged as private
            row = conn.execute(
                "SELECT private FROM entries WHERE agent = 'main'").fetchone()
            self.assertEqual(row[0], 1)
        finally:
            conn.close()

    def test_private_flag_excludes_file_when_opt_in(self) -> None:
        """Files that had any <private> marker are returned by default
        (their public content is still useful). Callers — like SessionStart
        auto-recall — can opt into extra caution by passing
        include_private=False, which hides the whole file even though its
        private TEXT is already stripped from the indexed body."""
        main = _make_agent(self.vault, "main")
        _write_note(main, "n", "<private>zebra marker</private>\nvisible kiwi text")
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            # Default: show the row (its public content is searchable)
            hits_default = vault_index.search(conn, "main", "kiwi")
            self.assertEqual(len(hits_default), 1)
            # Opt-in exclusion (used by SessionStart recall)
            hits_strict = vault_index.search(conn, "main", "kiwi", include_private=False)
            self.assertEqual(len(hits_strict), 0)
        finally:
            conn.close()

    def test_raw_file_unchanged_by_private_tag(self) -> None:
        """strip_private modifies only the in-memory copy used for indexing —
        the markdown file on disk keeps the original text."""
        main = _make_agent(self.vault, "main")
        path = _write_note(main, "n", "before\n<private>secret</private>\nafter")
        vault_index.rebuild(self.vault, self.db)
        raw = path.read_text(encoding="utf-8")
        self.assertIn("<private>secret</private>", raw)

    def test_legacy_journal_path_assigned_to_main(self) -> None:
        """Contract C4: pre-v3.1 vault/Journal/*.md files are indexed under
        agent='main' (matching guard-journal-write.sh regex)."""
        _make_agent(self.vault, "main")
        legacy = self.vault / "Journal"
        legacy.mkdir()
        (legacy / "2026-04-13.md").write_text(
            "---\ntitle: legacy\ntype: journal\n---\n\n## 09:00\n\nlegacy garnet entry\n\n---\n",
            encoding="utf-8",
        )
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            hits = vault_index.search(conn, "main", "garnet")
            self.assertEqual(len(hits), 1)
            self.assertTrue(hits[0].rel_path.endswith("Journal/2026-04-13.md"))
        finally:
            conn.close()

    def test_deleted_agent_removed_after_rebuild(self) -> None:
        """Contract C4: the daily rebuild is the authority — removed agents
        vanish from the index on the next run without any code knowing about
        the removal."""
        _make_agent(self.vault, "main")
        _make_agent(self.vault, "gone-tomorrow")
        _write_note(self.vault / "main", "m", "main stays")
        _write_note(self.vault / "gone-tomorrow", "g", "will vanish")
        vault_index.rebuild(self.vault, self.db)

        # Physically delete the agent folder
        import shutil
        shutil.rmtree(self.vault / "gone-tomorrow")

        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            gone_count = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE agent = 'gone-tomorrow'").fetchone()[0]
            self.assertEqual(gone_count, 0)
            main_count = conn.execute(
                "SELECT COUNT(*) FROM entries WHERE agent = 'main'").fetchone()[0]
            self.assertGreaterEqual(main_count, 1)
        finally:
            conn.close()

    def test_rebuild_is_idempotent(self) -> None:
        _make_agent(self.vault, "main")
        _write_note(self.vault / "main", "n", "some content")
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        first = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        conn.close()
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            second = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
            self.assertEqual(first, second)
        finally:
            conn.close()

    def test_fts_porter_stems_match(self) -> None:
        """Porter tokenizer: 'decisioning' should match a search for 'decision'."""
        main = _make_agent(self.vault, "main")
        _write_journal(main, "2026-04-14", [
            ("09:00", "We are decisioning about the rollout approach"),
        ])
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            hits = vault_index.search(conn, "main", "decision rollout")
            self.assertEqual(len(hits), 1)
        finally:
            conn.close()

    def test_schema_migration_v1_to_v1_is_noop(self) -> None:
        _make_agent(self.vault, "main")
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            row = conn.execute(
                "SELECT value FROM index_meta WHERE key = 'schema_version'").fetchone()
            self.assertEqual(row[0], str(vault_index.SCHEMA_VERSION))
        finally:
            conn.close()
        # Re-open: version unchanged, no errors
        conn2 = vault_index.connect(self.db)
        try:
            row = conn2.execute(
                "SELECT value FROM index_meta WHERE key = 'schema_version'").fetchone()
            self.assertEqual(row[0], str(vault_index.SCHEMA_VERSION))
        finally:
            conn2.close()

    def test_broken_db_rebuilds_fresh(self) -> None:
        """Contract C5: a corrupt DB file is renamed and a fresh one is
        created — the bot keeps running."""
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.db.write_bytes(b"this is not a sqlite database")
        conn = vault_index.connect(self.db)
        try:
            # Connection works; table exists; broken file was renamed.
            conn.execute("SELECT COUNT(*) FROM entries")
        finally:
            conn.close()
        broken_candidates = list(self.db.parent.glob("*.broken-*"))
        self.assertTrue(broken_candidates, "broken DB should have been renamed")

    def test_upsert_file_removes_stale_rows_when_file_deleted(self) -> None:
        """If a file vanished before the write-through call, stale rows are
        removed rather than left behind."""
        main = _make_agent(self.vault, "main")
        path = _write_note(main, "doomed", "to be deleted apricot")
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            hits_before = vault_index.search(conn, "main", "apricot")
            self.assertEqual(len(hits_before), 1)
            path.unlink()
            vault_index.upsert_file(conn, self.vault, "main", "main/Notes/doomed.md")
            hits_after = vault_index.search(conn, "main", "apricot")
            self.assertEqual(len(hits_after), 0)
        finally:
            conn.close()

    def test_get_excerpt_caps_body(self) -> None:
        main = _make_agent(self.vault, "main")
        long_body = "keyword " + ("filler " * 200)
        _write_note(main, "big", long_body)
        vault_index.rebuild(self.vault, self.db)
        conn = vault_index.connect(self.db)
        try:
            hits = vault_index.search(conn, "main", "keyword")
            self.assertEqual(len(hits), 1)
            detail = vault_index.get_excerpt(conn, "main", hits[0].id, max_chars=100)
            self.assertIsNotNone(detail)
            self.assertLessEqual(len(detail.body), 101)  # +ellipsis
            self.assertTrue(detail.body.endswith("…"))
        finally:
            conn.close()


class DiscoverAgentsTests(unittest.TestCase):
    def test_skips_reserved_names_and_files_without_hub(self) -> None:
        tmp = Path(tempfile.mkdtemp(prefix="cb-vi-disc-"))
        vault = tmp / "vault"
        vault.mkdir()
        # Reserved names — should be skipped
        (vault / ".graphs").mkdir()
        (vault / ".obsidian").mkdir()
        (vault / "Images").mkdir()
        # Directory without agent-<name>.md — should be skipped
        (vault / "not-an-agent").mkdir()
        (vault / "not-an-agent" / "random.md").write_text("hi", encoding="utf-8")
        # Real agent
        _make_agent(vault, "real")
        agents = vault_index.discover_agents(vault)
        self.assertEqual(agents, ["real"])


if __name__ == "__main__":
    unittest.main()
