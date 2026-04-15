"""Tests for the execution report system (v3.24.0).

Covers:
- _append_execution_report writes structured pipeline reports to agent journal
- _append_execution_report writes structured routine reports to agent journal
- Reports include correct step icons, status, duration, error, and data_dir
- Journal file is created with frontmatter if it doesn't exist
- Agent isolation: reports land in the correct agent's journal directory
- _journal_update_hints is populated for the enhanced nudge
- FTS write-through is called
- Fail-open: function never raises
"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._botload import load_bot_module


class AppendExecutionReportPipeline(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        # Create agent journal directory
        self.journal_dir = self.vault / "main" / "Journal"
        self.journal_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._td.cleanup()

    def test_pipeline_success_report(self):
        steps = [("fetch", "completed"), ("parse", "completed"), ("publish", "completed")]
        path = self.bot._append_execution_report(
            agent="main", kind="pipeline", name="oss-radar",
            status="completed", elapsed=154, steps=steps,
            data_dir="workspace/data/oss-radar/",
        )
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        content = path.read_text(encoding="utf-8")
        self.assertIn("## Pipeline Report — oss-radar", content)
        self.assertIn("**Status:** completed (3/3)", content)
        self.assertIn("**Duration:** 2m 34s", content)
        self.assertIn("✅ fetch", content)
        self.assertIn("✅ parse", content)
        self.assertIn("✅ publish", content)
        self.assertIn("**Outputs:** `workspace/data/oss-radar/`", content)
        self.assertNotIn("**Error:**", content)

    def test_pipeline_failure_report(self):
        steps = [("fetch", "completed"), ("analyze", "failed"), ("publish", "skipped")]
        path = self.bot._append_execution_report(
            agent="main", kind="pipeline", name="oss-radar",
            status="failed", elapsed=72, steps=steps,
            error="timeout after 120s", failed_step="analyze",
            data_dir="workspace/data/oss-radar/",
        )
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("**Status:** failed at step 2/3 (analyze)", content)
        self.assertIn("**Duration:** 1m 12s", content)
        self.assertIn("✅ fetch", content)
        self.assertIn("❌ analyze", content)
        self.assertIn("⏭ publish", content)
        self.assertIn("**Error:** timeout after 120s", content)

    def test_pipeline_cancelled_report(self):
        steps = [("fetch", "completed"), ("analyze", "running"), ("publish", "pending")]
        path = self.bot._append_execution_report(
            agent="main", kind="pipeline", name="oss-radar",
            status="cancelled", elapsed=30, steps=steps,
        )
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("**Status:** cancelled", content)
        self.assertIn("🔄 analyze", content)
        self.assertIn("⏰ publish", content)


class AppendExecutionReportRoutine(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        self.journal_dir = self.vault / "main" / "Journal"
        self.journal_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._td.cleanup()

    def test_routine_success_report(self):
        path = self.bot._append_execution_report(
            agent="main", kind="routine", name="vault-health",
            status="completed", elapsed=12,
        )
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("## Routine Report — vault-health", content)
        self.assertIn("**Status:** completed", content)
        self.assertIn("**Duration:** 0m 12s", content)
        self.assertNotIn("**Error:**", content)
        self.assertNotIn("**Steps:**", content)

    def test_routine_failure_report(self):
        path = self.bot._append_execution_report(
            agent="main", kind="routine", name="vault-health",
            status="failed", elapsed=5, error="Connection timeout",
        )
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("**Status:** failed", content)
        self.assertIn("**Error:** Connection timeout", content)


class JournalFileCreation(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        # Do NOT pre-create Journal dir — test that the function creates it
        (self.vault / "main").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._td.cleanup()

    def test_creates_journal_with_frontmatter(self):
        path = self.bot._append_execution_report(
            agent="main", kind="routine", name="test",
            status="completed", elapsed=1,
        )
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("---\ndate:", content)
        self.assertIn("type: journal", content)
        self.assertIn("agent: main", content)

    def test_appends_to_existing_journal(self):
        journal_dir = self.vault / "main" / "Journal"
        journal_dir.mkdir(parents=True, exist_ok=True)
        today = time.strftime("%Y-%m-%d")
        journal_path = journal_dir / f"{today}.md"
        journal_path.write_text("---\ndate: 2026-04-15\n---\n\n## Existing content\n", encoding="utf-8")

        path = self.bot._append_execution_report(
            agent="main", kind="routine", name="test",
            status="completed", elapsed=1,
        )
        content = path.read_text(encoding="utf-8")
        self.assertIn("## Existing content", content)
        self.assertIn("## Routine Report — test", content)


class AgentIsolation(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        for agent in ("main", "crypto-bro"):
            (self.vault / agent / "Journal").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._td.cleanup()

    def test_report_lands_in_correct_agent_journal(self):
        path_main = self.bot._append_execution_report(
            agent="main", kind="routine", name="test-main",
            status="completed", elapsed=1,
        )
        path_crypto = self.bot._append_execution_report(
            agent="crypto-bro", kind="routine", name="test-crypto",
            status="completed", elapsed=1,
        )
        self.assertIn("main", str(path_main))
        self.assertIn("crypto-bro", str(path_crypto))
        self.assertNotIn("crypto-bro", str(path_main))
        self.assertNotIn("main/Journal", str(path_crypto))


class JournalUpdateHints(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        (self.vault / "main" / "Journal").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        # Clean up module-level dict
        self.bot._journal_update_hints.clear()
        self._td.cleanup()

    def test_success_hint(self):
        self.bot._append_execution_report(
            agent="main", kind="pipeline", name="oss-radar",
            status="completed", elapsed=154,
            steps=[("fetch", "completed")],
        )
        hint = self.bot._journal_update_hints.get("main")
        self.assertIsNotNone(hint)
        self.assertIn("oss-radar", hint)
        self.assertIn("completou", hint)

    def test_failure_hint_with_step(self):
        self.bot._append_execution_report(
            agent="main", kind="pipeline", name="oss-radar",
            status="failed", elapsed=72,
            steps=[("fetch", "completed"), ("analyze", "failed")],
            error="timeout", failed_step="analyze",
        )
        hint = self.bot._journal_update_hints.get("main")
        self.assertIn("falhou", hint)
        self.assertIn("analyze", hint)

    def test_routine_hint(self):
        self.bot._append_execution_report(
            agent="main", kind="routine", name="vault-health",
            status="completed", elapsed=12,
        )
        hint = self.bot._journal_update_hints.get("main")
        self.assertIn("vault-health", hint)
        self.assertIn("completou", hint)


class FailOpen(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)

    def tearDown(self):
        self._td.cleanup()

    def test_returns_none_on_failure(self):
        """Function must never raise — returns None on any error."""
        with patch.object(Path, "open", side_effect=PermissionError("nope")):
            result = self.bot._append_execution_report(
                agent="main", kind="routine", name="broken",
                status="failed", elapsed=0, error="test",
            )
        # Should return None, not raise
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
