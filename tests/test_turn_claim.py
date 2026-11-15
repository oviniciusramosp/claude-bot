"""Per-context turn claim: concurrent updates must not share one runner.

Regression for the 2026-10-16 18:19 crash: six backlogged updates arrived at
startup, each on its own handler thread. ``_run_claude_prompt`` checked
``runner.running`` (only set True deep inside ``ClaudeRunner.run()``), so two
threads both called ``run()`` on the SAME runner. The first run's
``_cleanup()`` closed the second run's pipes and set ``self.process = None``;
the second then crashed in ``_read_stream`` with ``AttributeError`` and the
turn fell through the whole model fallback chain.

The fix claims the context atomically (``ThreadContext.claim_turn``) on the
outermost call; losers take the /btw-or-queue path and the owner drains the
queue before releasing.
"""
import threading
import time
import unittest
from unittest.mock import MagicMock

from tests._botload import load_bot_module


class _Harness:
    """Minimal ClaudeTelegramBot stand-in: real claim/divert/release/drain
    logic, fake turn body that records overlap."""

    def __init__(self, bot_module, ctx, hold=0.2):
        cls = bot_module.ClaudeTelegramBot
        self.bot = cls.__new__(cls)
        self.bot._ctx_local = threading.local()
        self.bot.send_message = MagicMock(return_value=1)
        self.ctx = ctx
        self.hold = hold
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.calls = []
        self.bot._run_claude_prompt_owned = self._owned

    def _owned(self, prompt, _retry=0, **kwargs):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.calls.append((prompt, _retry, threading.get_ident()))
        try:
            time.sleep(self.hold)
        finally:
            with self.lock:
                self.active -= 1

    def send_from_new_thread(self, prompt, barrier=None):
        def _target():
            self.bot._ctx = self.ctx
            if barrier is not None:
                barrier.wait()
            self.bot._run_claude_prompt(prompt)
        t = threading.Thread(target=_target, daemon=True)
        t.start()
        return t


