"""Rich Messages (Bot API 10.1), the expandable reasoning panel, and the
completion notice ("aviso de pronto").

All Telegram I/O is faked: ``tg_request`` / ``_tg_edit`` for the HTML path and
``_rich_request`` for the rich path (it is a separate single-shot transport so
it can read Telegram's error ``description``).
"""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._botload import load_bot_module


class _BotFixture:
    """ClaudeTelegramBot with every Telegram call recorded (see test_routine_continuity)."""

    def __init__(self, tmp_root: Path):
        self.home = tmp_root / "home"
        self.vault = tmp_root / "vault"
        self.home.mkdir()
        self.m = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        self.m.RICH_MESSAGES_ENABLED = True
        self.tg_calls = []      # HTML path: (method, data)
        self.rich_calls = []    # rich path: (method, data)
        self.rich_responses = []  # queue of responses for _rich_request; default ok
        self.edit_ok = True
        self._lock = threading.Lock()
        B = self.m.ClaudeTelegramBot
        self._patches = [
            patch.object(B, "_start_control_server", lambda self: None),
            patch.object(B, "_start_webhook_server", lambda self: None),
            patch.object(B, "_check_voice_tools",
                         lambda self: {"can_transcribe": False, "ffmpeg": "", "hear": ""}),
            patch.object(B, "_check_tts_tools",
                         lambda self: {"can_synthesize": False, "edge_tts": "", "say": "", "ffmpeg": ""}),
            patch.object(self.m.RoutineScheduler, "start", lambda self: None),
            patch.object(self.m.RoutineScheduler, "stop", lambda self: None),
        ]
        for p in self._patches:
            p.start()
        self.bot = B()

        def fake_tg_request(method, data=None, timeout=15):
            with self._lock:
                self.tg_calls.append((method, dict(data or {})))
                return {"ok": True, "result": {"message_id": 1000 + len(self.tg_calls)}}

        def fake_tg_edit(data):
            with self._lock:
                self.tg_calls.append(("editMessageText", dict(data)))
            return {"ok": True, "result": {}} if self.edit_ok else None

        def fake_rich_request(method, data, timeout=30):
            with self._lock:
                self.rich_calls.append((method, dict(data)))
                if self.rich_responses:
                    return self.rich_responses.pop(0)
                return {"ok": True, "result": {"message_id": 500 + len(self.rich_calls)}}

        self.bot.tg_request = fake_tg_request
        self.bot._tg_edit = fake_tg_edit
        self.bot._rich_request = fake_rich_request

    def html_sends(self):
        return [d for m, d in self.tg_calls if m == "sendMessage"]

    def html_edits(self):
        return [d for m, d in self.tg_calls if m == "editMessageText"]

    def cleanup(self):
        for p in self._patches:
            p.stop()


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fx = _BotFixture(Path(self._td.name))
        self.bot, self.m = self.fx.bot, self.fx.m

    def tearDown(self):
        self.fx.cleanup()
        self._td.cleanup()


