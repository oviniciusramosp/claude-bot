"""Tests for vault checkpoint — filesystem snapshot before routine execution.

The checkpoint system snapshots vault/ before each routine runs so changes
can be rolled back on failure.  Previous implementation used ``git stash``
which inadvertently restored deleted files and could lose new untracked ones.
The current implementation uses ``shutil.copytree`` / ``shutil.rmtree``.
"""
from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from tests._botload import load_bot_module


class _Base(unittest.TestCase):
    """Shared setup: load bot module with a tmp vault."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="ckpt-test-"))
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        # Seed a minimal vault structure
        routines = self.vault / "main" / "Routines"
        routines.mkdir(parents=True)
        (self.vault / "main" / "agent-main.md").write_text("---\nname: Main\n---\n")
        (routines / "daily-check.md").write_text("---\ntype: routine\n---\nDo stuff\n")
        (routines / "report.md").write_text("---\ntype: routine\n---\nReport\n")

        self.bot = load_bot_module(self.tmp / "home", self.vault)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)


class TestCreateSnapshot(_Base):
    def test_snapshot_contains_files(self) -> None:
        ref = self.bot.vault_checkpoint_create("test")
        self.assertIsNotNone(ref)
        snap = Path(ref) / "vault" / "main" / "Routines"
        self.assertTrue((snap / "daily-check.md").exists())
        self.assertTrue((snap / "report.md").exists())
        self.bot.vault_checkpoint_drop(ref)

    def test_snapshot_excludes_ignored_dirs(self) -> None:
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "workspace.json").write_text("{}")
        (self.vault / ".graphs").mkdir()
        (self.vault / ".graphs" / "graph.json").write_text("{}")
        (self.vault / "Images").mkdir()
        (self.vault / "Images" / "photo.png").write_bytes(b"\x89PNG")

        ref = self.bot.vault_checkpoint_create("test")
        self.assertIsNotNone(ref)
        snap = Path(ref) / "vault"
        self.assertFalse((snap / ".obsidian").exists())
        self.assertFalse((snap / ".graphs").exists())
        self.assertFalse((snap / "Images").exists())
        self.bot.vault_checkpoint_drop(ref)

    def test_returns_none_when_vault_missing(self) -> None:
        shutil.rmtree(self.vault)
        ref = self.bot.vault_checkpoint_create("test")
        self.assertIsNone(ref)


class TestRestore(_Base):
    def test_restore_reverts_changes(self) -> None:
        target = self.vault / "main" / "Routines" / "daily-check.md"
        original = target.read_text()

        ref = self.bot.vault_checkpoint_create("test")
        # Simulate routine modifying the file
        target.write_text("MODIFIED CONTENT")
        self.assertNotEqual(target.read_text(), original)

        ok = self.bot.vault_checkpoint_restore(ref)
        self.assertTrue(ok)
        self.assertEqual(target.read_text(), original)

    def test_restore_removes_files_created_during_routine(self) -> None:
        ref = self.bot.vault_checkpoint_create("test")
        # Simulate routine creating a new file
        new_file = self.vault / "main" / "Routines" / "new-routine.md"
        new_file.write_text("---\ntype: routine\n---\n")
        self.assertTrue(new_file.exists())

        self.bot.vault_checkpoint_restore(ref)
        self.assertFalse(new_file.exists())

    def test_restore_recreates_files_deleted_during_routine(self) -> None:
        target = self.vault / "main" / "Routines" / "report.md"
        original = target.read_text()

        ref = self.bot.vault_checkpoint_create("test")
        target.unlink()
        self.assertFalse(target.exists())

        self.bot.vault_checkpoint_restore(ref)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), original)


class TestDrop(_Base):
    def test_drop_removes_backup(self) -> None:
        ref = self.bot.vault_checkpoint_create("test")
        self.assertIsNotNone(ref)
        self.assertTrue(Path(ref).is_dir())

        self.bot.vault_checkpoint_drop(ref)
        self.assertFalse(Path(ref).exists())


class TestDeletedFileStaysDeleted(_Base):
    """Regression: the original bug — a file deleted by the user before
    the checkpoint must NOT reappear after drop (success path)."""

    def test_deleted_file_stays_deleted_after_drop(self) -> None:
        target = self.vault / "main" / "Routines" / "daily-check.md"
        # User deletes the routine before any checkpoint
        target.unlink()
        self.assertFalse(target.exists())

        # A different routine runs, checkpoint is created
        ref = self.bot.vault_checkpoint_create("other-routine")
        # Routine succeeds — drop the checkpoint
        if ref:
            self.bot.vault_checkpoint_drop(ref)

        # The deleted file must still be gone
        self.assertFalse(target.exists())


class TestNewFileSurvivesDrop(_Base):
    """Inverse bug: a file created by the user before the checkpoint
    must NOT disappear after drop (success path)."""

    def test_new_file_survives_drop(self) -> None:
        new_file = self.vault / "main" / "Routines" / "user-created.md"
        new_file.write_text("---\ntype: routine\n---\nMy routine\n")

        ref = self.bot.vault_checkpoint_create("test")
        # Routine succeeds — drop the checkpoint
        if ref:
            self.bot.vault_checkpoint_drop(ref)

        # The new file must still exist
        self.assertTrue(new_file.exists())
        self.assertIn("My routine", new_file.read_text())


if __name__ == "__main__":
    unittest.main()
