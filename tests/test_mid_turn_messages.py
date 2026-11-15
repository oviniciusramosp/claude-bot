"""Messages sent while a turn is running (v3.86).

Since v3.81 the prompt travels on the CLI's stdin, and stdin was closed right
after it — so every mid-turn message failed to reach the running turn and was
queued. The runner now keeps stdin open until the turn's `result`, writing a
mid-turn message as another stream-json user message (verified live on CLI
2.1.292: a message written during tool calls is folded into the same answer;
one written right at the end runs as one more turn with its own result).

On top of that the bot asks what to do with such a message:
[⚡ Mandar agora] [⏳ Depois] [🛑 Parar e mandar], defaulting after
BUSY_CHOICE_SECONDS.
"""
import json
import threading
import unittest
from unittest.mock import MagicMock

from tests._botload import load_bot_module


def _primed_runner(bot):
    """A ClaudeRunner mid-turn: running, stdin open, initial prompt written."""
    r = bot.ClaudeRunner()
    r.running = True
    pipe = MagicMock()
    r._stdin = pipe
    r._stdin_open = True
    r._stdin_primed = True
    return r, pipe


def _written(pipe):
    return [json.loads(c.args[0]) for c in pipe.write.call_args_list]


class RunnerInjection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_message_is_written_as_a_stream_json_user_message(self):
        r, pipe = _primed_runner(self.bot)
        self.assertTrue(r.send_btw("e também o saldo"))
        msg = _written(pipe)[0]
        self.assertEqual(msg["type"], "user")
        self.assertEqual(msg["message"]["content"][0]["text"], "e também o saldo")
        self.assertTrue(pipe.write.call_args.args[0].endswith("\n"))
        self.assertEqual(r.injected_count, 1)

    def test_no_legacy_slash_btw_prefix(self):
        r, pipe = _primed_runner(self.bot)
        r.send_btw("oi")
        self.assertNotIn("/btw", pipe.write.call_args.args[0])

    def test_message_before_prompt_is_written_waits_for_it(self):
        r, pipe = _primed_runner(self.bot)
        r._stdin_primed = False
        self.assertTrue(r.send_btw("cedo"))
        pipe.write.assert_not_called()
        r._prime_stdin(pipe, '{"type":"user","first":1}\n')
        writes = [c.args[0] for c in pipe.write.call_args_list]
        self.assertIn('"first"', writes[0])
        self.assertIn("cedo", writes[1])

    def test_result_closes_stdin_and_later_messages_are_refused(self):
        r, pipe = _primed_runner(self.bot)
        r._handle_event({"type": "result", "result": "pronto", "is_error": False})
        pipe.close.assert_called_once()
        self.assertFalse(r.can_inject())
        self.assertFalse(r.send_btw("tarde demais"))

    def test_message_accepted_before_priming_is_flushed_on_close(self):
        r, pipe = _primed_runner(self.bot)
        r._stdin_primed = False
        r.send_btw("na fila interna")
        r._close_stdin()
        self.assertIn("na fila interna", pipe.write.call_args.args[0])
        pipe.close.assert_called_once()

    def test_not_running_refuses(self):
        r, _ = _primed_runner(self.bot)
        r.running = False
        self.assertFalse(r.send_btw("x"))

    def test_broken_pipe_refuses_so_the_bot_queues(self):
        r, pipe = _primed_runner(self.bot)
        pipe.write.side_effect = BrokenPipeError("gone")
        self.assertFalse(r.send_btw("x"))
        self.assertFalse(r.can_inject())

    def test_extra_turn_keeps_both_answers(self):
        r, _ = _primed_runner(self.bot)
        r._handle_event({"type": "assistant", "message": {"content": [{"type": "text", "text": "hello"}]}})
        r._handle_event({"type": "result", "result": "hello"})
        r._handle_event({"type": "assistant", "message": {"content": [{"type": "text", "text": "world"}]}})
        r._handle_event({"type": "result", "result": "world"})
        self.assertEqual(r.result_text, "hello\n\nworld")
        self.assertEqual(r.accumulated_text, "hello\n\nworld")

    def test_single_turn_result_unchanged(self):
        r, _ = _primed_runner(self.bot)
        r._handle_event({"type": "result", "result": "só uma"})
        self.assertEqual(r.result_text, "só uma")

    def test_codex_cannot_inject(self):
        self.assertFalse(self.bot.CodexRunner().can_inject())


