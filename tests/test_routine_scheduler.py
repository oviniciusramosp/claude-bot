"""Unit tests for RoutineScheduler scheduling logic and pipeline DAG validation.

We avoid the background thread by calling _check_routines() directly with a
monkeypatched fake `time` module.
"""
import tempfile
import time as real_time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tests._botload import load_bot_module


class _FakeTime:
    """Replace bot.time with a frozen-clock impl. tm_wday: 0=Mon."""
    def __init__(self, year=2026, mon=4, day=10, hour=8, minute=0, wday=4):
        # Default: Friday Apr 10 2026 08:00
        self.y, self.mo, self.d, self.h, self.mi, self.w = year, mon, day, hour, minute, wday

    def strftime(self, fmt):
        if fmt == "%H:%M":
            return f"{self.h:02d}:{self.mi:02d}"
        if fmt == "%Y-%m-%d":
            return f"{self.y:04d}-{self.mo:02d}-{self.d:02d}"
        if fmt == "%Y-%m-%dT%H:%M:%S":
            return f"{self.y:04d}-{self.mo:02d}-{self.d:02d}T{self.h:02d}:{self.mi:02d}:00"
        if fmt == "%G-W%V":
            return "2026-W15"
        return real_time.strftime(fmt)

    def localtime(self, *_):
        # Return an object with tm_wday attribute
        return type("tm", (), {"tm_wday": self.w})()

    def time(self):
        return real_time.time()

    def sleep(self, *_):
        pass


def _write_routine(routines_dir: Path, name: str, content: str) -> Path:
    routines_dir.mkdir(parents=True, exist_ok=True)
    p = routines_dir / f"{name}.md"
    p.write_text(content, encoding="utf-8")
    return p


def _make_routine_md(*, title="r", times="08:00", days="*", enabled="true",
                     model="sonnet", routine_type="routine", until=None,
                     body="do the thing"):
    times_block = f'  times: ["{times}"]' if not times.startswith("[") else f"  times: {times}"
    days_block = f'  days: ["{days}"]' if not days.startswith("[") else f"  days: {days}"
    until_line = f"  until: {until}\n" if until else ""
    return (
        "---\n"
        f"title: {title}\n"
        f"type: {routine_type}\n"
        f"model: {model}\n"
        f"enabled: {enabled}\n"
        "schedule:\n"
        f"{times_block}\n"
        f"{days_block}\n"
        f"{until_line}"
        "---\n"
        f"{body}\n"
    )


