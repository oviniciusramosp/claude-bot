"""Tests for vault_index.refresh_stale() — the read-time lazy refresh path.

These tests pin the behavior that makes the FTS index always reflect the
current state of ``.md`` files on disk at the moment of every search read.
Without this, human edits in Obsidian (or git pulls, or vim saves) only
showed up after the 04:05 daily rebuild.

The fast path (no files changed) MUST be cheap — no frontmatter parsing,
no writes. Only a GROUP BY query + one stat() per indexed file.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import vault_index  # noqa: E402


# --- minimal fixtures (duplicated from test_vault_index.py so this file
# stays runnable in isolation without cross-test imports) ----------------


def _make_agent(vault: Path, agent_id: str) -> Path:
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


def _bump_mtime(path: Path, seconds_ahead: float = 2.0) -> None:
    """Force the filesystem mtime forward so refresh_stale reliably
    detects the edit even on filesystems with coarse-grained timestamps."""
    new = time.time() + seconds_ahead
    os.utime(path, (new, new))


# ------------------------------------------------------------------------


class RefreshStaleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cb-vi-stale-"))
        self.vault = self.tmp / "vault"
        self.db = self.tmp / "idx.sqlite"
        self.vault.mkdir()
        self.main = _make_agent(self.vault, "main")
        _write_journal(self.main, "2026-04-14", [("10:00", "first entry about apples")])
        _write_note(self.main, "seed-note", "seed note body about oranges")
        self.conn = vault_index.connect(self.db)
        vault_index.rebuild_agent(self.conn, self.vault, "main")

    def tearDown(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    # --- contract C2: empty agent is a programming error ----------------

    def test_refresh_stale_requires_agent(self) -> None:
        with self.assertRaises(ValueError):
            vault_index.refresh_stale(self.conn, self.vault, "")
        with self.assertRaises(ValueError):
            vault_index.refresh_stale(self.conn, self.vault, "   ")

    # --- fast path: nothing changed -------------------------------------

    def test_refresh_stale_noop_after_rebuild(self) -> None:
        """Immediately after rebuild, a refresh must touch zero rows."""
        stats = vault_index.refresh_stale(self.conn, self.vault, "main")
        self.assertEqual(stats.upserted, 0)
        self.assertEqual(stats.deleted, 0)
        # Both files (journal + note) walked, but neither reparsed
        self.assertGreaterEqual(stats.checked, 2)

    # --- case 1: new file on disk not yet in the DB ---------------------

    def test_refresh_stale_picks_up_brand_new_note(self) -> None:
        _write_note(self.main, "fresh-insight", "pineapple is the keyword")
        stats = vault_index.refresh_stale(self.conn, self.vault, "main")
        self.assertGreaterEqual(stats.upserted, 1)
        hits = vault_index.search(self.conn, "main", "pineapple")
        self.assertEqual(len(hits), 1)
        self.assertIn("fresh-insight", hits[0].rel_path)

    # --- case 2: file modified on disk (mtime bumped) -------------------

    def test_refresh_stale_reindexes_modified_file(self) -> None:
        note = self.main / "Notes" / "seed-note.md"
        note.write_text(
            "---\n"
            'title: "seed-note"\n'
            "type: note\n"
            "---\n\n"
            "newword grapefruit added after the original orange mention\n",
            encoding="utf-8",
        )
        _bump_mtime(note)
        # Before refresh: the new term is NOT searchable
        pre = vault_index.search(self.conn, "main", "grapefruit")
        self.assertEqual(pre, [])
        # After refresh: it IS
        stats = vault_index.refresh_stale(self.conn, self.vault, "main")
        self.assertGreaterEqual(stats.upserted, 1)
        post = vault_index.search(self.conn, "main", "grapefruit")
        self.assertEqual(len(post), 1)

    # --- case 3: file removed from disk (orphan row cleanup) ------------

    def test_refresh_stale_removes_orphan_rows(self) -> None:
        note = self.main / "Notes" / "seed-note.md"
        note.unlink()
        stats = vault_index.refresh_stale(self.conn, self.vault, "main")
        self.assertGreaterEqual(stats.deleted, 1)
        # The body term should no longer surface
        hits = vault_index.search(self.conn, "main", "oranges")
        self.assertEqual(hits, [])

    # --- case 4: rename detected as delete+insert -----------------------

    def test_refresh_stale_handles_rename(self) -> None:
        old = self.main / "Notes" / "seed-note.md"
        new = self.main / "Notes" / "renamed-note.md"
        old.rename(new)
        stats = vault_index.refresh_stale(self.conn, self.vault, "main")
        # one inserted (new path) + one deleted (old orphan)
        self.assertGreaterEqual(stats.upserted, 1)
        self.assertGreaterEqual(stats.deleted, 1)
        hits = vault_index.search(self.conn, "main", "oranges")
        self.assertEqual(len(hits), 1)
        self.assertIn("renamed-note", hits[0].rel_path)

    # --- isolation: refreshing one agent must never touch another ------

    def test_refresh_stale_honors_agent_isolation(self) -> None:
        other = _make_agent(self.vault, "crypto-bro")
        _write_note(other, "crypto-note", "bitcoin prices going up")
        vault_index.rebuild_agent(self.conn, self.vault, "crypto-bro")
        # Modify a main file; refresh only main
        note = self.main / "Notes" / "seed-note.md"
        note.write_text(
            "---\n"
            'title: "seed-note"\n'
            "type: note\n"
            "---\n\n"
            "strawberry was added\n",
            encoding="utf-8",
        )
        _bump_mtime(note)
        before_crypto = vault_index.search(self.conn, "crypto-bro", "bitcoin")
        vault_index.refresh_stale(self.conn, self.vault, "main")
        after_crypto = vault_index.search(self.conn, "crypto-bro", "bitcoin")
        # crypto-bro rows must be byte-identical across the refresh
        self.assertEqual(len(before_crypto), len(after_crypto))
        self.assertEqual(
            [h.rel_path for h in before_crypto],
            [h.rel_path for h in after_crypto],
        )

    # --- orphan sweep must not touch other agents' rows -----------------

    def test_refresh_stale_orphan_sweep_scoped_to_agent(self) -> None:
        other = _make_agent(self.vault, "crypto-bro")
        _write_note(other, "crypto-note", "ethereum staking rewards")
        vault_index.rebuild_agent(self.conn, self.vault, "crypto-bro")
        # Delete everything from main
        for p in (self.main / "Notes").glob("*.md"):
            p.unlink()
        for p in (self.main / "Journal").glob("*.md"):
            p.unlink()
        vault_index.refresh_stale(self.conn, self.vault, "main")
        # crypto-bro rows must still be there
        hits = vault_index.search(self.conn, "crypto-bro", "ethereum")
        self.assertEqual(len(hits), 1)

    # --- legacy vault/Journal/*.md (pre-v3.1) is owned by agent=main ----

    def test_refresh_stale_covers_legacy_main_journal(self) -> None:
        legacy_dir = self.vault / "Journal"
        legacy_dir.mkdir(exist_ok=True)
        legacy_file = legacy_dir / "2026-04-13.md"
        legacy_file.write_text(
            "---\n"
            'title: "Journal 2026-04-13"\n'
            "type: journal\n"
            "---\n\n"
            "## 09:00\n\nlegacytopic watermelon\n\n---\n\n",
            encoding="utf-8",
        )
        stats = vault_index.refresh_stale(self.conn, self.vault, "main")
        self.assertGreaterEqual(stats.upserted, 1)
        hits = vault_index.search(self.conn, "main", "watermelon")
        self.assertEqual(len(hits), 1)
        self.assertTrue(hits[0].rel_path.startswith("Journal/"))

    # --- modified journal file doesn't leave stale rows -----------------

    def test_refresh_stale_replaces_journal_sections_cleanly(self) -> None:
        """Journals are per-section rows. A rewrite must not leave the old
        section lurking as dead content."""
        journal = self.main / "Journal" / "2026-04-14.md"
        # Rewrite with a DIFFERENT 10:00 section content
        journal.write_text(
            "---\n"
            'title: "Journal 2026-04-14"\n'
            "type: journal\n"
            "created: 2026-04-14\n"
            "updated: 2026-04-14\n"
            "tags: [journal]\n"
            "---\n\n"
            "## 10:00\n\ntotally different content about mangoes\n\n---\n\n",
            encoding="utf-8",
        )
        _bump_mtime(journal)
        vault_index.refresh_stale(self.conn, self.vault, "main")
        # Old term gone
        self.assertEqual(vault_index.search(self.conn, "main", "apples"), [])
        # New term present
        self.assertEqual(len(vault_index.search(self.conn, "main", "mangoes")), 1)


if __name__ == "__main__":
    unittest.main()
