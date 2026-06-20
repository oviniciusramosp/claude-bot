"""Tests for auth hardening (v3.76): bot-owned Anthropic credential store,
the PKCE OAuth helpers, bearer resolution/injection, and the /auth command
group (remote diagnosis + recovery).

Network is never hit — `_oauth_token_request` is patched. The live `_auth_probe`
(which spawns the real CLI) is patched in dispatch tests so they stay hermetic.
"""
import base64
import hashlib
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._botload import load_bot_module
from tests.test_bot_integration import _BotFixture


class AuthHelpers(unittest.TestCase):
    """Pure module-level helpers — no bot instance needed."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)

    def tearDown(self):
        self._td.cleanup()

    # -- PKCE + authorize URL --

    def test_pkce_pair_is_valid_s256(self):
        verifier, challenge = self.bot._pkce_pair()
        expected = base64.urlsafe_b64encode(
            hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        self.assertEqual(challenge, expected)
        # No padding leaks into either value.
        self.assertNotIn("=", verifier)
        self.assertNotIn("=", challenge)

    def test_pkce_pair_is_random(self):
        self.assertNotEqual(self.bot._pkce_pair()[0], self.bot._pkce_pair()[0])

    def test_authorize_url_contains_pkce_and_client(self):
        url = self.bot._build_authorize_url("CHAL", "STATE")
        self.assertIn(self.bot.CLAUDE_OAUTH_CLIENT_ID, url)
        self.assertIn("code_challenge=CHAL", url)
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("state=STATE", url)
        self.assertIn("response_type=code", url)

    # -- credential store round-trip --

    def test_save_load_clear_round_trip(self):
        self.assertIsNone(self.bot._load_bot_auth())
        data = {"method": "setup_token", "token": "sk-ant-oat01-xyz"}
        self.bot._save_bot_auth(data)
        self.assertEqual(self.bot._load_bot_auth()["token"], "sk-ant-oat01-xyz")
        self.bot._clear_bot_auth()
        self.assertIsNone(self.bot._load_bot_auth())
        # Clearing again is a no-op (no exception).
        self.bot._clear_bot_auth()

    def test_saved_file_is_0600(self):
        self.bot._save_bot_auth({"method": "setup_token", "token": "sk-ant-x"})
        mode = os.stat(self.bot._CLAUDE_AUTH_FILE).st_mode & 0o777
        self.assertEqual(mode, 0o600)

    def test_load_tolerates_corrupt_file(self):
        self.bot._CLAUDE_AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.bot._CLAUDE_AUTH_FILE.write_text("{ not json")
        self.assertIsNone(self.bot._load_bot_auth())  # fail-open, no raise

    # -- bearer resolution --

    def test_resolve_none_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            self.assertIsNone(self.bot.resolve_oauth_bearer())

    def test_resolve_setup_token(self):
        self.bot._save_bot_auth({"method": "setup_token", "token": "sk-ant-oat01-LONG"})
        self.assertEqual(self.bot.resolve_oauth_bearer(), "sk-ant-oat01-LONG")

    def test_resolve_oauth_fresh_token_no_refresh(self):
        self.bot._save_bot_auth({
            "method": "oauth", "access_token": "AT", "refresh_token": "RT",
            "expires_at": time.time() + 3600})
        with patch.object(self.bot, "_oauth_token_request") as m:
            self.assertEqual(self.bot.resolve_oauth_bearer(), "AT")
            m.assert_not_called()  # still fresh — no refresh

    def test_resolve_oauth_refreshes_when_expiring(self):
        self.bot._save_bot_auth({
            "method": "oauth", "access_token": "OLD", "refresh_token": "RT",
            "expires_at": time.time() - 10})  # already expired
        with patch.object(self.bot, "_oauth_token_request",
                          return_value={"access_token": "NEW", "refresh_token": "RT2",
                                        "expires_in": 3600}) as m:
            self.assertEqual(self.bot.resolve_oauth_bearer(), "NEW")
            m.assert_called_once()
        # Persisted the rotated tokens.
        creds = self.bot._load_bot_auth()
        self.assertEqual(creds["access_token"], "NEW")
        self.assertEqual(creds["refresh_token"], "RT2")

    def test_resolve_oauth_refresh_failure_returns_stale(self):
        self.bot._save_bot_auth({
            "method": "oauth", "access_token": "STALE", "refresh_token": "RT",
            "expires_at": time.time() - 10})
        # Refresh raises (dead refresh token) → still return stale so the 401
        # path fires the alert/recovery instead of silently going keychain.
        with patch.object(self.bot, "_oauth_token_request", side_effect=Exception("boom")):
            self.assertEqual(self.bot.resolve_oauth_bearer(), "STALE")

    def test_resolve_env_fallback(self):
        with patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "ENVTOK"}):
            self.assertIsNone(self.bot._load_bot_auth())
            self.assertEqual(self.bot.resolve_oauth_bearer(), "ENVTOK")

    def test_file_takes_precedence_over_env(self):
        self.bot._save_bot_auth({"method": "setup_token", "token": "FILE"})
        with patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "ENVTOK"}):
            self.assertEqual(self.bot.resolve_oauth_bearer(), "FILE")

    # -- summary --

    def test_summary_keychain_when_unset(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
            s = self.bot.bot_auth_summary()
            self.assertEqual(s["source"], "keychain")
            self.assertIsNone(s["method"])

    def test_summary_oauth_reports_expiry(self):
        self.bot._save_bot_auth({
            "method": "oauth", "access_token": "AT", "refresh_token": "RT",
            "expires_at": time.time() + 1800})
        s = self.bot.bot_auth_summary()
        self.assertEqual(s["source"], "bot_token")
        self.assertEqual(s["method"], "oauth")
        self.assertTrue(0 < s["expires_in_s"] <= 1800)
        self.assertTrue(s["has_refresh"])

    # -- code exchange --

    def test_exchange_code_persists_oauth(self):
        with patch.object(self.bot, "_oauth_token_request",
                          return_value={"access_token": "AT", "refresh_token": "RT",
                                        "expires_in": 3600}) as m:
            data = self.bot._oauth_exchange_code("THECODE", "VERIFIER", "STATE")
        self.assertEqual(data["method"], "oauth")
        self.assertEqual(data["access_token"], "AT")
        # The payload carried the PKCE verifier and the auth-code grant.
        payload = m.call_args[0][0]
        self.assertEqual(payload["grant_type"], "authorization_code")
        self.assertEqual(payload["code"], "THECODE")
        self.assertEqual(payload["code_verifier"], "VERIFIER")

    def test_exchange_code_strips_state_suffix(self):
        with patch.object(self.bot, "_oauth_token_request",
                          return_value={"access_token": "AT", "expires_in": 3600}) as m:
            self.bot._oauth_exchange_code("CODE123#STATE456", "V", "S")
        self.assertEqual(m.call_args[0][0]["code"], "CODE123")

    def test_exchange_code_raises_without_access_token(self):
        with patch.object(self.bot, "_oauth_token_request", return_value={"error": "bad"}):
            with self.assertRaises(ValueError):
                self.bot._oauth_exchange_code("C", "V", "S")


class AuthCommandDispatch(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot
        self.mod = self.fixture.bot_module
        # Keep the live probe + keychain read hermetic.
        self.bot._auth_probe = lambda model="haiku": (True, "OK")
        self.bot._keychain_expiry_hours = lambda: None

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def _last_send(self) -> dict:
        for method, data in reversed(self.fixture.tg_calls):
            if method == "sendMessage":
                return data
        raise AssertionError("no sendMessage was made")

    def _all_texts(self):
        return [d["text"] for m, d in self.fixture.tg_calls if m == "sendMessage"]

    def test_auth_registered_in_handler_map(self):
        self.bot._handle_text("/auth")
        self.assertTrue(any("Auth do Claude" in t for t in self._all_texts()))

    def test_auth_login_stores_pending_and_sends_url(self):
        self.bot._handle_text("/auth login")
        self.assertIn("123456789", self.bot._pending_oauth)
        self.assertTrue(any("claude.com/cai/oauth/authorize" in t for t in self._all_texts()))

    def test_auth_set_rejects_bad_token(self):
        self.bot._handle_text("/auth set not-a-real-token")
        self.assertIn("inválido", self._last_send()["text"])
        self.assertIsNone(self.mod._load_bot_auth())

    def test_auth_set_installs_valid_token(self):
        self.bot._handle_text("/auth set sk-ant-oat01-abcdefghijklmnop")
        creds = self.mod._load_bot_auth()
        self.assertEqual(creds["method"], "setup_token")
        self.assertIn("instalado", self._last_send()["text"])

    def test_auth_logout_clears_token(self):
        self.mod._save_bot_auth({"method": "setup_token", "token": "sk-ant-x"})
        self.bot._handle_text("/auth logout")
        self.assertIsNone(self.mod._load_bot_auth())

    def test_auth_code_without_pending_is_rejected(self):
        self.bot._handle_text("/auth code SOMECODE")
        self.assertIn("Nenhum login", self._last_send()["text"])

    def test_auth_code_completes_exchange(self):
        self.bot._handle_text("/auth login")
        with patch.object(self.mod, "_oauth_token_request",
                          return_value={"access_token": "AT", "refresh_token": "RT",
                                        "expires_in": 3600}):
            self.bot._handle_text("/auth code THECODE123456789012345")
        self.assertEqual(self.mod._load_bot_auth()["access_token"], "AT")
        self.assertNotIn("123456789", self.bot._pending_oauth)  # cleared

    def test_bare_code_paste_when_login_pending(self):
        self.bot._handle_text("/auth login")
        with patch.object(self.mod, "_oauth_token_request",
                          return_value={"access_token": "BARE", "expires_in": 3600}):
            # No /auth prefix — a code-like token is intercepted.
            self.bot._handle_text("abcdefghijklmnopqrstuvwxyz0123456789")
        self.assertEqual(self.mod._load_bot_auth()["access_token"], "BARE")

    def test_normal_message_not_hijacked_as_code(self):
        self.bot._handle_text("/auth login")
        # A normal sentence (has spaces) must NOT be treated as a code.
        with patch.object(self.mod, "_oauth_exchange_code") as m:
            # Route through the interceptor guard only; we don't want a real run.
            with patch.object(self.bot, "_run_claude_prompt", lambda *a, **k: None):
                self.bot._handle_text("oi tudo bem com voce hoje")
            m.assert_not_called()
        self.assertIn("123456789", self.bot._pending_oauth)  # still pending


class AuthProactiveAlert(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def _texts(self):
        return [d["text"] for m, d in self.fixture.tg_calls if m == "sendMessage"]

    def test_alert_fires_and_throttles(self):
        self.bot._alert_auth_failure("401 invalid authentication credentials")
        first = [t for t in self._texts() if "Falha de autenticação" in t]
        self.assertEqual(len(first), 1)
        # Immediate second call is throttled (10-min window).
        self.bot._alert_auth_failure("401 again")
        again = [t for t in self._texts() if "Falha de autenticação" in t]
        self.assertEqual(len(again), 1)

    def test_alert_mentions_remote_recovery(self):
        self.bot._alert_auth_failure("401")
        joined = " ".join(self._texts())
        self.assertIn("/auth login", joined)


if __name__ == "__main__":
    unittest.main()