class _BotCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def setUp(self):
        cls = self.m.ClaudeTelegramBot
        self.bot = cls.__new__(cls)
        self.bot._ctx_local = threading.local()
        self.bot.send_message = MagicMock(return_value=555)
        self.bot.edit_message = MagicMock(return_value=True)
        self.bot.answer_callback = MagicMock()
        self.bot._run_claude_prompt = MagicMock()
        self.ctx = self.m.ThreadContext(chat_id="123456789")
        self.ctx.turn_owner = -1  # another thread owns the running turn
        self.runner = MagicMock(running=True)
        self.runner.can_inject.return_value = True
        self.runner.send_btw.return_value = True
        self.ctx.runner = self.runner
        self.bot._ctx = self.ctx
        saved = (self.m.BUSY_MESSAGE_MODE, self.m.BUSY_CHOICE_SECONDS)
        self.m.BUSY_MESSAGE_MODE = "ask"
        self.m.BUSY_CHOICE_SECONDS = 3600  # timers never fire inside a test
        self.addCleanup(self._restore, saved)

    def _restore(self, saved):
        self.m.BUSY_MESSAGE_MODE, self.m.BUSY_CHOICE_SECONDS = saved
        choices, _ = self.bot._busy_state()
        for e in choices.values():
            if e.get("timer"):
                e["timer"].cancel()

    def _offer(self, prompt="mais uma coisa", mid=42):
        self.bot._divert_busy_prompt(self.ctx, prompt, user_msg_id=mid)
        choices, _ = self.bot._busy_state()
        self.assertEqual(len(choices), 1)
        return next(iter(choices))

    def _buttons(self):
        markup = self.bot.send_message.call_args.kwargs["reply_markup"]
        return [b["callback_data"].rsplit(":", 1)[1] for b in markup["inline_keyboard"][0]]