class RichSend(_Base):
    def test_payload_shape(self):
        mid = self.bot.send_message("**Olá** | tabela", chat_id="42", thread_id="7",
                                    reply_to_message_id=9, disable_notification=True,
                                    reply_markup={"inline_keyboard": []}, rich=True)
        self.assertEqual(mid, 501)
        self.assertEqual(self.fx.tg_calls, [])          # no HTML send at all
        method, data = self.fx.rich_calls[0]
        self.assertEqual(method, "sendRichMessage")
        self.assertEqual(data["chat_id"], "42")
        self.assertEqual(data["message_thread_id"], "7")
        self.assertEqual(data["rich_message"], {"markdown": "**Olá** | tabela"})
        self.assertEqual(data["reply_parameters"],
                         {"message_id": 9, "allow_sending_without_reply": True})
        self.assertTrue(data["disable_notification"])
        self.assertIn("reply_markup", data)
        # Only documented sendRichMessage params — no HTML-only leftovers.
        for key in ("text", "parse_mode", "link_preview_options"):
            self.assertNotIn(key, data)
        self.assertEqual(self.bot._last_first_message_id, 501)

    def test_markdown_table_is_sent_verbatim(self):
        table = "| a | b |\n|---|---|\n| 1 | 2 |"
        self.bot.send_message(table, rich=True)
        self.assertEqual(self.fx.rich_calls[0][1]["rich_message"]["markdown"], table)

    def test_memory_context_is_stripped(self):
        self.bot.send_message("oi <memory-context>segredo</memory-context> tchau", rich=True)
        md = self.fx.rich_calls[0][1]["rich_message"]["markdown"]
        self.assertNotIn("segredo", md)
        self.assertNotIn("memory-context", md)

    def test_api_error_falls_back_to_html_once(self):
        self.fx.rich_responses = [{"ok": False, "error_code": 400,
                                   "description": "Bad Request: can't parse rich message"}]
        mid = self.bot.send_message("**x**", rich=True)
        self.assertEqual(len(self.fx.rich_calls), 1)
        sends = self.fx.html_sends()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["parse_mode"], "HTML")
        self.assertEqual(sends[0]["text"], "<b>x</b>")
        self.assertEqual(mid, 1001)
        self.assertFalse(self.m._RICH_RUNTIME_OFF)   # content error ≠ kill switch

    def test_unknown_method_trips_kill_switch(self):
        self.fx.rich_responses = [{"ok": False, "error_code": 404, "description": "Not Found"}]
        with self.assertLogs("claude-bot", level="WARNING") as logs:
            self.bot.send_message("a", rich=True)
        self.assertTrue(self.m._RICH_RUNTIME_OFF)
        self.assertTrue(any("disabled until restart" in line for line in logs.output))
        self.assertEqual(len(self.fx.html_sends()), 1)
        # Next rich send goes straight to HTML — no second probe.
        self.bot.send_message("b", rich=True)
        self.assertEqual(len(self.fx.rich_calls), 1)
        self.assertEqual(len(self.fx.html_sends()), 2)

    def test_env_disabled_uses_html(self):
        self.m.RICH_MESSAGES_ENABLED = False
        self.bot.send_message("a", rich=True)
        self.assertEqual(self.fx.rich_calls, [])
        self.assertEqual(len(self.fx.html_sends()), 1)

    def test_above_rich_limit_uses_html_split(self):
        text = "x" * (self.m.RICH_MESSAGE_MAX_CHARS + 10)
        self.bot.send_message(text, rich=True)
        self.assertEqual(self.fx.rich_calls, [])
        self.assertGreater(len(self.fx.html_sends()), 1)    # existing split path

    def test_above_block_limit_uses_html(self):
        text = "\n".join(f"- item {i}" for i in range(self.m.RICH_MESSAGE_MAX_BLOCKS + 5))
        self.bot.send_message(text, rich=True)
        self.assertEqual(self.fx.rich_calls, [])
        self.assertTrue(self.fx.html_sends())

    def test_ambiguous_transport_failure_does_not_resend(self):
        self.fx.rich_responses = [{"ok": False, "error_code": 0, "description": "timed out",
                                   "transport_error": TimeoutError("timed out")}]
        self.assertIsNone(self.bot.send_message("a", rich=True))
        self.assertEqual(self.fx.html_sends(), [])           # no duplicate

    def test_transport_failure_before_send_falls_back(self):
        import urllib.error
        self.fx.rich_responses = [{"ok": False, "error_code": 0, "description": "no route",
                                   "transport_error": urllib.error.URLError("no route")}]
        self.bot.send_message("a", rich=True)
        self.assertEqual(len(self.fx.html_sends()), 1)

    def test_internal_status_messages_unaffected(self):
        # Default rich=False: internal callers keep the HTML path even with rich on.
        self.bot.send_message("🔁 _Executando rotina *x*..._")
        self.bot.edit_message(77, "⏳ _Aguardando..._")
        self.assertEqual(self.fx.rich_calls, [])
        self.assertEqual(len(self.fx.html_sends()), 1)
        self.assertEqual(len(self.fx.html_edits()), 1)

    def test_non_html_parse_mode_never_rich(self):
        self.bot.send_message("plain", parse_mode="", rich=True)
        self.assertEqual(self.fx.rich_calls, [])


