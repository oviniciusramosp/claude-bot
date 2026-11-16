"""HTML widgets (Bot API 10.4): limits, private-only gating, fallback + kill
switch, the /cost and /routine status panels, and the routines refresh.

All Telegram I/O is faked: ``_widget_request`` (sendWidget /
editMessageWidgetData / answerWidgetQuery) and ``tg_request`` (the plain-text
fallback path). Nothing reaches the network.
"""
import json
import logging
import secrets
import tempfile
import threading
import unittest
import urllib.error
import zlib
from pathlib import Path
from unittest.mock import patch

from tests._botload import load_bot_module

PRIVATE = "123456789"          # TELEGRAM_CHAT_ID set by the harness
GROUP = "-1001234567890"


class _BotFixture:
    def __init__(self, tmp_root: Path):
        self.home = tmp_root / "home"
        self.vault = tmp_root / "vault"
        self.home.mkdir()
        self.m = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        self.m.WIDGETS_ENABLED = True
        self.tg_calls = []         # fallback path: (method, data)
        self.widget_calls = []     # widget path: (method, data)
        self.widget_responses = []  # queue; default = ok
        self._lock = threading.Lock()
        B = self.m.ClaudeTelegramBot
        self._patches = [
            patch.object(B, "_start_control_server", lambda self: None),
            patch.object(B, "_start_webhook_server", lambda self: None),
            patch.object(B, "_check_voice_tools",
                         lambda self: {"can_transcribe": False, "ffmpeg": "", "hear": ""}),
            patch.object(B, "_check_tts_tools",
                         lambda self: {"can_synthesize": False, "edge_tts": "", "say": "",
                                       "ffmpeg": ""}),
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

        def fake_widget_request(method, data, timeout=30):
            with self._lock:
                self.widget_calls.append((method, dict(data)))
                if self.widget_responses:
                    resp = self.widget_responses.pop(0)
                    if isinstance(resp, BaseException):
                        return {"ok": False, "error_code": 0, "description": str(resp),
                                "transport_error": resp}
                    return resp
                if method == "sendWidget":
                    return {"ok": True, "result": {"message_id": 500 + len(self.widget_calls)}}
                return {"ok": True, "result": True}

        self.bot.tg_request = fake_tg_request
        self.bot._widget_request = fake_widget_request

    def calls(self, method):
        return [d for m, d in self.widget_calls if m == method]

    def text_sends(self):
        return [d for m, d in self.tg_calls if m == "sendMessage"]

    def cleanup(self):
        for p in self._patches:
            p.stop()


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fx = _BotFixture(Path(self._td.name))
        self.bot, self.m = self.fx.bot, self.fx.m
        self.bot._ctx = self.bot._get_context(PRIVATE, None)

    def tearDown(self):
        self.fx.cleanup()
        self._td.cleanup()

    def in_group(self):
        self.bot._ctx = self.bot._get_context(GROUP, None)


# ---------------------------------------------------------------- limits

class HtmlLimits(_Base):
    def test_empty_and_nul_refused(self):
        self.assertIn("vazio", self.m._widget_html_problem(""))
        self.assertIn("NUL", self.m._widget_html_problem("<p>a\x00b</p>"))

    def test_raw_size_limit_counts_utf8_bytes(self):
        ok = "a" * self.m.WIDGET_HTML_MAX_BYTES
        self.assertIsNone(self.m._widget_html_problem(ok))  # compresses to almost nothing
        # 16385 × "é" = 32770 bytes but only 16385 characters
        self.assertIn("32770 bytes", self.m._widget_html_problem("é" * 16385))

    def test_compressed_limit_uses_zlib_level_9(self):
        noisy = secrets.token_hex(6000)  # 12000 bytes, incompressible-ish
        self.assertGreater(len(zlib.compress(noisy.encode(), 9)), 4096)
        problem = self.m._widget_html_problem(noisy)
        self.assertIn("comprimido", problem)
        self.assertIn(str(len(zlib.compress(noisy.encode(), 9))), problem)

    def test_builtin_panels_fit_with_margin(self):
        for name in ("COST_WIDGET_HTML", "ROUTINES_WIDGET_HTML"):
            html_code = getattr(self.m, name)
            self.assertIsNone(self.m._widget_html_problem(html_code), name)
            self.assertLess(len(zlib.compress(html_code.encode(), 9)), 3500, name)

    def test_builtin_panels_are_self_contained(self):
        for name in ("COST_WIDGET_HTML", "ROUTINES_WIDGET_HTML"):
            html_code = getattr(self.m, name)
            for banned in ("<script src", "<link", "http://", "https://", "fetch(",
                           "<input", "@import", "font-family", " vh", "oklch"):
                self.assertNotIn(banned, html_code, f"{name}: {banned}")
            self.assertIn("--tg-theme-", html_code, name)  # theme colors only

    def test_data_limit_counts_bytes_not_chars(self):
        self.assertIsNone(self.m._widget_data_problem("a" * 1024))
        self.assertIn("1025 bytes", self.m._widget_data_problem("a" * 1025))
        self.assertIn("1026 bytes", self.m._widget_data_problem("é" * 513))
        self.assertIsNone(self.m._widget_data_problem(None))

    def test_fit_rows_drops_rows_and_counts_them(self):
        rows = [["08:00", "x" * 28, 0, 0] for _ in range(100)]
        out = self.m._widget_fit_rows(lambda kept, hidden: {"r": kept, "x": hidden}, rows)
        self.assertLessEqual(len(out.encode()), 1024)
        body = json.loads(out)
        self.assertEqual(len(body["r"]) + body["x"], 100)
        self.assertGreater(body["x"], 0)


# ---------------------------------------------------------------- send_widget

class SendWidget(_Base):
    def test_private_chat_sends_widget_only(self):
        res = self.bot.send_widget("<p>oi</p>", {"a": 1}, caption="legenda",
                                   fallback_text="texto", allow_queries=True)
        self.assertTrue(res.widget)
        sent = self.fx.calls("sendWidget")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["chat_id"], PRIVATE)
        self.assertEqual(sent[0]["html"], "<p>oi</p>")
        self.assertEqual(sent[0]["chat_data"], '{"a":1}')
        self.assertEqual(sent[0]["caption"], "legenda")
        self.assertTrue(sent[0]["allow_queries"])
        self.assertNotIn("message_thread_id", sent[0])
        self.assertEqual(self.fx.text_sends(), [])
        self.assertEqual(res.message_id, 501)

    def test_private_topic_passes_thread_id(self):
        self.bot._ctx = self.bot._get_context(PRIVATE, 77)
        self.bot.send_widget("<p>oi</p>", fallback_text="t")
        self.assertEqual(self.fx.calls("sendWidget")[0]["message_thread_id"], 77)

    def test_group_gets_text_and_no_api_call(self):
        self.in_group()
        res = self.bot.send_widget("<p>oi</p>", fallback_text="texto do grupo")
        self.assertFalse(res.widget)
        self.assertEqual(self.fx.calls("sendWidget"), [])
        sends = self.fx.text_sends()
        self.assertEqual(len(sends), 1)
        self.assertEqual(sends[0]["chat_id"], GROUP)
        self.assertIn("texto do grupo", sends[0]["text"])

    def test_env_switch_off_gets_text(self):
        self.m.WIDGETS_ENABLED = False
        self.bot.send_widget("<p>oi</p>", fallback_text="texto")
        self.assertEqual(self.fx.calls("sendWidget"), [])
        self.assertEqual(len(self.fx.text_sends()), 1)

    def test_unknown_method_trips_kill_switch_once(self):
        self.fx.widget_responses.append(
            {"ok": False, "error_code": 404, "description": "Not Found: method not found"})
        with self.assertLogs("claude-bot", level="WARNING") as logs:
            res = self.bot.send_widget("<p>oi</p>", fallback_text="texto")
        self.assertFalse(res.widget)
        self.assertTrue(self.m._WIDGET_RUNTIME_OFF)
        self.assertTrue(any("disabled until restart" in line for line in logs.output))
        self.assertEqual(len(self.fx.text_sends()), 1)
        # Second send: straight to text, no API call, no second WARNING.
        self.bot.send_widget("<p>oi</p>", fallback_text="texto 2")
        self.assertEqual(len(self.fx.calls("sendWidget")), 1)
        self.assertEqual(len(self.fx.text_sends()), 2)

    def test_content_rejection_falls_back_without_kill_switch(self):
        self.fx.widget_responses.append(
            {"ok": False, "error_code": 400,
             "description": "Bad Request: INPUT_MEDIA_WIDGET_TOO_LARGE"})
        with self.assertLogs("claude-bot", level="WARNING") as logs:
            res = self.bot.send_widget("<p>oi</p>", fallback_text="texto")
        self.assertFalse(res.widget)
        self.assertFalse(self.m._WIDGET_RUNTIME_OFF)
        self.assertTrue(any("INPUT_MEDIA_WIDGET_TOO_LARGE" in line for line in logs.output))
        self.assertEqual(len(self.fx.text_sends()), 1)

    def test_server_error_is_unknown_delivery_no_duplicate(self):
        self.fx.widget_responses.append({"ok": False, "error_code": 502,
                                         "description": "Bad Gateway"})
        with self.assertLogs("claude-bot", level="ERROR"):
            res = self.bot.send_widget("<p>oi</p>", fallback_text="texto")
        self.assertIsNone(res.message_id)
        self.assertEqual(self.fx.text_sends(), [])

    def test_transport_error_before_send_falls_back(self):
        self.fx.widget_responses.append(urllib.error.URLError("no route"))
        res = self.bot.send_widget("<p>oi</p>", fallback_text="texto")
        self.assertFalse(res.widget)
        self.assertEqual(len(self.fx.text_sends()), 1)

    def test_transport_error_after_send_does_not_duplicate(self):
        self.fx.widget_responses.append(ConnectionResetError("reset"))
        with self.assertLogs("claude-bot", level="ERROR"):
            res = self.bot.send_widget("<p>oi</p>", fallback_text="texto")
        self.assertIsNone(res.message_id)
        self.assertEqual(self.fx.text_sends(), [])

    def test_oversized_html_never_reaches_api(self):
        with self.assertLogs("claude-bot", level="ERROR"):
            res = self.bot.send_widget(secrets.token_hex(6000), fallback_text="texto")
        self.assertFalse(res.widget)
        self.assertEqual(self.fx.calls("sendWidget"), [])
        self.assertEqual(len(self.fx.text_sends()), 1)

    def test_oversized_data_never_reaches_api(self):
        with self.assertLogs("claude-bot", level="ERROR"):
            self.bot.send_widget("<p>oi</p>", "x" * 2000, fallback_text="texto")
        self.assertEqual(self.fx.calls("sendWidget"), [])
        self.assertEqual(len(self.fx.text_sends()), 1)

    def test_no_fallback_text_is_logged_not_silent(self):
        self.in_group()
        with self.assertLogs("claude-bot", level="ERROR") as logs:
            res = self.bot.send_widget("<p>oi</p>")
        self.assertIsNone(res.message_id)
        self.assertTrue(any("no fallback text" in line for line in logs.output))

    def test_caption_truncated_to_limit(self):
        self.bot.send_widget("<p>oi</p>", caption="c" * 2000, fallback_text="t")
        self.assertEqual(len(self.fx.calls("sendWidget")[0]["caption"]), 1024)


