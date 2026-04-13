"""Tests for the restart-resilience system: ActiveMessageRegistry, pipeline/routine
resumption, and orphaned-message cleanup."""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tests._botload import load_bot_module


class ActiveMessageRegistryTests(unittest.TestCase):
    """Tests for the ActiveMessageRegistry class."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)

    def tearDown(self):
        self._td.cleanup()

    def test_register_and_get_all(self):
        reg = self.bot.ActiveMessageRegistry()
        reg.register(123, "456", None, "stream", "interactive")
        reg.register(789, "-100999", 42, "progress", "pipeline:foo")
        msgs = reg.get_all()
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["msg_id"], 123)
        self.assertEqual(msgs[0]["chat_id"], "456")
        self.assertIsNone(msgs[0]["thread_id"])
        self.assertEqual(msgs[0]["type"], "stream")
        self.assertEqual(msgs[0]["source"], "interactive")
        self.assertEqual(msgs[1]["msg_id"], 789)
        self.assertEqual(msgs[1]["thread_id"], 42)
        self.assertEqual(msgs[1]["source"], "pipeline:foo")

    def test_unregister_removes_entry(self):
        reg = self.bot.ActiveMessageRegistry()
        reg.register(100, "456", None, "stream", "interactive")
        reg.register(200, "456", None, "progress", "routine:bar")
        reg.unregister(100)
        msgs = reg.get_all()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["msg_id"], 200)

    def test_unregister_nonexistent_is_noop(self):
        reg = self.bot.ActiveMessageRegistry()
        reg.register(100, "456", None, "stream", "interactive")
        reg.unregister(999)  # doesn't exist
        self.assertEqual(len(reg.get_all()), 1)

    def test_clear_empties_all(self):
        reg = self.bot.ActiveMessageRegistry()
        reg.register(100, "456", None, "stream", "interactive")
        reg.register(200, "456", None, "stream", "interactive")
        reg.clear()
        self.assertEqual(len(reg.get_all()), 0)

    def test_persists_to_disk(self):
        reg = self.bot.ActiveMessageRegistry()
        reg.register(100, "456", None, "stream", "interactive")
        # Create a new instance — should read from disk
        reg2 = self.bot.ActiveMessageRegistry()
        msgs = reg2.get_all()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["msg_id"], 100)

    def test_empty_file_returns_empty_list(self):
        reg = self.bot.ActiveMessageRegistry()
        self.assertEqual(reg.get_all(), [])

    def test_corrupt_file_returns_empty_list(self):
        reg = self.bot.ActiveMessageRegistry()
        reg._path.parent.mkdir(parents=True, exist_ok=True)
        reg._path.write_text("not json", encoding="utf-8")
        self.assertEqual(reg.get_all(), [])


class CollectInterruptedTasksTests(unittest.TestCase):
    """Tests for RoutineStateManager._collect_interrupted_tasks."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)

    def tearDown(self):
        self._td.cleanup()

    def test_empty_state_returns_empty(self):
        sm = self.bot.RoutineStateManager()
        pipelines, routines = sm._collect_interrupted_tasks()
        self.assertEqual(pipelines, [])
        self.assertEqual(routines, [])

    def test_collects_running_routine(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("my-routine", "08:00", "running",
                      agent="main", source_file="main/Routines/my-routine.md")
        pipelines, routines = sm._collect_interrupted_tasks()
        self.assertEqual(len(routines), 1)
        self.assertEqual(routines[0]["name"], "my-routine")
        self.assertEqual(routines[0]["agent"], "main")
        self.assertEqual(routines[0]["source_file"], "main/Routines/my-routine.md")
        self.assertEqual(len(pipelines), 0)

    def test_collects_running_pipeline_with_steps(self):
        sm = self.bot.RoutineStateManager()
        sm.set_pipeline_status("my-pipe", "10:00", "running",
                               steps_init=[{"id": "s1", "output_type": "file"},
                                           {"id": "s2", "output_type": "telegram"}],
                               agent="crypto-bro",
                               source_file="crypto-bro/Routines/my-pipe.md")
        # Mark s1 as completed
        sm.set_step_status("my-pipe", "10:00", "s1", "completed")
        pipelines, routines = sm._collect_interrupted_tasks()
        self.assertEqual(len(pipelines), 1)
        self.assertEqual(pipelines[0]["name"], "my-pipe")
        self.assertEqual(pipelines[0]["steps"]["s1"]["status"], "completed")
        self.assertEqual(pipelines[0]["steps"]["s2"]["status"], "pending")
        self.assertEqual(len(routines), 0)

    def test_ignores_completed_entries(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("done", "08:00", "running")
        sm.set_status("done", "08:00", "completed")
        pipelines, routines = sm._collect_interrupted_tasks()
        self.assertEqual(len(pipelines), 0)
        self.assertEqual(len(routines), 0)

    def test_ignores_failed_entries(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("bad", "08:00", "running")
        sm.set_status("bad", "08:00", "failed", error="something broke")
        pipelines, routines = sm._collect_interrupted_tasks()
        self.assertEqual(len(pipelines), 0)
        self.assertEqual(len(routines), 0)

    def test_does_not_mutate_state(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("r1", "08:00", "running")
        sm._collect_interrupted_tasks()
        # State should still be "running"
        data = sm.get_today_state()
        self.assertEqual(data["r1"]["08:00"]["status"], "running")

    def test_cross_day_recovery(self):
        """Checks yesterday's state file for crash-at-midnight edge case."""
        sm = self.bot.RoutineStateManager()
        yesterday = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
        yesterday_file = self.bot.ROUTINES_STATE_DIR / f"{yesterday}.json"
        yesterday_file.write_text(json.dumps({
            "late-routine": {"23:59": {"status": "running", "agent": "main"}}
        }), encoding="utf-8")
        pipelines, routines = sm._collect_interrupted_tasks()
        self.assertEqual(len(routines), 1)
        self.assertEqual(routines[0]["name"], "late-routine")
        self.assertEqual(routines[0]["day"], yesterday)


class FindRoutineFileTests(unittest.TestCase):
    """Tests for the _find_routine_file standalone function."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)
        self.vault = self.bot.VAULT_DIR
        # Create a routine file
        routines_dir = self.vault / "main" / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        (routines_dir / "test-routine.md").write_text("---\ntitle: Test\n---\nbody\n")
        # agent-info so main counts as an agent
        (self.vault / "main" / "agent-info.md").write_text("---\nname: Main\n---\n")

    def tearDown(self):
        self._td.cleanup()

    def test_finds_by_source_file_hint(self):
        result = self.bot._find_routine_file("test-routine", "main/Routines/test-routine.md")
        self.assertIsNotNone(result)
        self.assertEqual(result.stem, "test-routine")

    def test_finds_by_name_fallback(self):
        result = self.bot._find_routine_file("test-routine")
        self.assertIsNotNone(result)
        self.assertEqual(result.stem, "test-routine")

    def test_returns_none_for_missing(self):
        result = self.bot._find_routine_file("nonexistent")
        self.assertIsNone(result)


class ParsePipelineTaskTests(unittest.TestCase):
    """Tests for the _parse_pipeline_task standalone function."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)
        self.vault = self.bot.VAULT_DIR
        (self.vault / "main").mkdir(parents=True, exist_ok=True)
        (self.vault / "main" / "agent-info.md").write_text("---\nname: Main\n---\n")

    def tearDown(self):
        self._td.cleanup()

    def test_parses_simple_pipeline(self):
        md_file = self.vault / "main" / "Routines" / "test-pipe.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        fm = {"title": "Test Pipeline", "type": "pipeline", "model": "sonnet",
              "notify": "final", "enabled": True}
        body = """```pipeline
- id: step1
  prompt: Do step 1
- id: step2
  depends_on: step1
  prompt: Do step 2
```"""
        task = self.bot._parse_pipeline_task(md_file, fm, body, "test-pipe", "sonnet", "10:00")
        self.assertIsNotNone(task)
        self.assertEqual(task.name, "test-pipe")
        self.assertEqual(len(task.steps), 2)
        self.assertEqual(task.steps[0].id, "step1")
        self.assertEqual(task.steps[1].id, "step2")
        self.assertEqual(task.steps[1].depends_on, ["step1"])

    def test_returns_none_for_empty_body(self):
        md_file = self.vault / "main" / "Routines" / "empty.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        task = self.bot._parse_pipeline_task(md_file, {}, "no pipeline block here", "empty", "sonnet", "10:00")
        self.assertIsNone(task)

    def test_detects_cycles(self):
        md_file = self.vault / "main" / "Routines" / "cycle.md"
        md_file.parent.mkdir(parents=True, exist_ok=True)
        body = """```pipeline
- id: a
  depends_on: b
  prompt: step a
- id: b
  depends_on: a
  prompt: step b
```"""
        task = self.bot._parse_pipeline_task(md_file, {"title": "Cycle"}, body, "cycle", "sonnet", "10:00")
        self.assertIsNone(task)


class PipelineExecutorResumeTests(unittest.TestCase):
    """Tests for PipelineExecutor with resume_state."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)

    def tearDown(self):
        self._td.cleanup()

    def test_resume_state_pre_seeds_step_status(self):
        PipelineStep = self.bot.PipelineStep
        PipelineTask = self.bot.PipelineTask
        step1 = PipelineStep(id="s1", name="S1", model="sonnet", prompt="do 1")
        step2 = PipelineStep(id="s2", name="S2", model="sonnet", prompt="do 2", depends_on=["s1"])

        task = PipelineTask(name="test", title="Test", steps=[step1, step2],
                            model="sonnet", time_slot="10:00", agent="main")

        resume = {
            "step_status": {"s1": "completed", "s2": "pending"},
            "step_outputs": {"s1": "output of s1"},
            "step_attempts": {"s1": 1, "s2": 0},
        }

        mock_bot = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.chat_id = "123"
        mock_ctx.thread_id = None
        mock_state = MagicMock()

        executor = self.bot.PipelineExecutor(task, mock_bot, mock_ctx, mock_state,
                                              resume_state=resume)
        self.assertTrue(executor._resumed)
        self.assertEqual(executor._step_status["s1"], "completed")
        self.assertEqual(executor._step_status["s2"], "pending")
        self.assertEqual(executor._step_outputs["s1"], "output of s1")
        self.assertEqual(executor._step_attempts["s1"], 1)

    def test_no_resume_state_defaults(self):
        PipelineStep = self.bot.PipelineStep
        PipelineTask = self.bot.PipelineTask
        step1 = PipelineStep(id="s1", name="S1", model="sonnet", prompt="do 1")

        task = PipelineTask(name="test", title="Test", steps=[step1],
                            model="sonnet", time_slot="10:00", agent="main")

        mock_bot = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.chat_id = "123"
        mock_ctx.thread_id = None
        mock_state = MagicMock()

        executor = self.bot.PipelineExecutor(task, mock_bot, mock_ctx, mock_state)
        self.assertFalse(executor._resumed)
        self.assertEqual(executor._step_status["s1"], "pending")
        self.assertEqual(executor._step_outputs, {})


if __name__ == "__main__":
    unittest.main()
