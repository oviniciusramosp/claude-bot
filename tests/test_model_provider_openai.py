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


class PerProviderSessionId(unittest.TestCase):
    """Session.session_id (Claude) and Session.codex_thread_id (Codex) live
    side by side so switching providers mid-session doesn't corrupt either."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def _session(self, **kw):
        kw.setdefault("name", "test")
        return self.bot.Session(**kw)

    def test_session_id_for_claude_returns_claude_sid(self):
        s = self._session(session_id="claude-abc", codex_thread_id="codex-xyz",
                          model="sonnet")
        self.assertEqual(self.bot._session_id_for(s), "claude-abc")

    def test_session_id_for_gpt_returns_codex_sid(self):
        s = self._session(session_id="claude-abc", codex_thread_id="codex-xyz",
                          model="gpt-5")
        self.assertEqual(self.bot._session_id_for(s), "codex-xyz")

    def test_session_id_for_glm_uses_claude_sid(self):
        # GLM shares the Claude local history store
        s = self._session(session_id="claude-abc", codex_thread_id="codex-xyz",
                          model="glm-4.7")
        self.assertEqual(self.bot._session_id_for(s), "claude-abc")

    def test_session_id_for_explicit_model_overrides_session_model(self):
        s = self._session(session_id="claude-abc", codex_thread_id="codex-xyz",
                          model="sonnet")
        # Fallback chain might route to gpt — should use codex id even though
        # session.model is still sonnet.
        self.assertEqual(self.bot._session_id_for(s, "gpt-5"), "codex-xyz")


class PersistCapturedId(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def _runner(self, captured=None, exit_code=0, error_text=""):
        r = self.bot.ClaudeRunner()
        r.captured_session_id = captured
        r.exit_code = exit_code
        r.error_text = error_text
        return r

    def _session(self, **kw):
        kw.setdefault("name", "test")
        return self.bot.Session(**kw)

    def test_persists_to_session_id_for_claude(self):
        s = self._session(model="sonnet")
        r = self._runner(captured="new-claude-sid")
        stored = self.bot._persist_captured_id(s, r)
        self.assertTrue(stored)
        self.assertEqual(s.session_id, "new-claude-sid")
        self.assertIsNone(s.codex_thread_id)

    def test_persists_to_codex_thread_id_for_gpt(self):
        s = self._session(model="gpt-5")
        r = self._runner(captured="new-codex-thread")
        stored = self.bot._persist_captured_id(s, r)
        self.assertTrue(stored)
        self.assertEqual(s.codex_thread_id, "new-codex-thread")
        self.assertIsNone(s.session_id)

    def test_does_not_persist_on_failed_run(self):
        s = self._session(model="gpt-5", codex_thread_id="old-id")
        r = self._runner(captured="fresh-id", exit_code=1, error_text="oops")
        stored = self.bot._persist_captured_id(s, r)
        self.assertFalse(stored)
        # Previous id unchanged (no poisoning)
        self.assertEqual(s.codex_thread_id, "old-id")

    def test_does_not_persist_when_no_capture(self):
        s = self._session(model="sonnet")
        r = self._runner(captured=None)
        self.assertFalse(self.bot._persist_captured_id(s, r))

    def test_error_text_alone_blocks_persist_even_with_exit_zero(self):
        # exit_code can be None for runners that never got to finalize;
        # error_text is the stronger signal that something went wrong.
        s = self._session(model="sonnet")
        r = self._runner(captured="maybe-id", exit_code=0, error_text="bad")
        self.assertFalse(self.bot._persist_captured_id(s, r))


if __name__ == "__main__":
    unittest.main()
