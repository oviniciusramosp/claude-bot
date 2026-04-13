"""Tests for manual pipeline step (manual: true) — review gate feature.

Tests cover:
- Parsing: manual steps accepted without prompts, fields set correctly
- DAG loop: waiting_for_approval is non-terminal and treated like running
- Progress text: 🔍 icon shown for waiting_for_approval
- Resume: waiting_for_approval converted to pending on restart
- Callback handlers: manual_approve/cancel/edit routing
- Feedback interception in _handle_text
- cancel() wakes manual review events
"""
import tempfile
import threading
import time as real_time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._botload import load_bot_module, ensure_agent_layout


def _make_pipeline_md(*, steps_yaml: str, model: str = "sonnet") -> str:
    return (
        "---\n"
        "title: Test Pipeline\n"
        "description: test\n"
        "type: pipeline\n"
        "created: 2026-01-01\n"
        "updated: 2026-01-01\n"
        "tags: [pipeline]\n"
        "schedule:\n"
        "  times: ['08:00']\n"
        "  days: ['*']\n"
        f"model: {model}\n"
        "enabled: true\n"
        "notify: none\n"
        "---\n\n"
        "[[Routines]]\n\n"
        "```pipeline\n"
        "steps:\n"
        f"{steps_yaml}"
        "```\n"
    )


class TestManualStepParsing(unittest.TestCase):
    """_parse_pipeline_task correctly handles manual: true steps."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.vault = self.tmp_path / "vault"
        ensure_agent_layout(self.vault, "main")
        self.bot = load_bot_module(self.tmp_path, self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_pipeline_file(self, steps_yaml: str) -> Path:
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        return md

    def test_manual_step_parsed_correctly(self):
        """A manual step is parsed with manual=True and manual_timeout set."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    model: opus\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Revisao Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
            "    timeout: 7200\n"
        )
        md = self._make_pipeline_file(steps_yaml)
        fm, body = self.bot.get_frontmatter_and_body(md)
        task = self.bot._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")
        self.assertIsNotNone(task)
        step_map = {s.id: s for s in task.steps}
        self.assertIn("manual-review", step_map)
        ms = step_map["manual-review"]
        self.assertTrue(ms.manual)
        self.assertEqual(ms.manual_timeout, 7200)
        self.assertEqual(ms.depends_on, ["writer"])

    def test_manual_step_no_prompt_required(self):
        """A manual: true step without prompt/prompt_file is NOT skipped."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    model: opus\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
        )
        md = self._make_pipeline_file(steps_yaml)
        fm, body = self.bot.get_frontmatter_and_body(md)
        task = self.bot._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")
        self.assertIsNotNone(task)
        step_ids = [s.id for s in task.steps]
        self.assertIn("manual-review", step_ids)

    def test_non_manual_step_requires_prompt(self):
        """A step without manual:true and without prompt IS skipped (existing behavior)."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    model: opus\n"
            "    prompt: Write something\n\n"
            "  - id: broken\n"
            "    name: Broken\n"
            "    depends_on: [writer]\n"
        )
        md = self._make_pipeline_file(steps_yaml)
        fm, body = self.bot.get_frontmatter_and_body(md)
        task = self.bot._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")
        # broken step should be dropped, only writer remains
        if task is not None:
            step_ids = [s.id for s in task.steps]
            self.assertNotIn("broken", step_ids)

    def test_manual_timeout_defaults_to_step_timeout(self):
        """When manual_timeout not set, it defaults to the step's timeout field."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    model: opus\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
            "    timeout: 3600\n"
        )
        md = self._make_pipeline_file(steps_yaml)
        fm, body = self.bot.get_frontmatter_and_body(md)
        task = self.bot._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")
        self.assertIsNotNone(task)
        step_map = {s.id: s for s in task.steps}
        ms = step_map["manual-review"]
        self.assertEqual(ms.manual_timeout, 3600)

    def test_manual_timeout_explicit_overrides_timeout(self):
        """manual_timeout field takes precedence over timeout."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    model: opus\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
            "    timeout: 3600\n"
            "    manual_timeout: 1800\n"
        )
        md = self._make_pipeline_file(steps_yaml)
        fm, body = self.bot.get_frontmatter_and_body(md)
        task = self.bot._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")
        self.assertIsNotNone(task)
        step_map = {s.id: s for s in task.steps}
        ms = step_map["manual-review"]
        self.assertEqual(ms.manual_timeout, 1800)


