"""Unit tests for RoutineStateManager (per-day routine execution state)."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from tests._botload import load_bot_module


class RoutineStateManagerBasic(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)

    def tearDown(self):
        self._td.cleanup()

    def test_set_running_then_completed(self):
        sm = self.bot.RoutineStateManager()
        self.assertFalse(sm.is_executed("foo", "08:00"))
        sm.set_status("foo", "08:00", "running")
        self.assertTrue(sm.is_executed("foo", "08:00"))
        sm.set_status("foo", "08:00", "completed")
        state = sm.get_today_state()
        self.assertEqual(state["foo"]["08:00"]["status"], "completed")
        self.assertIn("started_at", state["foo"]["08:00"])
        self.assertIn("finished_at", state["foo"]["08:00"])

    def test_failed_status_records_error(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("foo", "12:00", "running")
        sm.set_status("foo", "12:00", "failed", error="boom")
        state = sm.get_today_state()
        self.assertEqual(state["foo"]["12:00"]["status"], "failed")
        self.assertEqual(state["foo"]["12:00"]["error"], "boom")

    def test_is_executed_for_unknown_returns_false(self):
        sm = self.bot.RoutineStateManager()
        self.assertFalse(sm.is_executed("nope", "00:00"))

    def test_pipeline_steps_init(self):
        sm = self.bot.RoutineStateManager()
        sm.set_pipeline_status(
            "p1", "08:00", "running",
            steps_init=[
                {"id": "collect", "output_type": "file"},
                {"id": "analyze", "output_type": "telegram"},
            ],
        )
        steps = sm.get_pipeline_steps("p1", "08:00")
        self.assertEqual(set(steps.keys()), {"collect", "analyze"})
        self.assertEqual(steps["collect"]["status"], "pending")
        self.assertEqual(steps["analyze"]["output_type"], "telegram")

    def test_set_step_status_updates_only_target_step(self):
        sm = self.bot.RoutineStateManager()
        sm.set_pipeline_status("p1", "08:00", "running", steps_init=["a", "b"])
        sm.set_step_status("p1", "08:00", "a", "completed")
        steps = sm.get_pipeline_steps("p1", "08:00")
        self.assertEqual(steps["a"]["status"], "completed")
        self.assertEqual(steps["b"]["status"], "pending")

    def test_collect_interrupted_tasks(self):
        """_collect_interrupted_tasks returns running entries without mutating state."""
        state_file = self.bot.ROUTINES_STATE_DIR / f"{time.strftime('%Y-%m-%d')}.json"
        self.bot.ROUTINES_STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({
            "foo": {"08:00": {"status": "running", "started_at": "2026-04-10T08:00:00",
                              "agent": "main", "source_file": "main/Routines/foo.md"}},
            "bar": {
                "10:00": {
                    "type": "pipeline",
                    "status": "running",
                    "agent": "crypto-bro",
                    "source_file": "crypto-bro/Routines/bar.md",
                    "steps": {
                        "s1": {"status": "completed"},
                        "s2": {"status": "running"},
                        "s3": {"status": "pending"},
                    }
                }
            },
            "done": {"09:00": {"status": "completed"}},
        }))
        sm = self.bot.RoutineStateManager()
        pipelines, routines = sm._collect_interrupted_tasks()
        # State file should NOT be mutated
        data = json.loads(state_file.read_text())
        self.assertEqual(data["foo"]["08:00"]["status"], "running")
        self.assertEqual(data["bar"]["10:00"]["status"], "running")
        # Should find 1 pipeline and 1 routine
        self.assertEqual(len(pipelines), 1)
        self.assertEqual(len(routines), 1)
        self.assertEqual(pipelines[0]["name"], "bar")
        self.assertEqual(pipelines[0]["agent"], "crypto-bro")
        self.assertEqual(pipelines[0]["steps"]["s1"]["status"], "completed")
        self.assertEqual(routines[0]["name"], "foo")
        self.assertEqual(routines[0]["agent"], "main")

    def test_mark_interrupted_as_failed(self):
        """mark_interrupted_as_failed marks running entries as failed."""
        sm = self.bot.RoutineStateManager()
        sm.set_status("r1", "08:00", "running")
        sm.mark_interrupted_as_failed("r1", "08:00", is_pipeline=False)
        data = sm.get_today_state()
        self.assertEqual(data["r1"]["08:00"]["status"], "failed")
        self.assertIn("Bot restarted", data["r1"]["08:00"]["error"])

    def test_set_status_persists_agent_and_source_file(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("r1", "08:00", "running", agent="main", source_file="main/Routines/r1.md")
        data = sm.get_today_state()
        self.assertEqual(data["r1"]["08:00"]["agent"], "main")
        self.assertEqual(data["r1"]["08:00"]["source_file"], "main/Routines/r1.md")

    def test_concurrent_writes_dont_lose_data(self):
        # Even though we're not really threading, exercise the lock path
        sm = self.bot.RoutineStateManager()
        for i in range(20):
            sm.set_status(f"r{i}", "08:00", "completed")
        state = sm.get_today_state()
        for i in range(20):
            self.assertEqual(state[f"r{i}"]["08:00"]["status"], "completed")


class HistoryRollupTest(unittest.TestCase):
    """Verify that completed/failed/cancelled status transitions append to
    the monthly history rollup at Agents/<owner>/Routines/.history/YYYY-MM.md."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.home = self.tmp / "home"
        self.vault = self.tmp / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        # Seed a routine file so the rollup can pick up frontmatter.
        # The routine lives under Main — `_find_routine_file` will resolve it.
        routines_dir = self.bot.ROUTINES_DIR  # test shim = Agents/main/Routines
        routines_dir.mkdir(parents=True, exist_ok=True)
        (routines_dir / "alpha.md").write_text(
            """---
title: "Alpha"
description: "Test routine"
type: routine
created: 2026-04-11
updated: 2026-04-11
tags: [routine]
schedule:
  times: ["09:00"]
  days: ["*"]
model: sonnet
agent: main
enabled: true
---

Body.
""",
            encoding="utf-8",
        )
        # ensure_agent_layout() already wrote the agent-info.md that
        # iter_agent_ids() looks for — no extra setup needed.

    def tearDown(self):
        self._td.cleanup()

    def _history_path(self) -> Path:
        month = time.strftime("%Y-%m")
        return self.vault / "main" / "Routines" / ".history" / f"{month}.md"

    def test_completed_status_appends_record(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("alpha", "09:00", "running")
        self.assertFalse(self._history_path().exists())
        sm.set_status("alpha", "09:00", "completed")
        self.assertTrue(self._history_path().exists())
        text = self._history_path().read_text()
        self.assertIn("type: history", text)
        self.assertIn("## ", text)  # has at least one record header
        self.assertIn("alpha", text)
        self.assertIn("status: completed", text)
        self.assertIn("model: sonnet", text)
        self.assertIn("agent: main", text)

    def test_failed_status_includes_error(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("alpha", "10:00", "failed", error="boom\nwith newline")
        text = self._history_path().read_text()
        self.assertIn("status: failed", text)
        self.assertIn("error: boom with newline", text)

    def test_cancelled_status_recorded(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("alpha", "11:00", "cancelled")
        text = self._history_path().read_text()
        self.assertIn("status: cancelled", text)

    def test_running_status_does_not_write_history(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("alpha", "12:00", "running")
        self.assertFalse(self._history_path().exists())

    def test_pipeline_completed_appends_record(self):
        sm = self.bot.RoutineStateManager()
        sm.set_pipeline_status("alpha", "09:00", "running", steps_init=["s1"])
        self.assertFalse(self._history_path().exists())
        sm.set_pipeline_status("alpha", "09:00", "completed")
        text = self._history_path().read_text()
        self.assertIn("kind: pipeline", text)
        self.assertIn("status: completed", text)

    def test_multiple_records_appended(self):
        sm = self.bot.RoutineStateManager()
        sm.set_status("alpha", "09:00", "completed")
        sm.set_status("alpha", "10:00", "completed")
        sm.set_status("alpha", "11:00", "failed", error="x")
        text = self._history_path().read_text()
        # 3 records, 1 frontmatter block
        self.assertEqual(text.count("\n## "), 3)
        self.assertEqual(text.count("type: history"), 1)

    def test_history_file_is_queryable(self):
        """The rollup file must be a valid vault node so vault_query.find()
        can return it as type=history."""
        import sys as _sys
        _sys.path.insert(0, str(Path(self.bot.__file__).resolve().parent / "scripts"))
        from vault_query import load_vault

        sm = self.bot.RoutineStateManager()
        sm.set_status("alpha", "09:00", "completed")
        vi = load_vault(self.vault)
        history_files = vi.find(type="history")
        self.assertEqual(len(history_files), 1)
        self.assertEqual(history_files[0].type, "history")


if __name__ == "__main__":
    unittest.main()
