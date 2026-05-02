"""Tests for PipelineDisplayStatus + compute_display_status (Commit 7).

Validates the single-source-of-truth display enum that Swift/JS dashboards
mirror in Phase 2. Also exercises the additive routines-state JSON fields
(publish_emitted, display_status) on RoutineStateManager.set_pipeline_status.
"""

import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _botload import load_bot_module


class PipelineDisplayStatusEnumTests(unittest.TestCase):
    """Enum values are stable strings — Swift+JS rely on these literals."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pds-enum-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)

    def test_enum_values_are_capitalized_strings(self):
        """Spec § 5.2: enum values are exactly capitalized strings for direct UI rendering."""
        self.assertEqual(self.bot.PipelineDisplayStatus.IDLE.value, "Idle")
        self.assertEqual(self.bot.PipelineDisplayStatus.SCHEDULED.value, "Scheduled")
        self.assertEqual(self.bot.PipelineDisplayStatus.RUNNING.value, "Running")
        self.assertEqual(self.bot.PipelineDisplayStatus.SUCCESS.value, "Success")
        self.assertEqual(self.bot.PipelineDisplayStatus.FAILED.value, "Failed")
        self.assertEqual(self.bot.PipelineDisplayStatus.SKIPPED.value, "Skipped")

    def test_enum_str_inherits_for_string_compat(self):
        # str enum so direct string comparison works
        self.assertEqual(self.bot.PipelineDisplayStatus.IDLE, "Idle")


class ComputeDisplayStatusTests(unittest.TestCase):
    """compute_display_status priority + edge cases."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pds-compute-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)
        cls.now = time.time()

    def test_idle_when_no_state_no_schedule(self):
        result = self.bot.compute_display_status("p1", None, None, self.now)
        self.assertEqual(result, "Idle")

    def test_idle_when_empty_state_no_schedule(self):
        result = self.bot.compute_display_status("p1", {}, {}, self.now)
        self.assertEqual(result, "Idle")

    def test_scheduled_when_future_time_today(self):
        # Future time: 2 hours from now
        future = time.localtime(self.now + 7200)
        future_str = f"{future.tm_hour:02d}:{future.tm_min:02d}"
        schedule = {"times": [future_str]}
        result = self.bot.compute_display_status("p1", {}, schedule, self.now)
        self.assertEqual(result, "Scheduled")

    def test_idle_when_only_past_times_today(self):
        # Past time within the SAME day (avoid wraparound where now-7200 lands
        # on yesterday and reads as "future today" by hour comparison).
        now_lt = time.localtime(self.now)
        if now_lt.tm_min > 0:
            past_str = f"{now_lt.tm_hour:02d}:{now_lt.tm_min - 1:02d}"
        elif now_lt.tm_hour > 0:
            past_str = f"{now_lt.tm_hour - 1:02d}:59"
        else:
            self.skipTest("cannot run at exactly midnight (no past minute today)")
            return
        schedule = {"times": [past_str]}
        result = self.bot.compute_display_status("p1", {}, schedule, self.now)
        self.assertEqual(result, "Idle")

    def test_scheduled_with_interval(self):
        # Interval-based pipelines always count as scheduled when not running
        schedule = {"interval": "30m"}
        result = self.bot.compute_display_status("p1", {}, schedule, self.now)
        self.assertEqual(result, "Scheduled")

    def test_running_overrides_other_states(self):
        state = {"21:30": {"status": "running", "started_at": "2026-05-02T21:30:00"}}
        # Even if there's also a finalized entry, running wins
        result = self.bot.compute_display_status("p1", state, None, self.now)
        self.assertEqual(result, "Running")

    def test_running_beats_failed_in_other_slot(self):
        state = {
            "09:00": {"status": "failed", "finished_at": "2026-05-02T09:05:00"},
            "21:30": {"status": "running", "started_at": "2026-05-02T21:30:00"},
        }
        result = self.bot.compute_display_status("p1", state, None, self.now)
        self.assertEqual(result, "Running")

    def test_failed_when_most_recent_failed(self):
        state = {"21:30": {"status": "failed", "finished_at": "2026-05-02T21:35:00"}}
        result = self.bot.compute_display_status("p1", state, None, self.now)
        self.assertEqual(result, "Failed")

    def test_failed_when_most_recent_cancelled(self):
        state = {"21:30": {"status": "cancelled", "finished_at": "2026-05-02T21:35:00"}}
        result = self.bot.compute_display_status("p1", state, None, self.now)
        self.assertEqual(result, "Failed")

    def test_success_when_completed_and_publish_emitted_true(self):
        state = {"21:30": {"status": "completed", "publish_emitted": True,
                           "finished_at": "2026-05-02T21:35:00"}}
        result = self.bot.compute_display_status("p1", state, None, self.now)
        self.assertEqual(result, "Success")

    def test_success_when_completed_and_publish_emitted_unknown(self):
        # Backward compat: legacy state files lack publish_emitted; default to Success
        state = {"21:30": {"status": "completed", "finished_at": "2026-05-02T21:35:00"}}
        result = self.bot.compute_display_status("p1", state, None, self.now)
        self.assertEqual(result, "Success")

    def test_skipped_when_completed_but_publish_emitted_false(self):
        # NO_REPLY cascade reached the sink — soft success but nothing was sent
        state = {"21:30": {"status": "completed", "publish_emitted": False,
                           "finished_at": "2026-05-02T21:35:00"}}
        result = self.bot.compute_display_status("p1", state, None, self.now)
        self.assertEqual(result, "Skipped")

    def test_skipped_when_explicit_skipped_status(self):
        state = {"21:30": {"status": "skipped", "finished_at": "2026-05-02T21:35:00"}}
        result = self.bot.compute_display_status("p1", state, None, self.now)
        self.assertEqual(result, "Skipped")

    def test_picks_most_recent_when_multiple_finalized_today(self):
        state = {
            "09:00": {"status": "failed", "finished_at": "2026-05-02T09:05:00"},
            "18:00": {"status": "completed", "publish_emitted": True,
                      "finished_at": "2026-05-02T18:05:00"},
        }
        result = self.bot.compute_display_status("p1", state, None, self.now)
        # Most recent (18:00) → Success (failed at 09:00 is older)
        self.assertEqual(result, "Success")

    def test_finalized_overrides_scheduled(self):
        # If a run already happened today AND a future fire is scheduled, the
        # most recent finalized state wins (we report on what HAPPENED today).
        future = time.localtime(self.now + 7200)
        future_str = f"{future.tm_hour:02d}:{future.tm_min:02d}"
        state = {"09:00": {"status": "completed", "publish_emitted": True,
                           "finished_at": "2026-05-02T09:05:00"}}
        schedule = {"times": [future_str]}
        result = self.bot.compute_display_status("p1", state, schedule, self.now)
        self.assertEqual(result, "Success")