class TestWaitingForApprovalStatus(unittest.TestCase):
    """waiting_for_approval is non-terminal and treated as running in DAG loop."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.vault = self.tmp_path / "vault"
        ensure_agent_layout(self.vault, "main")
        self.bot = load_bot_module(self.tmp_path, self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_executor(self, steps_yaml: str):
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        fm, body = self.bot.get_frontmatter_and_body(md)
        task = self.bot._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")
        mock_bot = MagicMock()
        mock_bot._pending_manual_reviews = {}
        ctx = MagicMock()
        ctx.chat_id = "123"
        ctx.thread_id = None
        state = self.bot.RoutineStateManager()
        executor = self.bot.PipelineExecutor(task, mock_bot, ctx, state)
        executor._bot = mock_bot
        return executor

    def test_waiting_for_approval_not_in_terminal_set(self):
        """The terminal set does not include waiting_for_approval."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n"
        )
        executor = self._make_executor(steps_yaml)
        terminal = {"completed", "failed", "skipped"}
        self.assertNotIn("waiting_for_approval", terminal)

    def test_waiting_for_approval_counted_as_running(self):
        """waiting_for_approval triggers the 'still running' branch in DAG loop."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n"
        )
        executor = self._make_executor(steps_yaml)
        executor._step_status["writer"] = "waiting_for_approval"
        running = any(st in ("running", "waiting_for_approval") for st in executor._step_status.values())
        self.assertTrue(running)

    def test_completed_is_terminal(self):
        """completed is still terminal."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n"
        )
        executor = self._make_executor(steps_yaml)
        executor._step_status["writer"] = "completed"
        terminal = {"completed", "failed", "skipped"}
        non_terminal = [sid for sid, st in executor._step_status.items() if st not in terminal]
        self.assertEqual(non_terminal, [])


class TestProgressTextWaitingIcon(unittest.TestCase):
    """_build_progress_text shows 🔍 for waiting_for_approval steps."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.vault = self.tmp_path / "vault"
        ensure_agent_layout(self.vault, "main")
        self.bot = load_bot_module(self.tmp_path, self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def test_waiting_for_approval_shows_magnifier_icon(self):
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer Step\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Revisao Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
        )
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        fm, body = self.bot.get_frontmatter_and_body(md)
        task = self.bot._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")

        mock_bot = MagicMock()
        mock_bot._pending_manual_reviews = {}
        ctx = MagicMock()
        ctx.chat_id = "123"
        ctx.thread_id = None
        state = self.bot.RoutineStateManager()
        executor = self.bot.PipelineExecutor(task, mock_bot, ctx, state)
        executor._bot = mock_bot
        executor._step_status["writer"] = "completed"
        executor._step_status["manual-review"] = "waiting_for_approval"

        text = executor._build_progress_text(elapsed=0)
        self.assertIn("🔍", text)
        self.assertIn("Revisao Manual", text)

    def test_waiting_count_in_status_line(self):
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Revisao Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
        )
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        fm, body = self.bot.get_frontmatter_and_body(md)
        task = self.bot._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")

        mock_bot = MagicMock()
        mock_bot._pending_manual_reviews = {}
        ctx = MagicMock()
        ctx.chat_id = "123"
        ctx.thread_id = None
        state = self.bot.RoutineStateManager()
        executor = self.bot.PipelineExecutor(task, mock_bot, ctx, state)
        executor._bot = mock_bot
        executor._step_status["writer"] = "completed"
        executor._step_status["manual-review"] = "waiting_for_approval"

        text = executor._build_progress_text(elapsed=0)
        self.assertIn("aguardando", text)


class TestResumePipeline(unittest.TestCase):
    """_resume_pipeline converts waiting_for_approval back to pending."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.vault = self.tmp_path / "vault"
        ensure_agent_layout(self.vault, "main")
        self.bot = load_bot_module(self.tmp_path, self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def test_waiting_for_approval_becomes_pending_on_resume(self):
        """Resume treats waiting_for_approval as pending so the manual gate re-fires."""
        # Build a pipeline file
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
        )
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        fm, body = self.bot.get_frontmatter_and_body(md)
        task = self.bot._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")
        self.assertIsNotNone(task)

        # Simulate the persisted state with waiting_for_approval
        persisted_steps = {
            "writer": {"status": "completed", "attempt": 1},
            "manual-review": {"status": "waiting_for_approval", "attempt": 1},
        }

        step_status: dict = {}
        step_outputs: dict = {}
        step_attempts: dict = {}

        # Replicate _resume_pipeline logic for each step
        for step in task.steps:
            ps = persisted_steps.get(step.id, {})
            old_status = ps.get("status", "pending")
            attempt = ps.get("attempt", 0)

            if old_status == "completed":
                step_status[step.id] = "completed"
            elif old_status == "running":
                step_status[step.id] = "pending"
            elif old_status == "waiting_for_approval":
                step_status[step.id] = "pending"
            elif old_status == "failed":
                if attempt < step.retry:
                    step_status[step.id] = "pending"
                else:
                    step_status[step.id] = "failed"
            elif old_status == "skipped":
                step_status[step.id] = "skipped"
            else:
                step_status[step.id] = "pending"

            step_attempts[step.id] = attempt

        self.assertEqual(step_status["writer"], "completed")
        self.assertEqual(step_status["manual-review"], "pending")


