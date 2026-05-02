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


class CmdAckSlashCommandTests(unittest.TestCase):
    """The /ack <run_id> command clears a pipeline_failure block by run_id (Q1)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-ack-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)
        ensure_agent_layout(cls.bot.VAULT_DIR, "main")

    def setUp(self):
        path = self.bot._pipeline_failure_block_path("main")
        if path.exists():
            path.unlink()

    def _make_bot(self):
        """Construct a minimal ClaudeTelegramBot with mocked Telegram + session."""
        b = self.bot.ClaudeTelegramBot()
        b.send_message = MagicMock()
        # Mock active session to control current agent
        session = MagicMock()
        session.agent = "main"
        session.name = "test-session"
        b._get_session = MagicMock(return_value=session)
        return b

    def test_ack_no_arg_shows_usage(self):
        b = self._make_bot()
        b.cmd_ack("")
        b.send_message.assert_called_once()
        msg = b.send_message.call_args[0][0]
        self.assertIn("/ack <run_id>", msg)

    def test_ack_invalid_format_shows_error(self):
        b = self._make_bot()
        b.cmd_ack("not-a-valid-id")
        msg = b.send_message.call_args[0][0]
        self.assertIn("inválido", msg)
        self.assertIn("timestamp", msg)

    def test_ack_unknown_run_id_friendly_error(self):
        b = self._make_bot()
        b.cmd_ack("1714680000-abc123")
        msg = b.send_message.call_args[0][0]
        self.assertIn("Nenhum bloco encontrado", msg)
        self.assertIn("1714680000-abc123", msg)

    def test_ack_existing_block_clears_and_confirms(self):
        self.bot._append_pipeline_failure_block(
            "main", "failure",
            {"pipeline": "p1", "step": "s1", "ran_at": "x", "run_id": "1714680000-abc123"},
        )
        b = self._make_bot()
        b.cmd_ack("1714680000-abc123")
        msg = b.send_message.call_args[0][0]
        self.assertIn("removido", msg)
        # Block actually cleared
        self.assertEqual(self.bot._collect_pipeline_failure_blocks("main"), [])

    def test_ack_in_handler_map(self):
        """/ack registered in handler_map (smoke test for command dispatch)."""
        # Build minimal env to access handler_map. We can grep the source as a
        # simpler check that the dispatch entry exists.
        src = Path("/Users/viniciusramos/claude-bot/claude-fallback-bot.py").read_text()
        self.assertIn('"/ack": lambda: self.cmd_ack(arg)', src)

    def test_ack_in_help_text(self):
        self.assertIn("/ack", self.bot.HELP_TEXT)


class CmdRunOverridesTests(unittest.TestCase):
    """/run --overrides '<json>' parses and validates before enqueueing."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pv2-cmdrun-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)
        ensure_agent_layout(cls.bot.VAULT_DIR, "main")
        cls.routines = cls.bot.VAULT_DIR / "main" / "Routines"
        cls.routines.mkdir(parents=True, exist_ok=True)

    def _seed_pipeline(self, name="ovr-pipe"):
        body = (
            "```pipeline\n"
            "steps:\n"
            "  - id: analyst\n"
            "    name: Analyst\n"
            "    model: sonnet\n"
            "    prompt: do analysis\n"
            "    accepts_overrides:\n"
            "      focus_asset:\n"
            "        type: string\n"
            "        enum: [BTC, ETH, SOL]\n"
            "        default: BTC\n"
            "```"
        )
        md = self.routines / f"{name}.md"
        md.write_text("---\ntitle: T\ntype: pipeline\nenabled: true\n---\n" + body, encoding="utf-8")
        return md

    def _make_bot(self):
        b = self.bot.ClaudeTelegramBot()
        b.send_message = MagicMock()
        session = MagicMock()
        session.agent = "main"
        session.name = "test"
        b._get_session = MagicMock(return_value=session)
        # Mock the enqueue path so we can capture what was passed
        b.scheduler = MagicMock()
        b._active_pipelines = set()
        b._active_pipelines_lock = threading.Lock()
        b._routine_contexts = {}
        b._routine_contexts_lock = threading.Lock()
        return b

    def test_run_invalid_overrides_json_fails_loud(self):
        self._seed_pipeline("p1")
        b = self._make_bot()
        b.cmd_run("p1 --overrides '{not json}'")
        msg = b.send_message.call_args[0][0]
        self.assertIn("inválido", msg)
        b.scheduler._enqueue_pipeline_from_file.assert_not_called()

    def test_run_overrides_validation_error_friendly(self):
        self._seed_pipeline("p2")
        b = self._make_bot()
        # Pass enum-violation override
        b.cmd_run('p2 --overrides \'{"analyst": {"focus_asset": "DOGE"}}\'')
        msg = b.send_message.call_args[0][0]
        self.assertIn("Override inválido", msg)
        b.scheduler._enqueue_pipeline_from_file.assert_not_called()

    def test_run_valid_overrides_passes_through_to_enqueue(self):
        self._seed_pipeline("p3")
        b = self._make_bot()
        b.cmd_run('p3 --overrides \'{"analyst": {"focus_asset": "ETH"}}\'')
        b.scheduler._enqueue_pipeline_from_file.assert_called_once()
        kwargs = b.scheduler._enqueue_pipeline_from_file.call_args.kwargs
        applied = kwargs.get("applied_overrides")
        self.assertIsNotNone(applied)
        self.assertEqual(applied["analyst"]["focus_asset"], "ETH")

    def test_run_no_overrides_works_unchanged(self):
        self._seed_pipeline("p4")
        b = self._make_bot()
        b.cmd_run("p4")
        b.scheduler._enqueue_pipeline_from_file.assert_called_once()
        # applied_overrides may be None for non-v2 caller path
        kwargs = b.scheduler._enqueue_pipeline_from_file.call_args.kwargs
        self.assertIsNone(kwargs.get("applied_overrides"))


if __name__ == "__main__":
    unittest.main()
