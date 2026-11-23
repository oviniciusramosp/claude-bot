"""Live drafts (sendMessageDraft / sendRichMessageDraft), the native stop
(``stopped_message_generation``) and message effects (``message_effect_id``).

All Telegram I/O is faked: ``tg_request`` / ``_tg_edit`` / ``_rich_request``
by the rich-messages fixture, and ``_tg_call`` (the transport drafts use) here.
"""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from tests.test_rich_messages import _BotFixture


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fx = _BotFixture(Path(self._td.name))
        self.bot, self.m = self.fx.bot, self.fx.m
        m = self.m
        # Module-level switches are process-wide: reset them per test.
        m.LIVE_DRAFTS_ENABLED = True
        m.MESSAGE_EFFECTS_ENABLED = True
        m._DRAFTS_RUNTIME_OFF = False
        m._RICH_DRAFT_RUNTIME_OFF = False
        m._EFFECTS_RUNTIME_OFF = False
        m._RICH_RUNTIME_OFF = False
        m.NOTIFY_DONE_AFTER_SECONDS = 20
        m.SHOW_SIGNATURE = False
        self.draft_calls = []        # (method, data)
        self.draft_results = []      # queue of TgResult; default ok
        self._lock = threading.Lock()

        def fake_tg_call(method, data=None, **kw):
            with self._lock:
                self.draft_calls.append((method, dict(data or {})))
                if self.draft_results:
                    res = self.draft_results.pop(0)
                else:
                    res = m.TgResult(ok=True, status=200, body={"ok": True, "result": True})
            return self.bot._tg_set_last(res)

        self.bot._tg_call = fake_tg_call
        self.bot._active_msgs = MagicMock()
        self.bot.set_reaction = MagicMock(return_value=True)   # raw urlopen otherwise
        self.bot._is_authorized = lambda cid: cid in ("42", "-1001234")

    def tearDown(self):
        self.fx.cleanup()
        self._td.cleanup()

    def err(self, status, description):
        return self.m.TgResult(status=status, description=description)

    def ctx(self, chat_id="42", thread_id=None, user_msg_id=9):
        ctx = self.m.ThreadContext(chat_id=chat_id, thread_id=thread_id)
        ctx.user_msg_id = user_msg_id
        self.bot._ctx = ctx
        self.bot._contexts[(chat_id, thread_id)] = ctx
        return ctx

    def runner(self, snapshot="", text="", exit_code=0, elapsed=1.0, entries=None):
        r = MagicMock()
        r.get_snapshot.return_value = snapshot
        r.get_reasoning_entries.return_value = entries or []
        r.result_text = text
        r.accumulated_text = snapshot
        r.error_text = ""
        r.stderr_text = ""
        r.exit_code = exit_code
        r.cost_usd = 0
        r.start_time = time.time() - elapsed
        r.running = True
        return r


class OpenDraft(_Base):
    def test_private_chat_opens_thinking_draft_and_no_placeholder(self):
        ctx = self.ctx(thread_id=5)
        self.assertTrue(self.bot._drafts_usable(ctx))
        self.assertTrue(self.bot._start_draft_turn(ctx))
        method, data = self.draft_calls[0]
        self.assertEqual(method, "sendMessageDraft")
        self.assertEqual(data["chat_id"], 42)
        self.assertEqual(data["message_thread_id"], 5)
        self.assertEqual(data["text"], "")              # native "Thinking…"
        self.assertNotEqual(data["draft_id"], 0)
        self.assertTrue(data["can_stop"])
        self.assertTrue(data["keep_on_stop"])
        self.assertEqual(ctx.draft_id, data["draft_id"])
        self.assertIsNone(ctx.stream_msg_id)
        self.assertEqual(self.fx.html_sends(), [])

    def test_draft_ids_are_unique_and_nonzero(self):
        ids = {self.bot._next_draft_id() for _ in range(50)}
        self.assertEqual(len(ids), 50)
        self.assertNotIn(0, ids)
        self.assertTrue(all(0 < i < 2 ** 31 for i in ids))

    def test_groups_never_use_drafts(self):
        ctx = self.ctx(chat_id="-1001234", thread_id=3)
        self.assertFalse(self.bot._drafts_usable(ctx))

    def test_env_off(self):
        self.m.LIVE_DRAFTS_ENABLED = False
        self.assertFalse(self.bot._drafts_usable(self.ctx()))


