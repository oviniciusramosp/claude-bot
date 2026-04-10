"""Unit tests for _track_cost / get_weekly_cost (weekly cost tracker)."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from tests._botload import load_bot_module


class CostTracking(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)

    def tearDown(self):
        self._td.cleanup()

    def test_track_cost_creates_file(self):
        self.bot._track_cost(0.05)
        self.assertTrue(self.bot.COSTS_FILE.exists())
        data = json.loads(self.bot.COSTS_FILE.read_text())
        self.assertIn("weeks", data)
        self.assertIn("current_week", data)

    def test_track_cost_accumulates(self):
        self.bot._track_cost(0.10)
        self.bot._track_cost(0.20)
        self.bot._track_cost(0.30)
        weekly = self.bot.get_weekly_cost()
        self.assertAlmostEqual(weekly["total"], 0.60, places=4)
        self.assertAlmostEqual(weekly["today"], 0.60, places=4)

    def test_get_weekly_cost_empty_returns_zeros(self):
        weekly = self.bot.get_weekly_cost()
        self.assertEqual(weekly["total"], 0.0)
        self.assertEqual(weekly["today"], 0.0)

    def test_prunes_old_weeks(self):
        # Manually inject 6 weeks of data; bot should keep only last 4
        data = {
            "weeks": {
                "2026-W10": {"total": 1.0, "days": {}},
                "2026-W11": {"total": 1.0, "days": {}},
                "2026-W12": {"total": 1.0, "days": {}},
                "2026-W13": {"total": 1.0, "days": {}},
                "2026-W14": {"total": 1.0, "days": {}},
            },
            "current_week": "2026-W14",
        }
        self.bot.COSTS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.bot.COSTS_FILE.write_text(json.dumps(data))
        self.bot._track_cost(0.01)
        out = json.loads(self.bot.COSTS_FILE.read_text())
        self.assertLessEqual(len(out["weeks"]), 4)


if __name__ == "__main__":
    unittest.main()