# ---------------------------------------------------------------- /cost panel

class CostPanel(_Base):
    def test_breakdown_reads_providers_models_and_days(self):
        self.m._track_cost(1.5, model="opus")
        self.m._track_cost(0.25, model="sonnet")
        self.m._track_cost(0.5, model="gpt-5-codex")
        b = self.m.get_weekly_cost_breakdown()
        self.assertAlmostEqual(b["total"], 2.25)
        self.assertAlmostEqual(b["today"], 2.25)
        self.assertAlmostEqual(b["providers"]["anthropic"], 1.75)
        self.assertAlmostEqual(b["providers"]["openai"], 0.5)
        self.assertEqual(set(b["models"]), {"opus", "sonnet", "gpt-5-codex"})
        self.assertEqual(len(b["days"]), 7)
        self.assertAlmostEqual(sum(b["days"]), 2.25)

    def test_breakdown_legacy_week_counts_as_anthropic(self):
        import time as _t
        wk = _t.strftime("%G-W%V")
        self.m.COSTS_FILE.write_text(json.dumps(
            {"weeks": {wk: {"total": 3.0, "days": {_t.strftime("%Y-%m-%d"): 3.0}}}}))
        b = self.m.get_weekly_cost_breakdown()
        self.assertEqual(b["providers"], {"anthropic": 3.0})
        self.assertEqual(b["models"], {})

    def test_breakdown_unreadable_file_reports_error(self):
        self.m.COSTS_FILE.write_text("{not json")
        with self.assertLogs("claude-bot", level="ERROR"):
            b = self.m.get_weekly_cost_breakdown()
        self.assertTrue(b["error"])
        self.assertEqual(b["total"], 0.0)

    def test_private_cost_sends_panel(self):
        self.m._track_cost(1.5, model="opus")
        self.bot.cmd_cost("")
        sent = self.fx.calls("sendWidget")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["html"], self.m.COST_WIDGET_HTML)
        data = json.loads(sent[0]["chat_data"])
        self.assertEqual(data["t"], 1.5)
        self.assertEqual(data["p"], [["Anthropic", 1.5]])
        self.assertEqual(data["m"], [["opus", 1.5]])
        self.assertIn("US$ 1,50", sent[0]["caption"])
        self.assertNotIn("allow_queries", sent[0])  # static panel

    def test_group_cost_keeps_session_cost_text(self):
        self.in_group()
        with patch.object(self.bot, "_run_claude_prompt") as run:
            self.bot.cmd_cost("")
        run.assert_called_once_with("/cost")
        self.assertEqual(self.fx.calls("sendWidget"), [])

    def test_secondary_private_chat_never_sees_owner_cost(self):
        self.bot._ctx = self.bot._get_context("987654321", None)
        with patch.object(self.bot, "_is_primary_chat", lambda cid: False), \
                patch.object(self.bot, "_run_claude_prompt") as run:
            self.bot.cmd_cost("")
        run.assert_called_once_with("/cost")
        self.assertEqual(self.fx.calls("sendWidget"), [])

    def test_cost_sessao_keeps_session_cost_in_private(self):
        with patch.object(self.bot, "_run_claude_prompt") as run:
            self.bot.cmd_cost("sessao")
        run.assert_called_once_with("/cost")
        self.assertEqual(self.fx.calls("sendWidget"), [])

    def test_cost_fallback_text_when_widget_rejected(self):
        self.m._track_cost(2.0, model="opus")
        self.fx.widget_responses.append(
            {"ok": False, "error_code": 400, "description": "Bad Request: something"})
        with self.assertLogs("claude-bot", level="WARNING"):
            self.bot.cmd_cost("")
        sends = self.fx.text_sends()
        self.assertEqual(len(sends), 1)
        self.assertIn("US$ 2,00", sends[0]["text"])
        self.assertIn("opus", sends[0]["text"])

    def test_cost_unreadable_file_tells_user(self):
        self.m.COSTS_FILE.write_text("{not json")
        with self.assertLogs("claude-bot", level="ERROR"):
            self.bot.cmd_cost("")
        self.assertEqual(self.fx.calls("sendWidget"), [])
        self.assertIn("Não consegui ler", self.fx.text_sends()[0]["text"])

    def test_cost_payload_fits_with_many_models(self):
        b = {"week": "2026-W47", "total": 99.0, "today": 1.0, "days": [1.0] * 7,
             "providers": {"anthropic": 99.0},
             "models": {f"modelo-com-nome-bem-comprido-{i}": float(i + 1) for i in range(60)},
             "error": ""}
        payload = self.bot._cost_widget_payload(b)
        self.assertLessEqual(len(payload.encode()), 1024)
        body = json.loads(payload)
        self.assertEqual(len(body["m"]) + body["mx"], 60)