class StateManagerAdditiveFieldsTests(unittest.TestCase):
    """RoutineStateManager.set_pipeline_status accepts publish_emitted + display_status."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp(prefix="pds-state-"))
        cls.bot = load_bot_module(tmp_home=cls.tmp)

    def setUp(self):
        # Fresh state per test
        import shutil
        rstate_dir = self.bot.ROUTINES_STATE_DIR
        if rstate_dir.exists():
            shutil.rmtree(rstate_dir)
        rstate_dir.mkdir(parents=True, exist_ok=True)
        self.state = self.bot.RoutineStateManager()

    def test_legacy_call_without_new_fields_works(self):
        """Existing call sites keep working — new kwargs are optional."""
        self.state.set_pipeline_status("p1", "00:00", "completed")
        # No exception, entry exists
        data = self.state._load()
        self.assertIn("p1", data)
        self.assertEqual(data["p1"]["00:00"]["status"], "completed")
        # New fields not set when not passed
        self.assertNotIn("publish_emitted", data["p1"]["00:00"])
        self.assertNotIn("display_status", data["p1"]["00:00"])

    def test_publish_emitted_persisted(self):
        self.state.set_pipeline_status("p1", "00:00", "completed", publish_emitted=True)
        data = self.state._load()
        self.assertEqual(data["p1"]["00:00"]["publish_emitted"], True)

    def test_publish_emitted_false_persisted(self):
        self.state.set_pipeline_status("p1", "00:00", "completed", publish_emitted=False)
        data = self.state._load()
        self.assertEqual(data["p1"]["00:00"]["publish_emitted"], False)

    def test_display_status_persisted(self):
        self.state.set_pipeline_status("p1", "00:00", "completed",
                                       display_status="Success")
        data = self.state._load()
        self.assertEqual(data["p1"]["00:00"]["display_status"], "Success")

    def test_both_fields_persisted_together(self):
        self.state.set_pipeline_status("p1", "00:00", "failed",
                                       publish_emitted=False,
                                       display_status="Failed",
                                       error="step X failed")
        data = self.state._load()
        entry = data["p1"]["00:00"]
        self.assertEqual(entry["publish_emitted"], False)
        self.assertEqual(entry["display_status"], "Failed")
        self.assertEqual(entry["error"], "step X failed")
        self.assertEqual(entry["status"], "failed")


if __name__ == "__main__":
    unittest.main()
