"""Tests for ChatGPT/Codex provider routing and fallback chain behavior."""
import unittest

from tests._botload import load_bot_module


class ModelProviderOpenAI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_gpt_5_is_openai(self):
        self.assertEqual(self.bot.model_provider("gpt-5"), "openai")

    def test_gpt_5_codex_is_openai(self):
        self.assertEqual(self.bot.model_provider("gpt-5-codex"), "openai")

    def test_gpt_future_prefix_inference(self):
        self.assertEqual(self.bot.model_provider("gpt-6-experimental"), "openai")

    def test_other_providers_unaffected(self):
        self.assertEqual(self.bot.model_provider("sonnet"), "anthropic")
        self.assertEqual(self.bot.model_provider("glm-5.1"), "zai")
        self.assertEqual(self.bot.model_provider("opus"), "anthropic")


class FallbackChainCrossProvider(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def setUp(self):
        # Snapshot original chain so each test starts clean
        self._orig_chain = list(self.bot.MODEL_FALLBACK_CHAIN)
        self._orig_zai = self.bot.ZAI_API_KEY
        self._orig_codex = self.bot.CODEX_ENABLED

    def tearDown(self):
        self.bot.MODEL_FALLBACK_CHAIN[:] = self._orig_chain
        self.bot.ZAI_API_KEY = self._orig_zai
        self.bot.CODEX_ENABLED = self._orig_codex

    def test_skips_openai_when_codex_disabled(self):
        self.bot.MODEL_FALLBACK_CHAIN[:] = ["opus", "gpt-5", "sonnet"]
        self.bot.CODEX_ENABLED = False
        # Normal (non-AUTH/RATE_LIMIT) error kind so provider-skip doesn't kick in
        nxt = self.bot.get_fallback_model("opus", self.bot.ErrorKind.UNKNOWN)
        self.assertEqual(nxt, "sonnet")

    def test_includes_openai_when_codex_enabled(self):
        self.bot.MODEL_FALLBACK_CHAIN[:] = ["opus", "gpt-5", "sonnet"]
        self.bot.CODEX_ENABLED = True
        nxt = self.bot.get_fallback_model("opus", self.bot.ErrorKind.UNKNOWN)
        self.assertEqual(nxt, "gpt-5")

    def test_rate_limit_on_opus_hops_to_gpt_not_sonnet(self):
        # Cross-provider fallback: RATE_LIMIT on anthropic → skip all anthropic.
        self.bot.MODEL_FALLBACK_CHAIN[:] = ["opus", "sonnet", "gpt-5", "haiku"]
        self.bot.CODEX_ENABLED = True
        nxt = self.bot.get_fallback_model("opus", self.bot.ErrorKind.RATE_LIMIT)
        self.assertEqual(nxt, "gpt-5")

    def test_rate_limit_on_gpt_hops_to_other_provider(self):
        # RATE_LIMIT on openai → skip openai, pick next non-openai
        self.bot.MODEL_FALLBACK_CHAIN[:] = ["gpt-5", "gpt-5-codex", "sonnet"]
        self.bot.CODEX_ENABLED = True
        self.bot.ZAI_API_KEY = ""  # force anthropic as the only alternative
        nxt = self.bot.get_fallback_model("gpt-5", self.bot.ErrorKind.RATE_LIMIT)
        self.assertEqual(nxt, "sonnet")

    def test_no_candidate_returns_none(self):
        self.bot.MODEL_FALLBACK_CHAIN[:] = ["opus", "gpt-5"]
        self.bot.CODEX_ENABLED = False
        self.bot.ZAI_API_KEY = ""
        # opus is last viable — nothing after
        self.assertIsNone(
            self.bot.get_fallback_model("opus", self.bot.ErrorKind.UNKNOWN)
        )


class CodexModelRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_gpt_models_in_full_ids_table(self):
        self.assertIn("gpt-5", self.bot.MODEL_FULL_IDS)
        self.assertIn("gpt-5-codex", self.bot.MODEL_FULL_IDS)

    def test_gpt_models_in_providers_table(self):
        self.assertEqual(self.bot.MODEL_PROVIDERS["gpt-5"], "openai")
        self.assertEqual(self.bot.MODEL_PROVIDERS["gpt-5-codex"], "openai")


if __name__ == "__main__":
    unittest.main()