class SchedulerMatching(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        self.fake_time = _FakeTime()
        # Replace the bot's `time` with fake clock
        self._real_time = self.bot.time
        self.bot.time = self.fake_time

        self.enqueued = []
        self.enqueued_pipelines = []
        self.notifications = []

        self.state = self.bot.RoutineStateManager()
        self.scheduler = self.bot.RoutineScheduler(
            self.state,
            enqueue_fn=lambda task: self.enqueued.append(task),
            enqueue_pipeline_fn=lambda task: self.enqueued_pipelines.append(task),
            notify_fn=lambda msg: self.notifications.append(msg),
        )

    def tearDown(self):
        self.bot.time = self._real_time
        self._td.cleanup()

    def test_matches_when_time_and_day_align(self):
        _write_routine(self.bot.ROUTINES_DIR, "morning", _make_routine_md(times="08:00", days="*"))
        self.scheduler._check_routines()
        self.assertEqual(len(self.enqueued), 1)
        self.assertEqual(self.enqueued[0].name, "morning")

    def test_does_not_match_when_time_differs(self):
        _write_routine(self.bot.ROUTINES_DIR, "evening", _make_routine_md(times="20:00"))
        self.scheduler._check_routines()
        self.assertEqual(self.enqueued, [])

    def test_does_not_run_twice_in_same_slot(self):
        _write_routine(self.bot.ROUTINES_DIR, "morning", _make_routine_md(times="08:00"))
        self.scheduler._check_routines()
        self.scheduler._check_routines()
        self.assertEqual(len(self.enqueued), 1)

    def test_disabled_routine_is_skipped(self):
        _write_routine(self.bot.ROUTINES_DIR, "off", _make_routine_md(enabled="false"))
        self.scheduler._check_routines()
        self.assertEqual(self.enqueued, [])

    def test_day_filter_friday_only(self):
        # Today fake = Friday (wday=4)
        _write_routine(self.bot.ROUTINES_DIR, "fri", _make_routine_md(days="fri"))
        _write_routine(self.bot.ROUTINES_DIR, "mon", _make_routine_md(days="mon"))
        self.scheduler._check_routines()
        names = [t.name for t in self.enqueued]
        self.assertIn("fri", names)
        self.assertNotIn("mon", names)

    def test_until_in_past_is_skipped(self):
        _write_routine(self.bot.ROUTINES_DIR, "expired",
                       _make_routine_md(until="2020-01-01"))
        self.scheduler._check_routines()
        self.assertEqual(self.enqueued, [])

    def test_until_in_future_runs(self):
        _write_routine(self.bot.ROUTINES_DIR, "future",
                       _make_routine_md(until="2099-12-31"))
        self.scheduler._check_routines()
        self.assertEqual(len(self.enqueued), 1)

    def test_index_type_is_skipped(self):
        # Routines.md hub file
        _write_routine(self.bot.ROUTINES_DIR, "Routines",
                       _make_routine_md(routine_type="index"))
        self.scheduler._check_routines()
        self.assertEqual(self.enqueued, [])

    def test_missing_required_field_notifies_once_per_day(self):
        # No "type" field -> invalid
        broken = (
            "---\n"
            "title: x\n"
            "model: sonnet\n"
            "enabled: true\n"
            "schedule:\n"
            '  times: ["08:00"]\n'
            "---\n"
            "body\n"
        )
        _write_routine(self.bot.ROUTINES_DIR, "broken", broken)
        self.scheduler._check_routines()
        self.scheduler._check_routines()  # second pass shouldn't re-notify
        self.assertEqual(len(self.notifications), 1)
        self.assertIn("broken", self.notifications[0])
        self.assertEqual(self.enqueued, [])

    def test_invalid_schedule_type_notifies(self):
        bad = (
            "---\n"
            "title: x\n"
            "type: routine\n"
            "model: sonnet\n"
            "enabled: true\n"
            "schedule: not_a_dict\n"
            "---\n"
            "body\n"
        )
        _write_routine(self.bot.ROUTINES_DIR, "bad", bad)
        self.scheduler._check_routines()
        self.assertEqual(len(self.notifications), 1)
        self.assertIn("bad", self.notifications[0])

    def test_routine_passes_effort_through(self):
        body = (
            "---\n"
            "title: with_effort\n"
            "type: routine\n"
            "model: sonnet\n"
            "enabled: true\n"
            "effort: high\n"
            "schedule:\n"
            '  times: ["08:00"]\n'
            "---\n"
            "do thing\n"
        )
        _write_routine(self.bot.ROUTINES_DIR, "with_effort", body)
        self.scheduler._check_routines()
        self.assertEqual(len(self.enqueued), 1)
        self.assertEqual(self.enqueued[0].effort, "high")

    def test_invalid_effort_value_becomes_none(self):
        body = (
            "---\n"
            "title: bad_effort\n"
            "type: routine\n"
            "model: sonnet\n"
            "enabled: true\n"
            "effort: extreme\n"
            "schedule:\n"
            '  times: ["08:00"]\n'
            "---\n"
            "do thing\n"
        )
        _write_routine(self.bot.ROUTINES_DIR, "bad_effort", body)
        self.scheduler._check_routines()
        self.assertEqual(self.enqueued[0].effort, None)

    def test_minimal_context_flag_propagates(self):
        body = (
            "---\n"
            "title: minctx\n"
            "type: routine\n"
            "model: sonnet\n"
            "enabled: true\n"
            "context: minimal\n"
            "schedule:\n"
            '  times: ["08:00"]\n'
            "---\n"
            "go\n"
        )
        _write_routine(self.bot.ROUTINES_DIR, "minctx", body)
        self.scheduler._check_routines()
        self.assertTrue(self.enqueued[0].minimal_context)


class SchedulerPipelineCycle(unittest.TestCase):
    """The DAG cycle detector should reject pipelines with circular deps."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        self.fake_time = _FakeTime()
        self._real_time = self.bot.time
        self.bot.time = self.fake_time

        self.enqueued = []
        self.enqueued_pipelines = []

        self.state = self.bot.RoutineStateManager()
        self.scheduler = self.bot.RoutineScheduler(
            self.state,
            enqueue_fn=lambda task: self.enqueued.append(task),
            enqueue_pipeline_fn=lambda task: self.enqueued_pipelines.append(task),
            notify_fn=lambda msg: None,
        )

    def tearDown(self):
        self.bot.time = self._real_time
        self._td.cleanup()

    def _write_pipeline(self, name: str, pipeline_block: str):
        body = (
            "---\n"
            f"title: {name}\n"
            "type: pipeline\n"
            "model: sonnet\n"
            "enabled: true\n"
            "schedule:\n"
            '  times: ["08:00"]\n'
            "---\n"
            f"```pipeline\n{pipeline_block}```\n"
        )
        (self.bot.ROUTINES_DIR / f"{name}.md").write_text(body, encoding="utf-8")

    def test_cycle_pipeline_not_enqueued(self):
        self._write_pipeline("cyc",
            "steps:\n"
            "  - id: a\n"
            "    name: A\n"
            "    prompt: do a\n"
            "    depends_on: [b]\n"
            "  - id: b\n"
            "    name: B\n"
            "    prompt: do b\n"
            "    depends_on: [a]\n"
        )
        self.scheduler._check_routines()
        self.assertEqual(self.enqueued_pipelines, [])

    def test_valid_dag_enqueued(self):
        self._write_pipeline("dag",
            "steps:\n"
            "  - id: collect\n"
            "    name: Collect\n"
            "    prompt: get data\n"
            "  - id: analyze\n"
            "    name: Analyze\n"
            "    prompt: think\n"
            "    depends_on: [collect]\n"
            "  - id: publish\n"
            "    name: Publish\n"
            "    prompt: send\n"
            "    depends_on: [analyze]\n"
            "    output: telegram\n"
        )
        self.scheduler._check_routines()
        self.assertEqual(len(self.enqueued_pipelines), 1)
        task = self.enqueued_pipelines[0]
        self.assertEqual(len(task.steps), 3)
        # Output type for the marked step
        publish_step = [s for s in task.steps if s.id == "publish"][0]
        self.assertEqual(publish_step.output_type, "telegram")
        self.assertTrue(publish_step.output_to_telegram)

    def test_pipeline_no_steps_skipped(self):
        body = (
            "---\n"
            "title: empty\n"
            "type: pipeline\n"
            "model: sonnet\n"
            "enabled: true\n"
            "schedule:\n"
            '  times: ["08:00"]\n'
            "---\n"
            "no pipeline block here\n"
        )
        (self.bot.ROUTINES_DIR / "empty.md").write_text(body, encoding="utf-8")
        self.scheduler._check_routines()
        self.assertEqual(self.enqueued_pipelines, [])


class ListTodayRoutines(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        self.fake_time = _FakeTime()
        self._real_time = self.bot.time
        self.bot.time = self.fake_time
        self.state = self.bot.RoutineStateManager()
        self.scheduler = self.bot.RoutineScheduler(
            self.state,
            enqueue_fn=lambda task: None,
            enqueue_pipeline_fn=lambda task: None,
            notify_fn=lambda msg: None,
        )

    def tearDown(self):
        self.bot.time = self._real_time
        self._td.cleanup()

    def test_lists_today_routines_with_status(self):
        _write_routine(self.bot.ROUTINES_DIR, "morning", _make_routine_md(times="08:00"))
        _write_routine(self.bot.ROUTINES_DIR, "evening", _make_routine_md(times="20:00"))
        items = self.scheduler.list_today_routines()
        names = [i["name"] for i in items]
        self.assertIn("morning", names)
        self.assertIn("evening", names)
        # Both should be 'pending' since neither has run
        for i in items:
            self.assertEqual(i["status"], "pending")
        # Sorted by time
        self.assertEqual(items[0]["time"], "08:00")
        self.assertEqual(items[1]["time"], "20:00")


if __name__ == "__main__":
    unittest.main()
