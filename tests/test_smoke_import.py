"""Smoke test: the bot module imports without errors under the test harness.

If this fails, every other test fails — fix this first.
"""
import tempfile
import unittest
from pathlib import Path

from tests._botload import load_bot_module


class SmokeImport(unittest.TestCase):
    def test_bot_module_loads(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / "home"
            home.mkdir()
            vault = Path(td) / "vault"
            bot = load_bot_module(tmp_home=home, vault_dir=vault)
            self.assertTrue(hasattr(bot, "BOT_VERSION"))
            self.assertTrue(hasattr(bot, "SessionManager"))
            self.assertTrue(hasattr(bot, "RoutineScheduler"))
            self.assertTrue(hasattr(bot, "ClaudeRunner"))
            self.assertTrue(hasattr(bot, "parse_frontmatter"))
            self.assertTrue(hasattr(bot, "ClaudeTelegramBot"))
            self.assertTrue(bot.DATA_DIR.is_dir())


if __name__ == "__main__":
    unittest.main()
