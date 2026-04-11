"""Regression tests: per-thread isolation of the active ThreadContext.

The bot used to keep a single `self._ctx` instance attribute that was mutated
by every code path (polling, update handler, routines, pipelines, callbacks).
When two Telegram topics ran Claude prompts in parallel, the response of one
leaked into the other because `send_message` / `edit_message` resolved
`self._chat_id` (and `self._ctx.thread_id`) at SEND time from whatever
`self._ctx` happened to be at that instant.

The fix made `self._ctx` thread-local. These tests guarantee that:

1. Two threads writing different ThreadContexts to `bot._ctx` see only their
   own value, even under tight interleaving — without the fix this races
   deterministically.
2. `bot._chat_id` resolved inside a thread always reflects that thread's
   ThreadContext, not whatever a sibling thread set.
3. `send_message` called concurrently from two threads addresses each
   message to the correct (chat_id, thread_id) pair.
4. The fallback for code paths with no per-thread context (e.g. webhook
   server error notifications) returns the FIRST configured chat ID and
   never the raw comma-separated env var.
"""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._botload import load_bot_module


class _BotFixture:
    """Minimal ClaudeTelegramBot with all I/O mocked. Patterned after test_bot_integration."""

    def __init__(self, tmp_root: Path, telegram_chat_id: str = "123456789"):
        self.tmp_root = tmp_root
        self.home = tmp_root / "home"
        self.vault = tmp_root / "vault"
        self.home.mkdir()
        self.bot_module = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        # _botload always forces TELEGRAM_CHAT_ID="123456789" at the env level
        # before import; the bot captures it as a module-level constant. To
        # exercise CSV/single-id fallbacks we override the constant directly.
        self.bot_module.TELEGRAM_CHAT_ID = telegram_chat_id
        self.tg_calls: list[tuple[str, dict]] = []
        self.tg_calls_lock = threading.Lock()

        self._patches = [
            patch.object(self.bot_module.ClaudeTelegramBot, "_start_control_server", lambda self: None),
            patch.object(self.bot_module.ClaudeTelegramBot, "_start_webhook_server", lambda self: None),
            patch.object(
                self.bot_module.ClaudeTelegramBot,
                "_check_voice_tools",
                lambda self: {"can_transcribe": False, "ffmpeg": "", "hear": ""},
            ),
            patch.object(
                self.bot_module.ClaudeTelegramBot,
                "_check_tts_tools",
                lambda self: {"can_synthesize": False, "edge_tts": "", "say": "", "ffmpeg": ""},
            ),
            patch.object(self.bot_module.RoutineScheduler, "start", lambda self: None),
            patch.object(self.bot_module.RoutineScheduler, "stop", lambda self: None),
        ]
        for p in self._patches:
            p.start()

        self.bot = self.bot_module.ClaudeTelegramBot()

        def fake_tg_request(method, data=None, timeout=15):
            with self.tg_calls_lock:
                self.tg_calls.append((method, dict(data or {})))
                msg_id = len(self.tg_calls)
            return {"ok": True, "result": {"message_id": msg_id}}

        self.bot.tg_request = fake_tg_request

    def cleanup(self):
        for p in self._patches:
            p.stop()