class KillSwitch(_Base):
    def test_unknown_method_trips_switch_and_falls_back_to_placeholder(self):
        ctx = self.ctx()
        self.draft_results = [self.err(404, "Not Found")]
        with self.assertLogs("claude-bot", level="WARNING") as logs:
            self.assertFalse(self.bot._start_draft_turn(ctx))
        self.assertTrue(self.m._DRAFTS_RUNTIME_OFF)
        self.assertEqual(ctx.draft_id, 0)
        self.assertTrue(any("Live drafts" in l for l in logs.output))
        self.assertFalse(self.bot._drafts_usable(ctx))
        # The turn then gets the edit-path placeholder.
        self.bot._send_stream_placeholder(ctx)
        self.assertTrue(self.fx.html_sends()[0]["text"].startswith("⏳"))
        self.assertIsNotNone(ctx.stream_msg_id)

    def test_private_only_error_trips_switch(self):
        ctx = self.ctx()
        self.draft_results = [self.err(400, "Bad Request: method is available only for private chats")]
        self.assertFalse(self.bot._start_draft_turn(ctx))
        self.assertTrue(self.m._DRAFTS_RUNTIME_OFF)

    def test_one_off_failure_does_not_trip_switch(self):
        ctx = self.ctx(thread_id=99)
        self.draft_results = [self.err(400, "Bad Request: message thread not found")]
        self.assertFalse(self.bot._start_draft_turn(ctx))
        self.assertFalse(self.m._DRAFTS_RUNTIME_OFF)
        self.assertEqual(ctx.draft_id, 0)

    def test_switch_logs_once(self):
        with self.assertLogs("claude-bot", level="WARNING") as logs:
            self.m._disable_drafts_runtime("a")
            self.m._disable_drafts_runtime("b")
        self.assertEqual(len([l for l in logs.output if "Live drafts" in l]), 1)

    def test_rich_draft_unsupported_falls_back_to_plain_draft(self):
        ctx = self.ctx()
        ctx.draft_id = 7
        self.draft_results = [self.err(400, "Bad Request: rich message must be non-empty")]
        status = self.bot._send_draft(ctx, "**oi**")
        self.assertEqual(status, "ok")
        self.assertEqual([m for m, _ in self.draft_calls],
                         ["sendRichMessageDraft", "sendMessageDraft"])
        self.assertTrue(self.m._RICH_DRAFT_RUNTIME_OFF)
        self.assertFalse(self.m._DRAFTS_RUNTIME_OFF)
        self.assertEqual(self.draft_calls[1][1]["text"], "<b>oi</b>")
        self.assertEqual(self.draft_calls[1][1]["parse_mode"], "HTML")

    def test_mid_stream_switch_moves_turn_to_placeholder(self):
        ctx = self.ctx()
        ctx.draft_id = 7
        self.draft_results = [self.err(404, "Not Found"), self.err(404, "Not Found")]
        self.bot._stream_draft_tick(ctx, self.runner(snapshot="parcial"), time.time() + 5)
        self.assertEqual(ctx.draft_id, 0)
        self.assertIsNotNone(ctx.stream_msg_id)