class ChoiceCard(_BotCase):
    def test_card_offers_three_choices_and_does_not_send_yet(self):
        self._offer()
        self.assertEqual(self._buttons(), ["now", "later", "stop"])
        self.runner.send_btw.assert_not_called()
        self.assertEqual(self.ctx.pending, [])
        kw = self.bot.send_message.call_args.kwargs
        self.assertEqual(kw["reply_to_message_id"], 42)
        self.assertTrue(kw["disable_notification"])

    def test_callback_data_fits_telegram_limit(self):
        self._offer()
        markup = self.bot.send_message.call_args.kwargs["reply_markup"]
        for b in markup["inline_keyboard"][0]:
            self.assertLessEqual(len(b["callback_data"].encode()), 64)

    def test_no_send_now_button_when_turn_cannot_take_input(self):
        self.runner.can_inject.return_value = False
        self._offer()
        self.assertEqual(self._buttons(), ["later", "stop"])
        self.assertIn("mando depois", self.bot.send_message.call_args.args[0])

    def test_now_injects_into_running_turn(self):
        cid = self._offer()
        self.assertTrue(self.bot._resolve_busy_choice(cid, "now"))
        self.runner.send_btw.assert_called_once_with("mais uma coisa")
        self.assertEqual(self.ctx.pending, [])
        self.bot.edit_message.assert_called_with(555, self.m.BUSY_TEXT_NOW)

    def test_now_falls_back_to_queue_when_injection_fails(self):
        self.runner.send_btw.return_value = False
        cid = self._offer()
        self.bot._resolve_busy_choice(cid, "now")
        self.assertEqual(self.ctx.pending, [("mais uma coisa", 42)])
        self.bot.edit_message.assert_called_with(555, self.m.BUSY_TEXT_LATER)

    def test_later_queues_with_its_message_id(self):
        cid = self._offer()
        self.bot._resolve_busy_choice(cid, "later")
        self.runner.send_btw.assert_not_called()
        self.assertEqual(self.ctx.pending, [("mais uma coisa", 42)])

    def test_stop_cancels_and_goes_first_in_queue(self):
        self.ctx.pending.append("antiga")
        done = threading.Event()
        self.runner.cancel.side_effect = lambda: done.set()
        cid = self._offer()
        self.bot._resolve_busy_choice(cid, "stop")
        self.assertTrue(done.wait(2), "running turn was not cancelled")
        self.assertEqual(self.ctx.pending[0], ("mais uma coisa", 42))
        self.bot.edit_message.assert_called_with(555, self.m.BUSY_TEXT_STOP)

    def test_turn_already_over_runs_it_now(self):
        cid = self._offer()
        self.ctx.turn_owner = None
        self.runner.running = False
        self.bot._resolve_busy_choice(cid, "later")
        self.bot._run_claude_prompt.assert_called_once_with("mais uma coisa", user_msg_id=42)

    def test_second_tap_is_ignored(self):
        cid = self._offer()
        self.assertTrue(self.bot._resolve_busy_choice(cid, "now"))
        self.assertFalse(self.bot._resolve_busy_choice(cid, "stop"))
        self.runner.cancel.assert_not_called()

    def test_auto_choice_is_marked(self):
        cid = self._offer()
        self.bot._resolve_busy_choice(cid, "later", auto=True)
        self.assertIn("automático", self.bot.edit_message.call_args.args[1])

    def test_turn_end_moves_unanswered_card_to_queue(self):
        self._offer()
        self.bot._flush_busy_choices(self.ctx)
        self.assertEqual(self.ctx.pending, [("mais uma coisa", 42)])
        choices, _ = self.bot._busy_state()
        self.assertEqual(choices, {})
        self.bot.edit_message.assert_called_with(555, self.m.BUSY_TEXT_ENDED)

    def test_release_runs_unanswered_message(self):
        self._offer()
        self.ctx.turn_owner = threading.get_ident()
        self.bot._process_pending = MagicMock(
            side_effect=lambda: self.ctx.pending.clear())
        self.bot._release_turn(self.ctx)
        self.bot._process_pending.assert_called_once()
        self.assertIsNone(self.ctx.turn_owner)

    def test_card_not_delivered_applies_default_immediately(self):
        self.bot.send_message.return_value = None
        self.bot._divert_busy_prompt(self.ctx, "x", user_msg_id=42)
        self.runner.send_btw.assert_called_once_with("x")
        choices, _ = self.bot._busy_state()
        self.assertEqual(choices, {})

    def test_callback_routes_and_answers(self):
        cid = self._offer()
        self.bot._handle_callback({"id": "cb1", "data": f"busy:{cid}:later",
                                   "message": {"message_id": 555}})
        self.bot.answer_callback.assert_called_once()
        self.assertEqual(self.ctx.pending, [("mais uma coisa", 42)])

    def test_callback_for_resolved_card_says_so(self):
        self.bot._handle_callback({"id": "cb1", "data": "busy:deadbeef00:now",
                                   "message": {"message_id": 555}})
        self.assertIn("já foi", self.bot.answer_callback.call_args.args[1])


class Modes(_BotCase):
    def test_now_mode_injects_without_card(self):
        self.m.BUSY_MESSAGE_MODE = "now"
        self.bot._divert_busy_prompt(self.ctx, "direto", user_msg_id=42)
        self.runner.send_btw.assert_called_once_with("direto")
        self.bot.send_message.assert_called_once_with(
            self.m.BUSY_TEXT_NOW, disable_notification=True)

    def test_queue_mode_never_injects(self):
        self.m.BUSY_MESSAGE_MODE = "queue"
        self.bot._divert_busy_prompt(self.ctx, "espera", user_msg_id=42)
        self.runner.send_btw.assert_not_called()
        self.assertEqual(self.ctx.pending, [("espera", 42)])

    def test_explicit_btw_command_still_sends_now(self):
        self.bot.cmd_btw("via comando")
        self.runner.send_btw.assert_called_once_with("via comando")


if __name__ == "__main__":
    unittest.main()
