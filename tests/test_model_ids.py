"""v3.81.2 — model ids that the installed CLI actually serves.

Probed live on CLI 2.1.274 with the bot credential: claude-fable-5-5 does not
exist (Fable is 5.1), the bare `sonnet`/`haiku` aliases lag behind the 5.5 ids,
and claude-opus-5-5 needs CLI 2.1.280+. Also covers the false "model
unavailable" signal from a stderr warning on a successful run.
"""
import os
import unittest

from tests._botload import load_bot_module

# The exact warning CLI 2.1.274 prints for ids newer than its own catalog,
# even though the API call succeeds.
UNRECOGNIZED_WARNING = (
    '[claude-code:unrecognized_model] {"model":"claude-sonnet-5-5[1m]",'
    '"query_source":"sdk"}'
)


class ModelIdResolution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def setUp(self):
        self._env = {k: os.environ.pop(k, None) for k in self.bot.MODEL_ALIAS_ENV.values()}

    def tearDown(self):
        for k, v in self._env.items():
            if v is not None:
                os.environ[k] = v
            else:
                os.environ.pop(k, None)

    def test_fable_uses_real_5_1_id(self):
        self.assertEqual(self.bot.resolve_model_alias("fable"), "claude-fable-5-1")
        self.assertEqual(self.bot.MODEL_FULL_IDS["fable"], "claude-fable-5-1")

    def test_sonnet_and_haiku_pinned_to_5_5(self):
        self.assertEqual(self.bot.resolve_model_alias("sonnet"), "claude-sonnet-5-5")
        self.assertEqual(self.bot.resolve_model_alias("sonnet-5"), "claude-sonnet-5-5")
        self.assertEqual(self.bot.resolve_model_alias("haiku"), "claude-haiku-5-5")

    def test_opus_stays_on_alias(self):
        # claude-opus-5-5 is rejected by CLIs older than 2.1.280.
        self.assertEqual(self.bot.resolve_model_alias("opus"), "opus")

    def test_env_pin_beats_default_pin(self):
        os.environ["HAIKU_MODEL"] = "haiku"  # opt back into the bare alias
        self.assertEqual(self.bot.resolve_model_alias("haiku"), "haiku")

    def test_haiku_pin_still_skips_1m(self):
        self.assertEqual(
            self.bot.resolve_max_context_model("claude-haiku-5-5"), "claude-haiku-5-5")


class SuccessfulRunIsNotModelUnavailable(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def setUp(self):
        self.runner = self.bot.ClaudeRunner()
        self.runner.running = True

    def test_result_event_records_is_error(self):
        self.runner._handle_event({"type": "result", "result": "ok", "is_error": False})
        self.assertIs(self.runner.result_is_error, False)
        self.runner._handle_event({"type": "result", "result": "x", "is_error": True})
        self.assertIs(self.runner.result_is_error, True)

    def test_stderr_warning_on_success_is_ignored(self):
        self.runner._handle_event({"type": "result", "result": "ok", "is_error": False})
        self.runner.stderr_text = UNRECOGNIZED_WARNING
        self.assertFalse(self.runner._looks_like_model_unavailable())

    def test_same_warning_without_result_still_counts(self):
        # No result event (e.g. the CLI died): the stderr signal is all we have.
        self.runner.stderr_text = UNRECOGNIZED_WARNING
        self.assertTrue(self.runner._looks_like_model_unavailable())

    def test_real_rejection_still_detected(self):
        self.runner._handle_event({
            "type": "result", "is_error": True,
            "result": "API Error: 400 Claude Code 2.1.274 does not support this "
                      "model; version 2.1.280 or newer is required",
        })
        self.assertTrue(self.runner._looks_like_model_unavailable())

    def test_retry_reset_clears_result_flag(self):
        self.runner._handle_event({"type": "result", "result": "ok", "is_error": False})
        self.runner._reset_for_retry()
        self.assertIsNone(self.runner.result_is_error)


if __name__ == "__main__":
    unittest.main()