class DraftStreaming(_Base):
    def setUp(self):
        super().setUp()
        # Live answer text in drafts is opt-in since v3.94 (LIVE_DRAFT_ANSWER).
        self._saved_answer = self.m.LIVE_DRAFT_ANSWER
        self.m.LIVE_DRAFT_ANSWER = True
        self.addCleanup(setattr, self.m, "LIVE_DRAFT_ANSWER", self._saved_answer)

    def test_answer_streams_as_rich_draft_with_same_id(self):
        ctx = self.ctx()
        ctx.draft_id = 1234
        now = time.time()
        ctx.last_draft_time = now - 10
        self.bot._stream_draft_tick(ctx, self.runner(snapshot="Olá **mundo**"), now)
        method, data = self.draft_calls[-1]
        self.assertEqual(method, "sendRichMessageDraft")
        self.assertEqual(data["draft_id"], 1234)
        self.assertEqual(data["rich_message"], {"markdown": "Olá **mundo**"})
        self.assertTrue(data["can_stop"])
        self.assertEqual(ctx.last_draft_len, len("Olá **mundo**"))
        self.assertEqual(self.fx.html_edits(), [])     # nothing edited

    def test_plain_draft_when_rich_is_off(self):
        self.m.RICH_MESSAGES_ENABLED = False
        ctx = self.ctx()
        ctx.draft_id = 3
        self.bot._stream_draft_tick(ctx, self.runner(snapshot="**x**"), time.time() + 10)
        method, data = self.draft_calls[-1]
        self.assertEqual(method, "sendMessageDraft")
        self.assertEqual(data["text"], "<b>x</b>")

    def test_unchanged_content_waits_for_keepalive(self):
        ctx = self.ctx()
        ctx.draft_id = 3
        now = time.time()
        ctx.last_draft_time = now
        ctx.last_draft_len = len("abc")
        r = self.runner(snapshot="abc")
        self.bot._stream_draft_tick(ctx, r, now + 5)
        self.assertEqual(self.draft_calls, [])
        self.bot._stream_draft_tick(ctx, r, now + self.m.LIVE_DRAFT_KEEPALIVE + 0.1)
        self.assertEqual(len(self.draft_calls), 1)     # refreshed inside the 30s window
        self.assertLess(self.m.LIVE_DRAFT_KEEPALIVE, 30)

    def test_new_content_respects_interval(self):
        ctx = self.ctx()
        ctx.draft_id = 3
        now = time.time()
        ctx.last_draft_time = now
        self.bot._stream_draft_tick(ctx, self.runner(snapshot="novo"), now + 0.5)
        self.assertEqual(self.draft_calls, [])
        self.bot._stream_draft_tick(ctx, self.runner(snapshot="novo"), now + 2)
        self.assertEqual(len(self.draft_calls), 1)

    def test_reasoning_shown_before_the_answer(self):
        ctx = self.ctx()
        ctx.draft_id = 3
        r = self.runner(entries=[("tool", "🔧 Read arquivo.md")])
        self.bot._stream_draft_tick(ctx, r, time.time() + 10)
        md = self.draft_calls[-1][1]["rich_message"]["markdown"]
        self.assertIn("Raciocínio", md)
        self.assertEqual(ctx.last_draft_steps, 1)

    def test_dropped_draft_is_not_waited_on(self):
        ctx = self.ctx()
        ctx.draft_id = 3
        self.draft_results = [self.m.TgResult(status=429, dropped=True, description="throttled")]
        self.assertEqual(self.bot._send_draft(ctx, "x"), "dropped")
        self.assertEqual(len(self.draft_calls), 1)
        self.assertFalse(self.m._DRAFTS_RUNTIME_OFF)

    def test_drafts_are_rate_limited_and_droppable(self):
        # Drafts go through the shared limiter as a "send…" method.
        self.assertTrue(self.m._tg_method_is_rate_limited("sendMessageDraft"))
        self.assertTrue(self.m._tg_method_is_rate_limited("sendRichMessageDraft"))

    def test_no_more_drafts_after_stop(self):
        ctx = self.ctx()
        ctx.draft_id = 3
        ctx.draft_stopped = True
        self.bot._stream_draft_tick(ctx, self.runner(snapshot="x"), time.time() + 60)
        self.assertEqual(self.draft_calls, [])


