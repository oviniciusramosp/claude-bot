"""Unit tests for error classification + recovery planning + translation."""
import unittest

from tests._botload import load_bot_module


class ClassifyError(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def _kind(self, raw):
        return self.bot.classify_error(raw)

    def test_overloaded(self):
        self.assertEqual(self._kind("API overloaded"), self.bot.ErrorKind.OVERLOADED)

    def test_rate_limit(self):
        self.assertEqual(self._kind("rate limit exceeded"), self.bot.ErrorKind.RATE_LIMIT)
        self.assertEqual(self._kind("HTTP 429 too many"), self.bot.ErrorKind.RATE_LIMIT)

    def test_rate_limit_zai_format(self):
        """z.AI puts API errors in result_text — classify_error must still match."""
        zai_err = 'API Error: 429 {"error":{"code":"1302","message":"Rate limit reached for requests"}}'
        self.assertEqual(self._kind(zai_err), self.bot.ErrorKind.RATE_LIMIT)

    def test_context_too_long(self):
        self.assertEqual(self._kind("maximum context length"), self.bot.ErrorKind.CONTEXT_TOO_LONG)
        self.assertEqual(self._kind("too many tokens"), self.bot.ErrorKind.CONTEXT_TOO_LONG)

    def test_auth(self):
        self.assertEqual(self._kind("401 unauthorized"), self.bot.ErrorKind.AUTH)
        self.assertEqual(self._kind("invalid api key"), self.bot.ErrorKind.AUTH)
        self.assertEqual(self._kind("authentication failed"), self.bot.ErrorKind.AUTH)

    def test_credit(self):
        self.assertEqual(self._kind("insufficient credit"), self.bot.ErrorKind.CREDIT)
        self.assertEqual(self._kind("billing error"), self.bot.ErrorKind.CREDIT)

    def test_not_found(self):
        self.assertEqual(self._kind("model not found"), self.bot.ErrorKind.NOT_FOUND)
        self.assertEqual(self._kind("HTTP 404"), self.bot.ErrorKind.NOT_FOUND)

    def test_timeout(self):
        self.assertEqual(self._kind("request timed out"), self.bot.ErrorKind.TIMEOUT)
        self.assertEqual(self._kind("timeout reached"), self.bot.ErrorKind.TIMEOUT)

    def test_connection(self):
        self.assertEqual(self._kind("connection refused"), self.bot.ErrorKind.CONNECTION)
        self.assertEqual(self._kind("network unreachable"), self.bot.ErrorKind.CONNECTION)

    def test_cli_crash(self):
        self.assertEqual(self._kind("segmentation fault"), self.bot.ErrorKind.CLI_CRASH)
        self.assertEqual(self._kind("broken pipe"), self.bot.ErrorKind.CLI_CRASH)

    def test_empty_returns_unknown(self):
        self.assertEqual(self._kind(""), self.bot.ErrorKind.UNKNOWN)

    def test_unknown(self):
        self.assertEqual(self._kind("totally bizarre error"), self.bot.ErrorKind.UNKNOWN)


class RecoveryPlan(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_overloaded_uses_backoff(self):
        action, backoff, max_attempts = self.bot.get_recovery_plan(self.bot.ErrorKind.OVERLOADED)
        self.assertEqual(action, self.bot.RecoveryAction.BACKOFF_RETRY)
        self.assertGreater(backoff, 0)
        self.assertGreaterEqual(max_attempts, 1)

    def test_rate_limit_uses_longer_backoff(self):
        _, backoff_overloaded, _ = self.bot.get_recovery_plan(self.bot.ErrorKind.OVERLOADED)
        _, backoff_rate, _ = self.bot.get_recovery_plan(self.bot.ErrorKind.RATE_LIMIT)
        self.assertGreater(backoff_rate, backoff_overloaded)

    def test_rate_limit_allows_two_retries(self):
        """z.AI rate limits need 2 retry attempts with escalating backoff."""
        action, backoff, max_attempts = self.bot.get_recovery_plan(self.bot.ErrorKind.RATE_LIMIT)
        self.assertEqual(action, self.bot.RecoveryAction.BACKOFF_RETRY)
        self.assertEqual(backoff, 90)
        self.assertEqual(max_attempts, 2)

    def test_context_too_long_triggers_compact(self):
        action, _, _ = self.bot.get_recovery_plan(self.bot.ErrorKind.CONTEXT_TOO_LONG)
        self.assertEqual(action, self.bot.RecoveryAction.RETRY_AFTER_COMPACT)

    def test_auth_aborts(self):
        action, _, max_attempts = self.bot.get_recovery_plan(self.bot.ErrorKind.AUTH)
        self.assertEqual(action, self.bot.RecoveryAction.ABORT)
        self.assertEqual(max_attempts, 0)

    def test_credit_aborts(self):
        action, _, _ = self.bot.get_recovery_plan(self.bot.ErrorKind.CREDIT)
        self.assertEqual(action, self.bot.RecoveryAction.ABORT)


class TranslateError(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_overloaded_message(self):
        msg = self.bot._translate_error("the model is overloaded right now")
        self.assertIn("sobrecarregada", msg)

    def test_rate_limit_message(self):
        msg = self.bot._translate_error("rate limit hit")
        self.assertIn("Limite", msg)
        self.assertIn("429", msg)

    def test_unknown_truncates(self):
        long = "x" * 1000
        msg = self.bot._translate_error(long)
        # 400 char snippet plus markdown wrapper
        self.assertLess(len(msg), 600)
        self.assertIn("Erro do Claude CLI", msg)


if __name__ == "__main__":
    unittest.main()
