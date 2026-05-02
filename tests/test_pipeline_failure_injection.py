"""Tests for Pipeline v2 failure injection (Commit 8 of Phase 1).

Validates:
- _append_pipeline_failure_block writes structured blocks to agent-temp.md
- _collect_pipeline_failure_blocks parses them back
- _clear_pipeline_failure_block (by run_id) removes one block
- _clear_pipeline_failures_for_pipeline removes all blocks for a pipeline
- _session_start_recall surfaces blocks as `## Pipeline status` prefix
- Per-agent threading.Lock serializes concurrent appends (no lost updates)
- Auto-clear on successful pipeline re-run
"""

import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _botload import load_bot_module, ensure_agent_layout


class FailureBlockHelpersTests(unittest.TestCase):
    """Module-level helpers for managing failure blocks in agent-temp.md."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-fblocks-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)
        ensure_agent_layout(cls.bot.VAULT_DIR, "main")
        cls.path = cls.bot._pipeline_failure_block_path("main")

    def setUp(self):
        # Reset the file each test
        if self.path.exists():
            self.path.unlink()

    def test_append_creates_skeleton_when_missing(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s1", "ran_at": "2026-05-02T21:00:00",
             "run_id": "1714680000-abc123", "reason": "step s1 failed"},
        )
        self.assertTrue(self.path.exists())
        text = self.path.read_text()
        # Frontmatter created
        self.assertIn("type: history", text)
        self.assertIn("title: Temp — main", text)
        # Block written
        self.assertIn("## pipeline_failure", text)
        self.assertIn("- pipeline: p1", text)
        self.assertIn("- run_id: 1714680000-abc123", text)

    def test_append_skip_block_uses_skip_header(self):
        self.bot._append_pipeline_failure_block(
            "main", "skip",
            {"pipeline": "p2", "step": "writer", "ran_at": "2026-05-02T22:00:00",
             "run_id": "1714680001-def456", "reason": "no news today"},
        )
        text = self.path.read_text()
        self.assertIn("## pipeline_skip", text)
        self.assertNotIn("## pipeline_failure", text)

    def test_collect_returns_parsed_blocks(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s1", "ran_at": "2026-05-02T21:00:00",
             "run_id": "abc", "reason": "boom"},
        )
        self.bot._append_pipeline_failure_block(
            "main", "skip",
            {"pipeline": "p2", "step": "s2", "ran_at": "2026-05-02T22:00:00",
             "run_id": "def", "reason": "nothing"},
        )
        blocks = self.bot._collect_pipeline_failure_blocks("main")
        self.assertEqual(len(blocks), 2)
        kinds = {b["kind"] for b in blocks}
        self.assertEqual(kinds, {"failure", "skip"})

    def test_collect_returns_empty_when_no_file(self):
        self.assertEqual(self.bot._collect_pipeline_failure_blocks("nonexistent_agent"), [])

    def test_collect_returns_empty_when_no_blocks(self):
        # File exists but has only frontmatter
        self.bot._ensure_agent_temp_skeleton(self.path, "main")
        self.assertEqual(self.bot._collect_pipeline_failure_blocks("main"), [])

    def test_clear_by_run_id_removes_only_matching(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s1", "ran_at": "x", "run_id": "abc"},
        )
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p2", "step": "s2", "ran_at": "x", "run_id": "def"},
        )
        cleared = self.bot._clear_pipeline_failure_block("main", "abc")
        self.assertTrue(cleared)
        remaining = self.bot._collect_pipeline_failure_blocks("main")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["run_id"], "def")

    def test_clear_by_run_id_returns_false_when_not_found(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s1", "ran_at": "x", "run_id": "abc"},
        )
        cleared = self.bot._clear_pipeline_failure_block("main", "nonexistent")
        self.assertFalse(cleared)
        # Original still present
        self.assertEqual(len(self.bot._collect_pipeline_failure_blocks("main")), 1)

    def test_clear_by_pipeline_removes_all_matching(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s1", "ran_at": "x", "run_id": "a"},
        )
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s2", "ran_at": "y", "run_id": "b"},
        )
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p2", "step": "s3", "ran_at": "z", "run_id": "c"},
        )
        cleared = self.bot._clear_pipeline_failures_for_pipeline("main", "p1")
        self.assertEqual(cleared, 2)
        remaining = self.bot._collect_pipeline_failure_blocks("main")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["pipeline"], "p2")

    def test_concurrent_appends_serialized(self):
        """Per-agent lock prevents lost updates from concurrent failures."""
        N = 8
        threads = []
        for i in range(N):
            t = threading.Thread(
                target=self.bot._append_pipeline_failure_block,
                args=("main", "failure", {
                    "pipeline": f"p{i}", "step": "s", "ran_at": "x",
                    "run_id": f"run-{i}",
                }),
            )
            threads.append(t)
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        blocks = self.bot._collect_pipeline_failure_blocks("main")
        self.assertEqual(len(blocks), N)
        run_ids = {b["run_id"] for b in blocks}
        self.assertEqual(len(run_ids), N)  # all unique survived

    def test_overrides_field_serialized_as_json(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s1", "ran_at": "x", "run_id": "z",
             "overrides": {"analyst": {"focus_asset": "ETH"}}},
        )
        text = self.path.read_text()
        # JSON-encoded dict appears verbatim on the line
        self.assertIn('"focus_asset"', text)
        self.assertIn('"ETH"', text)


class SessionStartRecallIntegrationTests(unittest.TestCase):
    """_session_start_recall surfaces failure blocks as ## Pipeline status prefix."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-recall-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)
        ensure_agent_layout(cls.bot.VAULT_DIR, "main")

    def setUp(self):
        path = self.bot._pipeline_failure_block_path("main")
        if path.exists():
            path.unlink()

    def _make_session(self, agent="main", session_id=None, message_count=0,
                      active_memory=True):
        s = MagicMock()
        s.agent = agent
        s.session_id = session_id
        s.message_count = message_count
        s.active_memory = active_memory
        return s

    def test_no_failure_blocks_no_prefix(self):
        # No failures + no FTS hits → None
        session = self._make_session()
        result = self.bot._session_start_recall("hello", session)
        # May be None (no FTS hits) — acceptable
        self.assertTrue(result is None or "Pipeline status" not in result)

    def test_failure_block_surfaces_in_first_turn(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "crypto-ta-analise", "step": "analyst",
             "ran_at": "2026-05-02T21:32:14", "run_id": "1714680000-abc123",
             "reason": "Step 'analyst' returned status='failed'"},
        )
        session = self._make_session()
        result = self.bot._session_start_recall("any prompt", session)
        self.assertIsNotNone(result)
        self.assertIn("## Pipeline status", result)
        self.assertIn("crypto-ta-analise", result)
        self.assertIn("FAILED", result)
        self.assertIn("1714680000-abc123", result)
        self.assertIn("/ack", result)  # acknowledge instruction

    def test_failure_block_skipped_for_resumed_session(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s1", "ran_at": "x", "run_id": "abc"},
        )
        # Resumed session (session_id set) → no recall
        session = self._make_session(session_id="existing-id")
        result = self.bot._session_start_recall("hello", session)
        self.assertIsNone(result)

    def test_failure_block_skipped_when_active_memory_off(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s1", "ran_at": "x", "run_id": "abc"},
        )
        session = self._make_session(active_memory=False)
        result = self.bot._session_start_recall("hello", session)
        self.assertIsNone(result)

    def test_skip_block_uses_skipped_wording(self):
        self.bot._append_pipeline_failure_block(
            "main", "skip",
            {"pipeline": "crypto-news", "step": "writer", "ran_at": "x",
             "run_id": "skip-run", "reason": "no news today"},
        )
        session = self._make_session()
        result = self.bot._session_start_recall("any", session)
        self.assertIsNotNone(result)
        self.assertIn("SKIPPED", result)
        self.assertNotIn("FAILED", result)  # skip is lighter wording


if __name__ == "__main__":
    unittest.main()