class _Finalize(_Base):
    def turn(self, elapsed=1.0, text="Resposta **final**", exit_code=0, chat_id="42",
             stopped=False):
        ctx = self.ctx(chat_id=chat_id, thread_id=5)
        ctx.draft_id = 555
        ctx.draft_stopped = stopped
        runner = self.m.ClaudeRunner()
        runner.result_text = text
        runner.exit_code = exit_code
        runner.start_time = time.time() - elapsed
        session = self.m.Session(name="s1", agent="main")
        return ctx, runner, session


class FinalDelivery(_Finalize):
    def test_final_answer_is_a_new_reply_message(self):
        ctx, runner, session = self.turn()
        self.bot._finalize_response(session, runner, prompt="oi")
        method, data = self.fx.rich_calls[0]
        self.assertEqual(method, "sendRichMessage")       # new message, not an edit
        self.assertIn("Resposta **final**", data["rich_message"]["markdown"])
        self.assertEqual(data["reply_parameters"],
                         {"message_id": 9, "allow_sending_without_reply": True})
        self.assertEqual(data["message_thread_id"], 5)
        self.assertNotIn("message_effect_id", data)        # short turn: no effect
        self.assertEqual(self.fx.html_edits(), [])
        self.assertEqual(ctx.draft_id, 0)                  # reset for the next turn

    def test_no_pronto_notice_on_draft_turn_but_effect_on_long_answer(self):
        ctx, runner, session = self.turn(elapsed=60)
        self.bot._finalize_response(session, runner, prompt="oi")
        data = self.fx.rich_calls[0][1]
        self.assertEqual(data["message_effect_id"], self.m.EFFECT_ID_CELEBRATE)
        notices = [d for d in self.fx.html_sends() if d.get("text", "").startswith("✅ Pronto")]
        self.assertEqual(notices, [])                      # no double "done" signal

    def test_copy_button_kept(self):
        code = "```python\n" + "print('x')\n" * 5 + "```"
        ctx, runner, session = self.turn(text=code)
        self.bot._finalize_response(session, runner, prompt="oi")
        markup = self.fx.rich_calls[0][1]["reply_markup"]
        self.assertIn("copy_text", markup["inline_keyboard"][0][0])

    def test_unknown_delivery_is_not_resent(self):
        ctx, runner, session = self.turn()
        self.fx.rich_responses = [{"ok": False, "error_code": 502, "description": "Bad Gateway"}]
        self.bot._finalize_response(session, runner, prompt="oi")
        self.assertEqual(len(self.fx.rich_calls), 1)
        sends = self.fx.html_sends()
        self.assertFalse(any("final" in d["text"] for d in sends))   # never a duplicate
        self.assertTrue(any("Não sei se a resposta chegou" in d["text"] for d in sends))

    def test_long_answer_is_split_not_cut_on_html_path(self):
        self.m.RICH_MESSAGES_ENABLED = False
        text = "\n\n".join(f"parágrafo {i} " + "x" * 300 for i in range(40))
        ctx, runner, session = self.turn(text=text)
        self.bot._finalize_response(session, runner, prompt="oi")
        sends = self.fx.html_sends()
        self.assertGreater(len(sends), 1)
        joined = "".join(d["text"] for d in sends)
        self.assertIn("parágrafo 39", joined)
        self.assertEqual(sends[0]["reply_parameters"]["message_id"], 9)