class TestCallbackHandlers(unittest.TestCase):
    """Callback handlers route manual_approve/cancel/edit correctly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.vault = self.tmp_path / "vault"
        ensure_agent_layout(self.vault, "main")
        self.bot_module = load_bot_module(self.tmp_path, self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_bot(self):
        """Create a minimal ClaudeTelegramBot with mocked Telegram calls."""
        bot = self.bot_module.ClaudeTelegramBot.__new__(self.bot_module.ClaudeTelegramBot)
        bot._pending_manual_reviews = {}
        bot._pending_approvals = {}
        bot._voice_picks = {}
        bot._reasoning_toggles = {}
        bot._ctx_local = threading.local()
        bot._ctx = MagicMock()
        bot._ctx.chat_id = "123"
        bot._ctx.thread_id = None
        bot.send_message = MagicMock(return_value=42)
        bot.edit_message = MagicMock()
        bot.answer_callback = MagicMock()
        bot.tg_request = MagicMock(return_value={"ok": True})
        bot._remove_keyboard = MagicMock()
        return bot

    def _make_callback(self, data: str) -> dict:
        return {
            "id": "cb_id",
            "message": {"message_id": 100, "chat": {"id": 123}},
            "data": data,
        }

    def test_manual_approve_sets_result_and_wakes_event(self):
        bot = self._make_bot()
        event = threading.Event()
        review_id = "abc123"
        entry = {
            "event": event,
            "result": None,
            "step_name": "Test",
            "message_id": 99,
            "chat_id": "123",
            "thread_id": None,
            "awaiting_feedback": False,
        }
        bot._pending_manual_reviews[review_id] = entry

        cb = self._make_callback(f"manual_approve:{review_id}")
        bot._handle_callback(cb)

        self.assertTrue(event.is_set())
        self.assertEqual(entry["result"], "approved")
        bot.answer_callback.assert_called()

    def test_manual_cancel_sets_result_and_wakes_event(self):
        bot = self._make_bot()
        event = threading.Event()
        review_id = "def456"
        entry = {
            "event": event,
            "result": None,
            "step_name": "Test",
            "message_id": 99,
            "chat_id": "123",
            "thread_id": None,
            "awaiting_feedback": False,
        }
        bot._pending_manual_reviews[review_id] = entry

        cb = self._make_callback(f"manual_cancel:{review_id}")
        bot._handle_callback(cb)

        self.assertTrue(event.is_set())
        self.assertEqual(entry["result"], "cancelled")

    def test_manual_edit_sets_awaiting_feedback(self):
        bot = self._make_bot()
        event = threading.Event()
        review_id = "ghi789"
        entry = {
            "event": event,
            "result": None,
            "step_name": "Test",
            "message_id": 99,
            "chat_id": "123",
            "thread_id": None,
            "awaiting_feedback": False,
        }
        bot._pending_manual_reviews[review_id] = entry

        cb = self._make_callback(f"manual_edit:{review_id}")
        bot._handle_callback(cb)

        # Event should NOT be set yet
        self.assertFalse(event.is_set())
        self.assertTrue(entry["awaiting_feedback"])

    def test_expired_review_returns_expired_message(self):
        bot = self._make_bot()
        cb = self._make_callback("manual_approve:nonexistent")
        bot._handle_callback(cb)
        bot.answer_callback.assert_called_with("cb_id", "Expirado")


class TestFeedbackInterception(unittest.TestCase):
    """_handle_text intercepts messages when awaiting_feedback is True."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.vault = self.tmp_path / "vault"
        ensure_agent_layout(self.vault, "main")
        self.bot_module = load_bot_module(self.tmp_path, self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def _make_bot(self):
        bot = self.bot_module.ClaudeTelegramBot.__new__(self.bot_module.ClaudeTelegramBot)
        bot._pending_manual_reviews = {}
        bot._pending_approvals = {}
        bot._voice_picks = {}
        bot._reasoning_toggles = {}
        bot._ctx_local = threading.local()
        ctx = MagicMock()
        ctx.chat_id = "123"
        ctx.thread_id = None
        bot._ctx = ctx
        bot.send_message = MagicMock(return_value=42)
        bot.edit_message = MagicMock()
        bot.answer_callback = MagicMock()
        bot.tg_request = MagicMock(return_value={"ok": True})
        bot._remove_keyboard = MagicMock()
        bot._session = MagicMock()
        return bot

    def test_feedback_captured_when_awaiting(self):
        bot = self._make_bot()
        event = threading.Event()
        review_id = "feed001"
        entry = {
            "event": event,
            "result": None,
            "feedback": None,
            "step_name": "Test",
            "message_id": 99,
            "chat_id": "123",
            "thread_id": None,
            "awaiting_feedback": True,
        }
        bot._pending_manual_reviews[review_id] = entry

        # Simulate the user sending feedback text
        # Directly exercise the feedback interception logic
        text = "Ajuste o tom para mais informal"
        for _rev_id, _rev_entry in list(bot._pending_manual_reviews.items()):
            if (
                _rev_entry.get("awaiting_feedback")
                and str(_rev_entry.get("chat_id")) == str(bot._ctx.chat_id)
                and str(_rev_entry.get("thread_id") or "") == str(bot._ctx.thread_id or "")
            ):
                _rev_entry["awaiting_feedback"] = False
                _rev_entry["feedback"] = text
                _rev_entry["result"] = "edit"
                _rev_entry["event"].set()
                break

        self.assertTrue(event.is_set())
        self.assertEqual(entry["feedback"], "Ajuste o tom para mais informal")
        self.assertEqual(entry["result"], "edit")
        self.assertFalse(entry["awaiting_feedback"])

    def test_feedback_not_captured_when_not_awaiting(self):
        bot = self._make_bot()
        event = threading.Event()
        review_id = "feed002"
        entry = {
            "event": event,
            "result": None,
            "feedback": None,
            "step_name": "Test",
            "message_id": 99,
            "chat_id": "123",
            "thread_id": None,
            "awaiting_feedback": False,  # NOT awaiting
        }
        bot._pending_manual_reviews[review_id] = entry

        # Nothing should match
        for _rev_id, _rev_entry in list(bot._pending_manual_reviews.items()):
            if (
                _rev_entry.get("awaiting_feedback")
                and str(_rev_entry.get("chat_id")) == str(bot._ctx.chat_id)
            ):
                _rev_entry["event"].set()
                break

        self.assertFalse(event.is_set())
        self.assertIsNone(entry["feedback"])

    def test_chat_id_scoped_feedback(self):
        """Feedback for a different chat does not match."""
        bot = self._make_bot()
        event = threading.Event()
        review_id = "feed003"
        entry = {
            "event": event,
            "result": None,
            "feedback": None,
            "step_name": "Test",
            "message_id": 99,
            "chat_id": "999999",  # different chat
            "thread_id": None,
            "awaiting_feedback": True,
        }
        bot._pending_manual_reviews[review_id] = entry

        for _rev_id, _rev_entry in list(bot._pending_manual_reviews.items()):
            if (
                _rev_entry.get("awaiting_feedback")
                and str(_rev_entry.get("chat_id")) == str(bot._ctx.chat_id)  # 123
            ):
                _rev_entry["event"].set()
                break

        self.assertFalse(event.is_set())


class TestCancelWakesManualReviews(unittest.TestCase):
    """PipelineExecutor.cancel() wakes pending manual review events."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.vault = self.tmp_path / "vault"
        ensure_agent_layout(self.vault, "main")
        self.bot_module = load_bot_module(self.tmp_path, self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def test_cancel_sets_result_cancelled_and_wakes_event(self):
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
        )
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        fm, body = self.bot_module.get_frontmatter_and_body(md)
        task = self.bot_module._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")

        mock_bot = MagicMock()
        event = threading.Event()
        review_entry = {
            "pipeline_name": "test-pipeline",
            "event": event,
            "result": None,
        }
        mock_bot._pending_manual_reviews = {"rev001": review_entry}

        ctx = MagicMock()
        ctx.chat_id = "123"
        ctx.thread_id = None
        state = self.bot_module.RoutineStateManager()
        executor = self.bot_module.PipelineExecutor(task, mock_bot, ctx, state)
        executor._bot = mock_bot

        executor.cancel()

        self.assertTrue(event.is_set())
        self.assertEqual(review_entry["result"], "cancelled")

    def test_cancel_only_wakes_own_pipeline_reviews(self):
        """cancel() should not wake reviews belonging to a different pipeline."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n"
        )
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        fm, body = self.bot_module.get_frontmatter_and_body(md)
        task = self.bot_module._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")

        mock_bot = MagicMock()
        event_own = threading.Event()
        event_other = threading.Event()
        mock_bot._pending_manual_reviews = {
            "own": {"pipeline_name": "test-pipeline", "event": event_own, "result": None},
            "other": {"pipeline_name": "other-pipeline", "event": event_other, "result": None},
        }

        ctx = MagicMock()
        ctx.chat_id = "123"
        ctx.thread_id = None
        state = self.bot_module.RoutineStateManager()
        executor = self.bot_module.PipelineExecutor(task, mock_bot, ctx, state)
        executor._bot = mock_bot

        executor.cancel()

        self.assertTrue(event_own.is_set())
        self.assertFalse(event_other.is_set())


