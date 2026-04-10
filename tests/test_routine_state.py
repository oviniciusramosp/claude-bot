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

    def test_cleanup_stale_running_on_init(self):
        # Pre-write a state file with a "running" entry
        state_file = self.bot.ROUTINES_STATE_DIR / f"{time.strftime('%Y-%m-%d')}.json"
        self.bot.ROUTINES_STATE_DIR.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({
            "foo": {"08:00": {"status": "running", "started_at": "2026-04-10T08:00:00"}},
            "bar": {
                "10:00": {
                    "type": "pipeline",
                    "status": "running",
                    "steps": {
                        "s1": {"status": "running"},
                        "s2": {"status": "pending"},
                    }
                }
            }
        }))
        # Constructing RoutineStateManager should mark stale "running" as "failed"
        self.bot.RoutineStateManager()
        data = json.loads(state_file.read_text())
        self.assertEqual(data["foo"]["08:00"]["status"], "failed")
        self.assertIn("Bot restarted", data["foo"]["08:00"]["error"])
        # Pipeline-level + nested step
        self.assertEqual(data["bar"]["10:00"]["status"], "failed")
        self.assertEqual(data["bar"]["10:00"]["steps"]["s1"]["status"], "failed")
        # Pending step untouched
        self.assertEqual(data["bar"]["10:00"]["steps"]["s2"]["status"], "pending")

    def test_concurrent_writes_dont_lose_data(self):
        # Even though we're not really threading, exercise the lock path
        sm = self.bot.RoutineStateManager()
        for i in range(20):
            sm.set_status(f"r{i}", "08:00", "completed")
        state = sm.get_today_state()
        for i in range(20):
            self.assertEqual(state[f"r{i}"]["08:00"]["status"], "completed")


if __name__ == "__main__":
    unittest.main()