class NativeStop(_Finalize):
    def stop_update(self, chat_id=42, thread_id=5, draft_id=555):
        payload = {"chat": {"id": chat_id, "type": "private"}, "draft_id": draft_id}
        if thread_id is not None:
            payload["message_thread_id"] = thread_id
        return payload

    def test_stop_cancels_the_matching_turn(self):
        ctx = self.ctx(thread_id=5)
        ctx.draft_id = 555
        ctx.runner = MagicMock(running=True)
        self.bot._handle_generation_stopped(self.stop_update())
        ctx.runner.cancel.assert_called_once()
        self.assertTrue(ctx.draft_stopped)

    def test_stop_for_other_draft_or_chat_is_ignored(self):
        ctx = self.ctx(thread_id=5)
        ctx.draft_id = 555
        ctx.runner = MagicMock(running=True)
        self.bot._handle_generation_stopped(self.stop_update(draft_id=999))
        self.bot._handle_generation_stopped(self.stop_update(chat_id=777))   # unauthorized
        ctx.runner.cancel.assert_not_called()
        self.assertFalse(ctx.draft_stopped)

    def test_stop_found_by_draft_id_when_thread_differs(self):
        ctx = self.ctx(thread_id=5)
        ctx.draft_id = 555
        ctx.runner = MagicMock(running=True)
        self.bot._handle_generation_stopped(self.stop_update(thread_id=None))
        ctx.runner.cancel.assert_called_once()

    def test_stop_after_turn_ended_does_nothing(self):
        ctx = self.ctx(thread_id=5)
        ctx.draft_id = 555
        ctx.runner = MagicMock(running=False)
        self.bot._handle_generation_stopped(self.stop_update())
        ctx.runner.cancel.assert_not_called()

    def test_partial_answer_kept_and_marked(self):
        ctx, runner, session = self.turn(text="", exit_code=130, stopped=True, elapsed=60)
        runner.accumulated_text = "Metade da resposta"
        self.bot._finalize_response(session, runner, prompt="oi")
        md = self.fx.rich_calls[0][1]["rich_message"]["markdown"]
        self.assertIn("Metade da resposta", md)
        self.assertIn("Interrompido por você", md)
        self.assertNotIn("message_effect_id", self.fx.rich_calls[0][1])   # no party on stop

    def test_polling_requests_the_stop_update(self):
        self.bot._update_offset = 0
        seen = {}

        def fake_tg_request(method, data=None, timeout=15):
            seen.update(data or {})
            return {"ok": True, "result": []}
        self.bot.tg_request = fake_tg_request
        self.bot._poll_updates()
        self.assertIn("stopped_message_generation", seen["allowed_updates"])
        self.assertIn("message", seen["allowed_updates"])
        self.assertIn("callback_query", seen["allowed_updates"])


class GroupPathUnchanged(_Base):
    def test_group_stream_edits_placeholder(self):
        ctx = self.ctx(chat_id="-1001234", thread_id=3)
        self.bot._send_stream_placeholder(ctx)
        self.assertEqual(ctx.draft_id, 0)
        r = self.runner(snapshot="Parcial.")  # previews show whole sentences (v3.95)
        r.accumulated_thinking = ""
        r.tool_log = []
        alive = MagicMock()   # one loop pass, then the runner thread "ends"
        alive.is_alive.side_effect = [True, False]
        self.bot._stream_updates(alive, r)
        self.assertEqual(self.draft_calls, [])
        self.assertTrue(any(d.get("message_id") == ctx.stream_msg_id
                            for d in self.fx.html_edits()) or self.fx.rich_calls)

    def test_group_final_edits_placeholder_and_no_effect(self):
        ctx = self.ctx(chat_id="-1001234", thread_id=3)
        ctx.stream_msg_id = 77
        runner = self.m.ClaudeRunner()
        runner.result_text = "Resposta"
        runner.exit_code = 0
        runner.start_time = time.time() - 60
        self.bot._finalize_response(self.m.Session(name="s1", agent="main"), runner, prompt="oi")
        self.assertEqual(self.fx.rich_calls[0][0], "editMessageText")
        self.assertEqual(self.fx.rich_calls[0][1]["message_id"], 77)
        notice = [d for d in self.fx.html_sends() if d["text"].startswith("✅ Pronto")]
        self.assertEqual(len(notice), 1)
        self.assertNotIn("message_effect_id", notice[0])      # groups: never an effect