# ---------------------------------------------------------------- /routine status

def _routines(status_of_b="pending"):
    return [
        {"name": "a", "title": "Resumo da manhã", "time": "08:00", "status": "completed"},
        {"name": "b", "title": "Notícias", "time": "12:00", "status": status_of_b},
        {"name": "c", "title": "Pipeline X", "time": "18:00", "status": "failed",
         "error": "boom", "type": "pipeline", "steps": {}},
    ]


class RoutinesPanel(_Base):
    def setUp(self):
        super().setUp()
        self.routines = _routines()
        self.bot.scheduler.list_today_routines = lambda: self.routines

    def test_private_status_sends_refreshable_panel(self):
        self.bot._routine_status()
        sent = self.fx.calls("sendWidget")
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["html"], self.m.ROUTINES_WIDGET_HTML)
        self.assertTrue(sent[0]["allow_queries"])
        data = json.loads(sent[0]["chat_data"])
        self.assertEqual(data["r"], [["08:00", "Resumo da manhã", 2, 0],
                                     ["12:00", "Notícias", 0, 0],
                                     ["18:00", "Pipeline X", 3, 1]])
        self.assertIn("1 concluída,", sent[0]["caption"])
        self.assertIn("1 com falha", sent[0]["caption"])
        self.assertEqual(self.fx.text_sends(), [])

    def test_group_status_keeps_text_list(self):
        self.in_group()
        self.bot._routine_status()
        self.assertEqual(self.fx.calls("sendWidget"), [])
        text = self.fx.text_sends()[0]["text"]
        self.assertIn("Notícias", text)
        self.assertIn("boom", text)

    def test_empty_day_is_plain_text(self):
        self.routines = []
        self.bot._routine_status()
        self.assertEqual(self.fx.calls("sendWidget"), [])
        self.assertIn("Nenhuma rotina", self.fx.text_sends()[0]["text"])

    def test_many_routines_fit_and_report_hidden(self):
        self.routines = [{"title": f"Rotina número {i} com título longo", "time": "09:00",
                          "status": "pending"} for i in range(80)]
        payload, _key = self.bot._routines_widget_payload()
        self.assertLessEqual(len(payload.encode()), 1024)
        body = json.loads(payload)
        self.assertEqual(len(body["r"]) + body["x"], 80)

    def test_refresh_answers_then_edits_only_on_change(self):
        self.bot._routine_status()
        mid = self.fx.calls("sendWidget")[0] and 501
        q = {"id": "q1", "chat": {"id": int(PRIVATE), "type": "private"},
             "message_id": mid, "data": "rt"}
        # Same state as sent → answer only, no edit.
        self.bot._handle_widget_query(q)
        answers = self.fx.calls("answerWidgetQuery")
        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0]["widget_query_id"], "q1")
        self.assertEqual(json.loads(answers[0]["data"])["r"][1][2], 0)
        self.assertEqual(self.fx.calls("editMessageWidgetData"), [])
        # A routine finished → answer + edit the message's chat_data.
        self.routines = _routines(status_of_b="completed")
        self.bot._handle_widget_query(dict(q, id="q2"))
        edits = self.fx.calls("editMessageWidgetData")
        self.assertEqual(len(edits), 1)
        self.assertEqual(edits[0]["message_id"], mid)
        self.assertEqual(json.loads(edits[0]["chat_data"])["r"][1][2], 2)
        # Polled again with nothing new → no second edit.
        self.bot._handle_widget_query(dict(q, id="q3"))
        self.assertEqual(len(self.fx.calls("editMessageWidgetData")), 1)
        self.assertEqual(len(self.fx.calls("answerWidgetQuery")), 3)

    def test_edit_not_modified_counts_as_done(self):
        self.fx.widget_responses += [
            {"ok": True, "result": True},  # answer
            {"ok": False, "error_code": 400,
             "description": "Bad Request: message is not modified"},
        ]
        q = {"id": "q1", "chat": {"id": int(PRIVATE)}, "message_id": 9, "data": "rt"}
        self.bot._handle_widget_query(q)
        self.assertEqual(self.bot._widget_panel_states().get((PRIVATE, 9)) is not None, True)

    def test_unauthorized_query_answered_without_data_leak(self):
        q = {"id": "q9", "chat": {"id": 555}, "message_id": 1, "data": "rt"}
        self.bot._handle_widget_query(q)
        answers = self.fx.calls("answerWidgetQuery")
        self.assertEqual(len(answers), 1)
        self.assertEqual(json.loads(answers[0]["data"]), {"e": "Não autorizado"})
        self.assertEqual(self.fx.calls("editMessageWidgetData"), [])

    def test_unknown_query_is_answered(self):
        q = {"id": "q8", "chat": {"id": int(PRIVATE)}, "message_id": 1, "data": "zz"}
        with self.assertLogs("claude-bot", level="WARNING"):
            self.bot._handle_widget_query(q)
        self.assertIn("e", json.loads(self.fx.calls("answerWidgetQuery")[0]["data"]))

    def test_handler_crash_still_answers(self):
        def boom():
            raise RuntimeError("disco sumiu")
        self.bot.scheduler.list_today_routines = boom
        q = {"id": "q7", "chat": {"id": int(PRIVATE)}, "message_id": 1, "data": "rt"}
        with self.assertLogs("claude-bot", level="ERROR"):
            self.bot._handle_widget_query(q)
        answers = self.fx.calls("answerWidgetQuery")
        self.assertEqual(len(answers), 1)
        self.assertIn("Erro", json.loads(answers[0]["data"])["e"])

    def test_dispatch_runs_off_thread(self):
        done = threading.Event()
        with patch.object(self.bot, "_handle_widget_query", lambda q: done.set()):
            self.bot._dispatch_widget_query({"id": "x"})
            self.assertTrue(done.wait(2))


class Polling(_Base):
    def test_poll_asks_for_widget_queries(self):
        self.bot._poll_updates()
        polls = [d for m, d in self.fx.tg_calls if m == "getUpdates"]
        self.assertIn("widget_query", polls[0]["allowed_updates"])

    def test_poll_without_widgets_keeps_old_list(self):
        self.m.WIDGETS_ENABLED = False
        self.bot._poll_updates()
        polls = [d for m, d in self.fx.tg_calls if m == "getUpdates"]
        self.assertNotIn("widget_query", polls[0]["allowed_updates"])


if __name__ == "__main__":
    logging.disable(logging.NOTSET)
    unittest.main()