class RichEdit(_Base):
    def test_edit_payload_shape(self):
        ok = self.bot.edit_message(77, "**fim**", chat_id="42",
                                   reply_markup={"inline_keyboard": []}, rich=True)
        self.assertTrue(ok)
        method, data = self.fx.rich_calls[0]
        self.assertEqual(method, "editMessageText")
        self.assertEqual(data, {"chat_id": "42", "message_id": 77,
                                "rich_message": {"markdown": "**fim**"},
                                "reply_markup": {"inline_keyboard": []}})
        self.assertEqual(self.fx.html_edits(), [])

    def test_edit_error_falls_back_and_message_stays_html(self):
        self.fx.rich_responses = [{"ok": False, "error_code": 400,
                                   "description": "Bad Request: can't parse rich message"}]
        self.assertTrue(self.bot.edit_message(77, "a", rich=True))
        self.assertEqual(len(self.fx.html_edits()), 1)
        # Same message, next stream edit: no rich retry (would double the calls).
        self.bot.edit_message(77, "ab", rich=True)
        self.assertEqual(len(self.fx.rich_calls), 1)
        self.assertEqual(len(self.fx.html_edits()), 2)

    def test_already_rich_message_is_always_edited_rich(self):
        self.bot.edit_message(77, "parcial", rich=True)
        self.bot.edit_message(77, "✅")                  # internal status, rich=False
        self.assertEqual([m for m, _ in self.fx.rich_calls],
                         ["editMessageText", "editMessageText"])
        self.assertEqual(self.fx.html_edits(), [])

    def test_not_modified_counts_as_success(self):
        self.fx.rich_responses = [{"ok": False, "error_code": 400,
                                   "description": "Bad Request: message is not modified"}]
        self.assertTrue(self.bot.edit_message(77, "x", rich=True))
        self.assertEqual(self.fx.html_edits(), [])

    def test_rich_message_param_ignored_trips_kill_switch(self):
        self.fx.rich_responses = [{"ok": False, "error_code": 400,
                                   "description": "Bad Request: message text is empty"}]
        with self.assertLogs("claude-bot", level="WARNING"):
            self.bot.edit_message(77, "x", rich=True)
        self.assertTrue(self.m._RICH_RUNTIME_OFF)

    def test_three_failing_messages_disable_rich_edits(self):
        for mid in (1, 2, 3):
            self.fx.rich_responses.append({"ok": False, "error_code": 400,
                                           "description": "Bad Request: weird"})
            self.bot.edit_message(mid, "x", rich=True)
        self.assertTrue(self.m._RICH_EDIT_RUNTIME_OFF)
        self.assertFalse(self.m._RICH_RUNTIME_OFF)       # sends still allowed
        self.bot.edit_message(4, "x", rich=True)
        self.assertEqual(len(self.fx.rich_calls), 3)


class RichMarkdownPrep(_Base):
    def test_accidental_math_marker_spoiler_strike_escaped(self):
        md = self.m._rich_markdown_from_model(
            "BTC $65k → $70k, a == b, x || y, ~30s, ~~riscado~~")
        self.assertIn("\\$65k", md)
        self.assertIn("\\$70k", md)
        self.assertIn("\\=\\=", md)
        self.assertIn("\\|\\|", md)
        self.assertIn("\\~30s", md)
        self.assertIn("~~riscado~~", md)

    def test_code_and_urls_untouched(self):
        src = "`a == $b`\n```\nx = $y || ~z\n```\nhttps://t.me/~user?q=$x"
        self.assertEqual(self.m._rich_markdown_from_model(src), src)

    def test_table_rows_keep_pipes(self):
        src = "| a || b |\n|---|---|"
        self.assertEqual(self.m._rich_markdown_from_model(src), src)

    def test_expandable_marker_becomes_details(self):
        md = self.m._rich_markdown_from_model("**> 🧠 *Reasoning:*\n> linha 1\n> linha 2\n\nResposta")
        self.assertIn("<details><summary>🧠 *Reasoning:*</summary>", md)
        self.assertIn("linha 1\nlinha 2", md)
        self.assertIn("</details>", md)
        self.assertNotIn("<details open", md)            # collapsed by default
        self.assertTrue(md.rstrip().endswith("Resposta"))

    def test_truncated_fence_in_details_is_closed(self):
        md = self.m._rich_markdown_from_model("**> 🧠 R\n> ```py\n> x = 1\n\nfim")
        before_close = md.split("</details>")[0]
        self.assertEqual(before_close.count("```") % 2, 0)


class ExpandableReasoning(_Base):
    def test_html_converter_emits_expandable_blockquote(self):
        html = self.bot._markdown_to_html("**> 🧠 *Reasoning:*\n> passo 1\n\nResposta")
        self.assertIn("<blockquote expandable>", html)
        self.assertIn("passo 1", html)
        self.assertIn("Resposta", html)

    def test_plain_quote_stays_plain(self):
        html = self.bot._markdown_to_html("> citação")
        self.assertIn("<blockquote>citação</blockquote>", html)

    def test_expandable_survives_sanitize_and_rebalance(self):
        s = self.bot._sanitize_telegram_html("<blockquote expandable>a<b>b</blockquote>")
        self.assertTrue(s.startswith("<blockquote expandable>"))
        chunks = self.bot._rebalance_html_chunks(["<blockquote expandable>abc", "def</blockquote>"])
        self.assertTrue(chunks[1].startswith("<blockquote expandable>"))

    def test_stream_display_marks_reasoning_expandable(self):
        runner = self.m.ClaudeRunner()
        runner.accumulated_thinking = "pensando"
        display = self.bot._build_stream_display("resposta", runner, 1, 5, True)
        self.assertTrue(display.startswith("**> 🧠"))
        html = self.bot._markdown_to_html(display)
        self.assertIn("<blockquote expandable>", html)


