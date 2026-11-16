"""Friendly model names in messages (v3.89.1).

`/model` → Sonnet 5.5 answered "Modelo alterado para `sonnet-5`": the bot key
for Sonnet 5.5 is `sonnet-5`, and that internal key was shown verbatim. The
model that ran was right (claude-sonnet-5-5); only the label was wrong.
"""
import tempfile
import threading
from pathlib import Path
import unittest
from unittest.mock import MagicMock

from tests._botload import load_bot_module


class DisplayName(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.m.MODEL_IDS_FILE = Path(self._td.name) / "model-ids.json"
        self.m._LEARNED_MODEL_IDS = None

    def test_known_keys(self):
        f = self.m.model_display_name
        self.assertEqual(f("sonnet-5"), "Sonnet 5.5")
        self.assertEqual(f("fable"), "Fable 5.1")
        self.assertEqual(f("haiku"), "Haiku 5.5")
        self.assertEqual(f("gpt-5.5"), "GPT-5.5")

    def test_context_suffix_and_concrete_ids(self):
        f = self.m.model_display_name
        self.assertEqual(f("opus[1m]"), f("opus"))
        self.assertEqual(f("claude-sonnet-5-5"), "Sonnet 5.5")

    def test_unknown_and_empty(self):
        self.assertEqual(self.m.model_display_name("algo"), "algo")
        self.assertEqual(self.m.model_display_name(None), "—")

    def test_name_follows_the_model_the_cli_really_ran(self):
        r = self.m.ClaudeRunner()
        r._requested_model = "opus"
        r._handle_event({"type": "system", "subtype": "init", "model": "claude-opus-6[1m]"})
        self.assertEqual(self.m.model_display_name("opus"), "Opus 6")
        # survives a restart
        self.m._LEARNED_MODEL_IDS = None
        self.assertEqual(self.m.model_display_name("opus"), "Opus 6")

    def test_non_claude_ids_are_not_learned(self):
        self.m.learn_model_id("glm-5.1", "sonnet")  # z.AI proxy alias
        self.assertFalse(self.m.MODEL_IDS_FILE.exists())

    def test_corrupt_file_falls_back_loudly(self):
        self.m.MODEL_IDS_FILE.write_text("{nope", encoding="utf-8")
        with self.assertLogs(self.m.logger, level="ERROR"):
            self.assertEqual(self.m.model_display_name("sonnet-5"), "Sonnet 5.5")

    def test_picker_buttons_use_the_same_names(self):
        self.m.learn_model_id("haiku", "claude-haiku-6")
        cls = self.m.ClaudeTelegramBot
        bot = cls.__new__(cls)
        bot._ctx_local = threading.local()
        bot.send_message = MagicMock()
        bot.cmd_model_keyboard()
        labels = [b["text"] for row in bot.send_message.call_args.kwargs["reply_markup"]["inline_keyboard"] for b in row]
        self.assertIn("Haiku 6", labels)
        self.assertIn("Sonnet 5.5", labels)

    def test_model_switch_confirmation_uses_friendly_name(self):
        cls = self.m.ClaudeTelegramBot
        bot = cls.__new__(cls)
        bot._ctx_local = threading.local()
        bot.send_message = MagicMock()
        session = MagicMock(model="opus", name="s")
        bot._get_session = MagicMock(return_value=session)
        bot.sessions = MagicMock()
        bot._transcripts_lock = threading.Lock()
        bot._transcripts = {}
        bot._handoff_pending = {}
        bot.cmd_model_switch("sonnet-5")
        text = bot.send_message.call_args.args[0]
        self.assertIn("Sonnet 5.5", text)
        self.assertNotIn("sonnet-5", text)
        self.assertEqual(session.model, "sonnet-5")  # what runs is unchanged


if __name__ == "__main__":
    unittest.main()