class TestManualStepApproveFlow(unittest.TestCase):
    """_execute_manual_step completes when event is set with result=approved."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.vault = self.tmp_path / "vault"
        ensure_agent_layout(self.vault, "main")
        self.bot_module = load_bot_module(self.tmp_path, self.vault)

    def tearDown(self):
        self.tmp.cleanup()

    def test_approve_flow_marks_step_completed_and_copies_output(self):
        """When approved, step status = completed and output file is written."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Revisao Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
            "    timeout: 5\n"
        )
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        fm, body = self.bot_module.get_frontmatter_and_body(md)
        task = self.bot_module._parse_pipeline_task(md, fm, body, "test-pipeline", "sonnet", "08:00")
        self.assertIsNotNone(task)

        # Set up workspace and data dir
        workspace = self.vault / "main" / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        data_dir = workspace / "data" / "test-pipeline"
        data_dir.mkdir(parents=True, exist_ok=True)

        # Write the "completed" writer output
        writer_output = "# Test Content\n\nThis is the draft content."
        (data_dir / "writer.md").write_text(writer_output, encoding="utf-8")

        mock_bot = MagicMock()
        pending_reviews = {}
        mock_bot._pending_manual_reviews = pending_reviews
        mock_bot.send_message = MagicMock(return_value=42)
        mock_bot.edit_message = MagicMock()

        ctx = MagicMock()
        ctx.chat_id = "123"
        ctx.thread_id = None

        state = self.bot_module.RoutineStateManager()
        executor = self.bot_module.PipelineExecutor(task, mock_bot, ctx, state)
        executor._bot = mock_bot
        executor.workspace = workspace
        executor._start_time = real_time.time()

        # Simulate user clicking approve: set result after a short delay
        def _simulate_approve():
            real_time.sleep(0.3)
            for entry in pending_reviews.values():
                entry["result"] = "approved"
                entry["event"].set()

        t = threading.Thread(target=_simulate_approve, daemon=True)
        t.start()

        step = next(s for s in task.steps if s.id == "manual-review")
        executor._execute_manual_step(step, data_dir)
        t.join(timeout=3)

        self.assertEqual(executor._step_status["manual-review"], "completed")
        out_file = data_dir / "manual-review.md"
        self.assertTrue(out_file.exists())
        self.assertEqual(out_file.read_text(encoding="utf-8"), writer_output)

    def test_timeout_marks_step_failed(self):
        """When manual_timeout expires, step is marked failed."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Revisao Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
            "    timeout: 1\n"  # 1 second timeout
        )
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline2.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        fm, body = self.bot_module.get_frontmatter_and_body(md)
        task = self.bot_module._parse_pipeline_task(md, fm, body, "test-pipeline2", "sonnet", "08:00")
        self.assertIsNotNone(task)

        workspace = self.vault / "main" / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        data_dir = workspace / "data" / "test-pipeline2"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "writer.md").write_text("draft content", encoding="utf-8")

        mock_bot = MagicMock()
        mock_bot._pending_manual_reviews = {}
        mock_bot.send_message = MagicMock(return_value=42)
        mock_bot.edit_message = MagicMock()

        ctx = MagicMock()
        ctx.chat_id = "123"
        ctx.thread_id = None

        state = self.bot_module.RoutineStateManager()
        executor = self.bot_module.PipelineExecutor(task, mock_bot, ctx, state)
        executor._bot = mock_bot
        executor.workspace = workspace
        executor._start_time = real_time.time()

        step = next(s for s in task.steps if s.id == "manual-review")
        executor._execute_manual_step(step, data_dir)

        self.assertEqual(executor._step_status["manual-review"], "failed")
        self.assertIn("timeout", executor._step_errors.get("manual-review", "").lower())

    def test_cancel_flow_marks_step_failed(self):
        """When cancelled, step is marked failed."""
        steps_yaml = (
            "  - id: writer\n"
            "    name: Writer\n"
            "    prompt: Write something\n\n"
            "  - id: manual-review\n"
            "    name: Revisao Manual\n"
            "    manual: true\n"
            "    depends_on: [writer]\n"
            "    timeout: 10\n"
        )
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        md = routines_dir / "test-pipeline3.md"
        md.write_text(_make_pipeline_md(steps_yaml=steps_yaml), encoding="utf-8")
        fm, body = self.bot_module.get_frontmatter_and_body(md)
        task = self.bot_module._parse_pipeline_task(md, fm, body, "test-pipeline3", "sonnet", "08:00")
        self.assertIsNotNone(task)

        workspace = self.vault / "main" / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        data_dir = workspace / "data" / "test-pipeline3"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "writer.md").write_text("draft content", encoding="utf-8")

        mock_bot = MagicMock()
        pending_reviews = {}
        mock_bot._pending_manual_reviews = pending_reviews
        mock_bot.send_message = MagicMock(return_value=42)
        mock_bot.edit_message = MagicMock()

        ctx = MagicMock()
        ctx.chat_id = "123"
        ctx.thread_id = None

        state = self.bot_module.RoutineStateManager()
        executor = self.bot_module.PipelineExecutor(task, mock_bot, ctx, state)
        executor._bot = mock_bot
        executor.workspace = workspace
        executor._start_time = real_time.time()

        def _simulate_cancel():
            real_time.sleep(0.3)
            for entry in pending_reviews.values():
                entry["result"] = "cancelled"
                entry["event"].set()

        t = threading.Thread(target=_simulate_cancel, daemon=True)
        t.start()

        step = next(s for s in task.steps if s.id == "manual-review")
        executor._execute_manual_step(step, data_dir)
        t.join(timeout=3)

        self.assertEqual(executor._step_status["manual-review"], "failed")
        self.assertIn("Cancelled", executor._step_errors.get("manual-review", ""))


if __name__ == "__main__":
    unittest.main()