class TestTurnClaim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def _ctx(self):
        return self.bot.ThreadContext(chat_id="123456789")

    def test_concurrent_messages_never_overlap_and_none_is_lost(self):
        ctx = self._ctx()
        h = _Harness(self.bot, ctx)
        prompts = [f"msg-{i}" for i in range(6)]  # the 6-update backlog
        barrier = threading.Barrier(len(prompts))
        threads = [h.send_from_new_thread(p, barrier) for p in prompts]
        for t in threads:
            t.join(timeout=10)
            self.assertFalse(t.is_alive())

        self.assertEqual(h.max_active, 1, "two turns ran on one context at once")
        delivered = "\n\n".join(c[0] for c in h.calls)
        for p in prompts:
            self.assertIn(p, delivered, f"{p} was lost")
        self.assertIsNone(ctx.turn_owner, "claim leaked after all turns finished")
        self.assertEqual(ctx.pending, [])

    def test_nested_calls_on_owner_thread_reenter(self):
        """_retry / _fallback_model / queue-drain recursion must not divert."""
        ctx = self._ctx()
        h = _Harness(self.bot, ctx, hold=0)
        seen = []

        def owned(prompt, _retry=0, **kwargs):
            seen.append(_retry)
            if _retry == 0:
                h.bot._run_claude_prompt(prompt, _retry=1, _fallback_model="sonnet")
        h.bot._run_claude_prompt_owned = owned
        h.bot._ctx = ctx
        h.bot._run_claude_prompt("hi")

        self.assertEqual(seen, [0, 1])
        self.assertIsNone(ctx.turn_owner)
        h.bot.send_message.assert_not_called()

    def test_loser_uses_btw_when_runner_is_running(self):
        ctx = self._ctx()
        runner = MagicMock()
        runner.running = True
        runner.send_btw.return_value = True
        ctx.runner = runner
        ctx.turn_owner = -1  # some other thread owns the turn
        h = _Harness(self.bot, ctx)
        h.bot._ctx = ctx
        saved = self.bot.BUSY_MESSAGE_MODE
        self.bot.BUSY_MESSAGE_MODE = "now"  # "ask" shows a card instead
        self.addCleanup(setattr, self.bot, "BUSY_MESSAGE_MODE", saved)
        h.bot._run_claude_prompt("extra context")

        runner.send_btw.assert_called_once_with("extra context")
        self.assertEqual(ctx.pending, [])
        self.assertEqual(h.calls, [])

    def test_loser_queues_while_owner_is_still_starting(self):
        """runner.running is still False during pre-run setup — the old race window."""
        ctx = self._ctx()
        ctx.runner = self.bot.ClaudeRunner()
        self.assertFalse(ctx.runner.running)
        ctx.turn_owner = -1
        h = _Harness(self.bot, ctx)
        h.bot._ctx = ctx
        h.bot._run_claude_prompt("second")

        self.assertEqual(ctx.pending, ["second"])
        self.assertEqual(h.calls, [])

    def test_release_drains_prompt_queued_during_turn(self):
        ctx = self._ctx()
        h = _Harness(self.bot, ctx, hold=0)
        first = True

        def owned(prompt, _retry=0, **kwargs):
            nonlocal first
            h.calls.append((prompt, _retry, threading.get_ident()))
            if first:
                first = False
                # Simulates a loser enqueuing after the in-turn drain already ran.
                with ctx.pending_lock:
                    ctx.pending.append("late")
        h.bot._run_claude_prompt_owned = owned
        h.bot._ctx = ctx
        h.bot._run_claude_prompt("first")

        self.assertEqual([c[0] for c in h.calls], ["first", "late"])
        self.assertIsNone(ctx.turn_owner)

    def test_claim_released_when_turn_raises(self):
        ctx = self._ctx()
        h = _Harness(self.bot, ctx)

        def boom(prompt, _retry=0, **kwargs):
            raise RuntimeError("turn exploded")
        h.bot._run_claude_prompt_owned = boom
        h.bot._ctx = ctx
        with self.assertRaises(RuntimeError):
            h.bot._run_claude_prompt("x")
        self.assertIsNone(ctx.turn_owner)


class TestRunnerProcessSwap(unittest.TestCase):
    """Defense in depth: a swapped self.process must not crash the reader."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def _proc(self, lines):
        proc = MagicMock()
        proc.stdout = iter(lines)
        proc.stderr = MagicMock()
        proc.stderr.read.return_value = "warn: something"
        proc.returncode = 0
        proc.pid = 99
        return proc

    def test_read_stream_survives_process_cleared_mid_stream(self):
        runner = self.bot.ClaudeRunner()

        def lines():
            yield '{"type":"system","subtype":"init"}\n'
            runner.process = None  # a concurrent _cleanup() did this
            yield "\n"
        proc = self._proc(lines())
        runner.process = proc
        runner._read_stream()  # used to raise AttributeError on .stderr
        proc.stderr.read.assert_called_once()
        self.assertEqual(runner.stderr_text, "warn: something")

    def test_read_stream_without_process_reports_error(self):
        runner = self.bot.ClaudeRunner()
        runner.process = None
        runner._read_stream()
        self.assertTrue(runner.error_text)

    def test_cleanup_keeps_a_process_it_did_not_own(self):
        runner = self.bot.ClaudeRunner()
        mine = self._proc([])
        mine.stdout = MagicMock()
        theirs = self._proc([])

        def swap(timeout=None):
            runner.process = theirs
            return 0
        mine.wait.side_effect = swap
        runner.process = mine
        runner._cleanup()
        self.assertIs(runner.process, theirs)
        self.assertEqual(runner.exit_code, 0)

    def test_codex_runner_read_stream_survives_swap(self):
        runner = self.bot.CodexRunner()

        def lines():
            runner.process = None
            yield "\n"
        proc = self._proc(lines())
        runner.process = proc
        runner._read_stream()
        proc.stderr.read.assert_called_once()


if __name__ == "__main__":
    unittest.main()