class CtxThreadLocal(unittest.TestCase):
    """Each thread sees its own _ctx slot."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def test_two_threads_do_not_share_ctx(self):
        ctx_a = self.bot._get_context("100", 1)
        ctx_b = self.bot._get_context("200", 2)

        errors: list[str] = []
        barrier = threading.Barrier(2)

        def worker(ctx, label, mismatches):
            barrier.wait()
            for _ in range(500):
                self.bot._ctx = ctx
                # Tight interleaving — sibling thread is doing the same dance
                got_ctx = self.bot._ctx
                got_chat = self.bot._chat_id
                if got_ctx is not ctx:
                    mismatches.append(f"{label}: ctx swapped under us")
                if got_chat != ctx.chat_id:
                    mismatches.append(f"{label}: chat_id was {got_chat!r} expected {ctx.chat_id!r}")

        m_a: list[str] = []
        m_b: list[str] = []
        t1 = threading.Thread(target=worker, args=(ctx_a, "A", m_a))
        t2 = threading.Thread(target=worker, args=(ctx_b, "B", m_b))
        t1.start(); t2.start()
        t1.join(); t2.join()

        self.assertEqual(m_a, [], f"Thread A saw cross-talk: {m_a[:3]}")
        self.assertEqual(m_b, [], f"Thread B saw cross-talk: {m_b[:3]}")

    def test_main_thread_ctx_does_not_leak_to_new_thread(self):
        """A new thread starts with _ctx == None regardless of what the parent set."""
        ctx_main = self.bot._get_context("999", 7)
        self.bot._ctx = ctx_main
        self.assertIs(self.bot._ctx, ctx_main)

        observed: dict = {}
        def child():
            observed["ctx"] = self.bot._ctx
        t = threading.Thread(target=child)
        t.start(); t.join()

        self.assertIsNone(observed["ctx"], "Child thread inherited parent's _ctx")
        # Parent thread still sees its own value
        self.assertIs(self.bot._ctx, ctx_main)


class SendMessageConcurrentRouting(unittest.TestCase):
    """send_message called from concurrent threads must address each message
    to that thread's own context, not whichever ctx happens to be 'last set'."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def test_concurrent_send_message_routes_correctly(self):
        ctx_palmeiras = self.bot._get_context("-1003728739949", 17)
        ctx_crypto = self.bot._get_context("-1003728739949", 38)

        N = 100
        barrier = threading.Barrier(2)

        def sender(ctx, label):
            self.bot._ctx = ctx
            barrier.wait()
            for i in range(N):
                self.bot.send_message(f"{label}-{i}", parse_mode=None)

        t1 = threading.Thread(target=sender, args=(ctx_palmeiras, "palmeiras"))
        t2 = threading.Thread(target=sender, args=(ctx_crypto, "crypto"))
        t1.start(); t2.start()
        t1.join(); t2.join()

        # Every recorded sendMessage must have its label match the chat/thread
        with self.fixture.tg_calls_lock:
            calls = list(self.fixture.tg_calls)

        leaks: list[str] = []
        for method, data in calls:
            if method != "sendMessage":
                continue
            text = data.get("text", "")
            chat = str(data.get("chat_id", ""))
            thread = data.get("message_thread_id")
            if text.startswith("palmeiras-"):
                if chat != "-1003728739949" or thread != 17:
                    leaks.append(f"palmeiras text -> chat={chat} thread={thread}")
            elif text.startswith("crypto-"):
                if chat != "-1003728739949" or thread != 38:
                    leaks.append(f"crypto text -> chat={chat} thread={thread}")
            else:
                leaks.append(f"unknown text -> {text!r}")

        self.assertEqual(leaks, [], f"Cross-talk detected: {leaks[:5]}")
        # Sanity: we recorded 2*N sends
        send_count = sum(1 for m, _ in calls if m == "sendMessage")
        self.assertEqual(send_count, 2 * N)


class FallbackChatIdParsesCsv(unittest.TestCase):
    """When _ctx is None, _chat_id must return the first authorized chat,
    not the raw comma-separated TELEGRAM_CHAT_ID env var."""

    def test_csv_env_returns_first_id(self):
        td = tempfile.TemporaryDirectory()
        try:
            fixture = _BotFixture(Path(td.name), telegram_chat_id="111,222,333")
            try:
                bot = fixture.bot
                # In a fresh thread, _ctx is None — fallback path
                results: dict = {}
                def child():
                    results["chat_id"] = bot._chat_id
                t = threading.Thread(target=child)
                t.start(); t.join()
                self.assertEqual(results["chat_id"], "111")
            finally:
                fixture.cleanup()
        finally:
            td.cleanup()

    def test_single_id_env_unchanged(self):
        td = tempfile.TemporaryDirectory()
        try:
            fixture = _BotFixture(Path(td.name), telegram_chat_id="555")
            try:
                bot = fixture.bot
                results: dict = {}
                def child():
                    results["chat_id"] = bot._chat_id
                t = threading.Thread(target=child)
                t.start(); t.join()
                self.assertEqual(results["chat_id"], "555")
            finally:
                fixture.cleanup()
        finally:
            td.cleanup()


if __name__ == "__main__":
    unittest.main()