class Effects(_Base):
    def test_effect_only_in_private_chats(self):
        self.bot.send_message("oi", chat_id="42", effect_id="123")
        self.bot.send_message("oi", chat_id="-1005", effect_id="123")
        sends = self.fx.html_sends()
        self.assertEqual(sends[0]["message_effect_id"], "123")
        self.assertNotIn("message_effect_id", sends[1])

    def test_effect_on_first_chunk_only(self):
        self.bot.send_message("\n\n".join("y" * 3000 for _ in range(3)), chat_id="42",
                              effect_id="123")
        sends = self.fx.html_sends()
        self.assertGreater(len(sends), 1)
        self.assertIn("message_effect_id", sends[0])
        self.assertTrue(all("message_effect_id" not in d for d in sends[1:]))

    def test_rich_send_carries_effect(self):
        self.bot.send_message("**oi**", chat_id="42", effect_id="123", rich=True)
        self.assertEqual(self.fx.rich_calls[0][1]["message_effect_id"], "123")

    def test_rejected_effect_resends_without_it_and_disables(self):
        self.fx.rich_responses = [{"ok": False, "error_code": 400,
                                   "description": "Bad Request: EFFECT_ID_INVALID"}]
        mid = self.bot.send_message("**oi**", chat_id="42", effect_id="123", rich=True)
        self.assertIsNotNone(mid)
        self.assertEqual(len(self.fx.rich_calls), 2)
        self.assertNotIn("message_effect_id", self.fx.rich_calls[1][1])
        self.assertTrue(self.m._EFFECTS_RUNTIME_OFF)
        self.bot.send_message("de novo", chat_id="42", effect_id="123")
        self.assertNotIn("message_effect_id", self.fx.html_sends()[-1])

    def test_rejected_effect_on_html_path(self):
        calls = []

        def fake_tg_request(method, data=None, timeout=15):
            calls.append(dict(data or {}))
            if len(calls) == 1:
                self.bot._tg_set_last(self.err(400, "Bad Request: EFFECT_ID_INVALID"))
                return None
            self.bot._tg_set_last(self.m.TgResult(ok=True, status=200))
            return {"ok": True, "result": {"message_id": 5}}
        self.bot.tg_request = fake_tg_request
        self.assertEqual(self.bot.send_message("oi", chat_id="42", effect_id="123"), 5)
        self.assertIn("message_effect_id", calls[0])
        self.assertNotIn("message_effect_id", calls[1])

    def test_pronto_notice_celebrates_in_private_chat(self):
        ctx = self.ctx()
        ctx.stream_msg_id = 77
        runner = self.m.ClaudeRunner()
        runner.result_text = "ok"
        runner.exit_code = 0
        runner.start_time = time.time() - 60
        self.bot._finalize_response(self.m.Session(name="s1", agent="main"), runner, prompt="oi")
        notice = [d for d in self.fx.html_sends() if d["text"].startswith("✅ Pronto")]
        self.assertEqual(notice[0]["message_effect_id"], self.m.EFFECT_ID_CELEBRATE)

    def test_error_notice_has_no_effect(self):
        ctx = self.ctx()
        ctx.stream_msg_id = 77
        runner = self.m.ClaudeRunner()
        runner.result_text = "x"
        runner.error_text = "boom"
        runner.exit_code = 1
        runner.start_time = time.time() - 60
        self.bot._finalize_response(self.m.Session(name="s1", agent="main"), runner, prompt=None)
        notice = [d for d in self.fx.html_sends() if d["text"].startswith("⚠️ Terminou")]
        self.assertNotIn("message_effect_id", notice[0])

    def test_effects_env_off(self):
        self.m.MESSAGE_EFFECTS_ENABLED = False
        self.bot.send_message("oi", chat_id="42", effect_id="123")
        self.assertNotIn("message_effect_id", self.fx.html_sends()[0])


if __name__ == "__main__":
    unittest.main()