class _FinalizeBase(_Base):
    def make_turn(self, elapsed=30.0, text="Resposta **final**", exit_code=0):
        ctx = self.m.ThreadContext(chat_id="42", thread_id=7)
        ctx.stream_msg_id = 77
        ctx.user_msg_id = 9
        self.bot._ctx = ctx
        runner = self.m.ClaudeRunner()
        runner.result_text = text
        runner.exit_code = exit_code
        runner.start_time = time.time() - elapsed
        session = self.m.Session(name="s1", agent="main")
        self.m.SHOW_SIGNATURE = False
        return ctx, runner, session

    def notices(self):
        return [d for d in self.fx.html_sends()
                if d.get("text", "").startswith(("✅ Pronto", "⚠️ Terminou"))]


class FinalizeRich(_FinalizeBase):
    def test_final_answer_edited_as_rich(self):
        ctx, runner, session = self.make_turn(elapsed=1)
        self.bot._finalize_response(session, runner, prompt="oi")
        method, data = self.fx.rich_calls[0]
        self.assertEqual(method, "editMessageText")
        self.assertEqual(data["message_id"], 77)
        self.assertIn("Resposta **final**", data["rich_message"]["markdown"])
        self.assertEqual(self.fx.html_edits(), [])

    def test_long_answer_fits_one_rich_message(self):
        ctx, runner, session = self.make_turn(elapsed=1, text=("palavra " * 50 + "\n\n") * 30)  # ~10k chars, 30 blocks
        self.bot._finalize_response(session, runner, prompt="oi")
        self.assertEqual(len(self.fx.rich_calls), 1)
        self.assertEqual(self.fx.html_sends(), [])        # no 4096-char split

    def test_rich_final_failure_falls_back_to_html_edit(self):
        ctx, runner, session = self.make_turn(elapsed=1)
        self.fx.rich_responses = [{"ok": False, "error_code": 400, "description": "bad"}]
        self.bot._finalize_response(session, runner, prompt="oi")
        edits = self.fx.html_edits()
        self.assertEqual(len(edits), 1)
        self.assertIn("<b>final</b>", edits[0]["text"])


class CompletionNotice(_FinalizeBase):
    def setUp(self):
        super().setUp()
        self.m.NOTIFY_DONE_AFTER_SECONDS = 20

    def test_notice_after_threshold_when_delivered_by_edit(self):
        ctx, runner, session = self.make_turn(elapsed=45)
        self.bot._finalize_response(session, runner, prompt="oi")
        notes = self.notices()
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0]["text"].startswith("✅ Pronto · 45s"))
        self.assertEqual(notes[0]["reply_parameters"],
                         {"message_id": 9, "allow_sending_without_reply": True})
        self.assertNotIn("disable_notification", notes[0])
        self.assertEqual(notes[0]["chat_id"], "42")
        self.assertEqual(notes[0]["message_thread_id"], 7)

    def test_no_notice_below_threshold(self):
        ctx, runner, session = self.make_turn(elapsed=5)
        self.bot._finalize_response(session, runner, prompt="oi")
        self.assertEqual(self.notices(), [])

    def test_disabled_with_zero(self):
        self.m.NOTIFY_DONE_AFTER_SECONDS = 0
        ctx, runner, session = self.make_turn(elapsed=500)
        self.bot._finalize_response(session, runner, prompt="oi")
        self.assertEqual(self.notices(), [])

    def test_no_notice_when_delivered_as_new_message(self):
        # Rich off + edit fails → answer goes out as a NEW (notifying) message.
        self.m.RICH_MESSAGES_ENABLED = False
        self.fx.edit_ok = False
        ctx, runner, session = self.make_turn(elapsed=45)
        self.bot._finalize_response(session, runner, prompt="oi")
        self.assertTrue(any("final" in d["text"] for d in self.fx.html_sends()))
        self.assertEqual(self.notices(), [])

    def test_no_notice_for_routines(self):
        ctx, runner, session = self.make_turn(elapsed=45)
        self.bot._finalize_response(session, runner, prompt="[ROTINA: x | 07:00]",
                                    routine_mode=True)
        self.assertEqual(self.notices(), [])

    def test_no_notice_for_voice_only(self):
        ctx, runner, session = self.make_turn(elapsed=45)
        self.bot._finalize_response(session, runner, prompt="oi", suppress_text=True)
        self.assertEqual(self.notices(), [])

    def test_no_notice_when_cancelled(self):
        ctx, runner, session = self.make_turn(elapsed=45, exit_code=130)
        self.bot._finalize_response(session, runner, prompt="oi")
        self.assertEqual(self.notices(), [])

    def test_error_turn_says_so(self):
        ctx, runner, session = self.make_turn(elapsed=45, exit_code=1)
        runner.error_text = "boom"
        self.bot._finalize_response(session, runner, prompt=None)
        notes = self.notices()
        self.assertEqual(len(notes), 1)
        self.assertTrue(notes[0]["text"].startswith("⚠️ Terminou com erro"))


if __name__ == "__main__":
    unittest.main()
