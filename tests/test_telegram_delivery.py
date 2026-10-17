"""Telegram delivery: a final answer is never silently cut, duplicated or lost.

Covers the transport layer contracts (see CLAUDE.md "Turn integrity"):

* the "fits in one message" decision is made AFTER HTML conversion, and a
  final edit is never truncated (``edit_message`` returns False instead);
* the plain-text fallback fires ONLY on "can't parse entities";
* "message is not modified" is a successful edit;
* a send whose delivery is UNKNOWN is never repeated;
* the rate limiter drops streaming previews while a chat is throttled and
  honors a 429's full ``retry_after`` for final deliveries;
* getUpdates failures back off (409 → deleteWebhook once + one alert);
* the update offset is written atomically;
* multipart uploads JSON-encode object fields (reply_parameters, …).
"""
import io
import json
import os
import socket
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._botload import load_bot_module


def _ok(message_id=1):
    resp = MagicMock()
    resp.read.return_value = json.dumps(
        {"ok": True, "result": {"message_id": message_id}}).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda s, *a: False
    return resp


def _http_error(code, description, retry_after=None):
    body = {"ok": False, "error_code": code, "description": description}
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(json.dumps(body).encode()))


def _payload(call):
    """JSON body of a urlopen(req, ...) call."""
    req = call.args[0]
    return json.loads(req.data.decode("utf-8"))


def _method(call):
    return call.args[0].full_url.rsplit("/", 1)[-1]


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.m = load_bot_module(tmp_home=Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        B = self.m.ClaudeTelegramBot
        self.bot = B.__new__(B)
        self.bot.base_url = "https://api.telegram.org/botTEST"
        self.bot.token = "TEST"
        self.bot._ctx_local = threading.local()
        self.bot._active_msgs = MagicMock()
        self.bot.primary_chat_ids = {"111"}
        self.sleep = patch.object(self.m.time, "sleep").start()
        self.addCleanup(patch.stopall)

    def urlopen(self, *effects):
        return patch.object(self.m.urllib.request, "urlopen", side_effect=list(effects))


class TgResultClassification(_Case):
    def test_parse_error_and_not_modified(self):
        R = self.m.TgResult
        self.assertTrue(R(status=400, description="Bad Request: can't parse entities: x").parse_error)
        self.assertFalse(R(status=403, description="Forbidden: bot was blocked").parse_error)
        self.assertTrue(R(status=400, description="Bad Request: message is not modified").not_modified)
        self.assertTrue(R(status=429).rate_limited)

    def test_side_channel_records_http_reason(self):
        with self.urlopen(_http_error(403, "Forbidden: bot was kicked")):
            self.assertIsNone(self.bot.tg_request("sendMessage", {"chat_id": 5, "text": "x"}))
        res = self.bot.tg_last_result()
        self.assertEqual(res.status, 403)
        self.assertIn("kicked", res.description)


class PlainTextFallback(_Case):
    def test_fallback_only_on_parse_error(self):
        with self.urlopen(_http_error(400, "Bad Request: can't parse entities: bad tag"),
                          _ok(9)) as uo:
            mid = self.bot.send_message("**oi**", chat_id="5")
        self.assertEqual(mid, 9)
        self.assertEqual(uo.call_count, 2)
        second = _payload(uo.call_args_list[1])
        self.assertNotIn("parse_mode", second)
        self.assertNotIn("<b>", second["text"])

    def test_no_fallback_on_forbidden(self):
        with self.urlopen(_http_error(403, "Forbidden: bot was blocked by the user")) as uo:
            mid = self.bot.send_message("oi", chat_id="5")
        self.assertIsNone(mid)
        self.assertEqual(uo.call_count, 1, "a 403 must not trigger a plain-text resend")
        self.assertEqual(self.bot._last_send_outcome().status, "failed")

    def test_no_resend_after_unknown_delivery(self):
        with self.urlopen(socket.timeout("read timed out")) as uo:
            mid = self.bot.send_message("oi", chat_id="5")
        self.assertIsNone(mid)
        self.assertEqual(uo.call_count, 1)
        out = self.bot._last_send_outcome()
        self.assertTrue(out.unknown)
        self.assertEqual(out.status, "unknown")

    def test_failed_chunk_stops_the_rest(self):
        text = "\n\n".join(["parágrafo " * 300] * 3)  # several chunks
        chunks = len(self.bot._split_message(self.bot._markdown_to_html(text)))
        self.assertGreaterEqual(chunks, 2)
        with self.urlopen(_ok(1), _http_error(400, "Bad Request: chat not found"),
                          _ok(3), _ok(4)) as uo:
            mid = self.bot.send_message(text, chat_id="5")
        self.assertIsNone(mid)
        self.assertEqual(uo.call_count, 2, "no chunk may be sent after a failed one")
        out = self.bot._last_send_outcome()
        self.assertEqual((out.sent, out.status), (1, "failed"))

    def test_edit_falls_back_only_on_parse_error(self):
        with self.urlopen(_http_error(400, "Bad Request: can't parse entities"), _ok()) as uo:
            self.assertTrue(self.bot.edit_message(7, "**oi**", chat_id="5"))
        self.assertEqual(uo.call_count, 2)
        with self.urlopen(_http_error(400, "Bad Request: message to edit not found")) as uo:
            self.assertFalse(self.bot.edit_message(7, "**oi**", chat_id="5"))
        self.assertEqual(uo.call_count, 1)


class EditSemantics(_Case):
    def test_not_modified_is_success(self):
        with self.urlopen(_http_error(400, "Bad Request: message is not modified")) as uo:
            self.assertTrue(self.bot.edit_message(7, "igual", chat_id="5"))
        self.assertEqual(uo.call_count, 1)

    def test_final_edit_is_never_truncated(self):
        text = "a & b " * 700  # 4200 raw? no: keep raw under the limit below
        text = text[:3900]
        self.assertLessEqual(len(text), self.m.MAX_MESSAGE_LENGTH)
        self.assertGreater(len(self.bot._markdown_to_html(text)), self.m.MAX_MESSAGE_LENGTH)
        with self.urlopen(_ok()) as uo:
            self.assertFalse(self.bot.edit_message(7, text, chat_id="5"))
        self.assertEqual(uo.call_count, 0)

    def test_preview_edit_truncates(self):
        text = ("a & b " * 700)[:3900]
        with self.urlopen(_ok()) as uo:
            self.assertTrue(self.bot.edit_message(7, text, chat_id="5", preview=True))
        self.assertLessEqual(len(_payload(uo.call_args_list[0])["text"]),
                             self.m.MAX_MESSAGE_LENGTH)


class FinalDelivery(_Case):
    def test_answer_that_grows_past_limit_is_split_not_cut(self):
        text = ("a & b " * 700)[:3900]  # fits raw, not after HTML escaping
        effects = [_ok(100 + i) for i in range(10)]
        with self.urlopen(*effects) as uo:
            status = self.bot._deliver_final_text(text, stream_msg=7, chat_id="5")
        self.assertEqual(status, "delivered")
        methods = [_method(c) for c in uo.call_args_list]
        self.assertGreaterEqual(methods.count("sendMessage"), 2)
        sent = "".join(_payload(c)["text"] for c in uo.call_args_list if _method(c) == "sendMessage")
        self.assertEqual(sent.count("&amp;"), text.count("&"), "every character must arrive")
        # the stream placeholder is retired (edited to ✅) after the answer went out
        self.assertEqual(methods[-1], "editMessageText")
        self.assertEqual(_payload(uo.call_args_list[-1])["text"], "✅")

    def test_edit_path_carries_copy_button(self):
        markup = {"inline_keyboard": [[{"text": "📋 Copiar código", "copy_text": {"text": "x"}}]]}
        with self.urlopen(_ok()) as uo:
            status = self.bot._deliver_final_text("curta", 7, markup, chat_id="5")
        self.assertEqual(status, "delivered")
        self.assertEqual(_payload(uo.call_args_list[0])["reply_markup"], markup)

    def test_stream_message_deleted_when_it_cannot_be_edited(self):
        with self.urlopen(_http_error(400, "Bad Request: message to edit not found"),
                          _ok(50),
                          _http_error(400, "Bad Request: message to edit not found"),
                          _ok()) as uo:
            status = self.bot._deliver_final_text("curta", 7, chat_id="5")
        self.assertEqual(status, "delivered")
        self.assertEqual([_method(c) for c in uo.call_args_list],
                         ["editMessageText", "sendMessage", "editMessageText", "deleteMessage"])

    def test_transient_failure_schedules_one_retry_and_keeps_registration(self):
        self.bot._tg_set_last(self.m.TgResult(status=502, description="Bad Gateway"))
        with patch.object(self.m.threading, "Timer") as timer, \
                patch.object(self.bot, "_cache_response") as cache, \
                patch.object(self.bot, "_post_delivery_notice") as notice:
            settled = self.bot._handle_undelivered_final("failed", "texto", 7, None, "5", None)
        self.assertFalse(settled, "a retried delivery must stay registered")
        timer.assert_called_once()
        cache.assert_called_once()
        self.assertIn("nova tentativa", notice.call_args.args[3])

    def test_unknown_delivery_is_not_retried(self):
        self.bot._tg_set_last(self.m.TgResult(delivery_unknown=True))
        with patch.object(self.m.threading, "Timer") as timer, \
                patch.object(self.bot, "_post_delivery_notice") as notice:
            settled = self.bot._handle_undelivered_final("unknown", "texto", 7, None, "5", None)
        self.assertTrue(settled)
        timer.assert_not_called()
        self.assertIn("Não sei se a resposta chegou", notice.call_args.args[3])

    def test_retry_success_unregisters(self):
        with patch.object(self.bot, "_deliver_final_text", return_value="delivered"), \
                patch.object(self.bot, "_uncache_response") as uncache:
            self.bot._retry_final_delivery("texto", 7, None, "5", None)
        self.bot._active_msgs.unregister.assert_called_once_with(7)
        uncache.assert_called_once_with(7)


class RateLimiting(_Case):
    def test_streaming_preview_dropped_while_throttled(self):
        self.bot._tg_limiter().block("5", 30)
        with self.urlopen(_ok()) as uo:
            self.assertFalse(self.bot.edit_message(7, "parcial", chat_id="5", preview=True))
        self.assertEqual(uo.call_count, 0)
        self.sleep.assert_not_called()

    def test_chat_action_dropped_while_throttled(self):
        self.bot._tg_limiter().block("5", 30)
        with self.urlopen(_ok()) as uo:
            self.bot.tg_request("sendChatAction", {"chat_id": "5", "action": "typing"})
        self.assertEqual(uo.call_count, 0)

    def test_final_delivery_waits_out_the_block(self):
        self.bot._tg_limiter().block("5", 20)
        with self.urlopen(_ok()) as uo:
            self.assertTrue(self.bot.edit_message(7, "final", chat_id="5"))
        self.assertEqual(uo.call_count, 1)
        self.assertGreaterEqual(max(c.args[0] for c in self.sleep.call_args_list), 19)

    def test_429_retry_after_is_honored_in_full(self):
        with self.urlopen(_http_error(429, "Too Many Requests: retry after 45", 45),
                          _ok(3)) as uo:
            mid = self.bot.send_message("oi", chat_id="5")
        self.assertEqual(mid, 3)
        self.assertEqual(uo.call_count, 2)
        self.assertGreaterEqual(max(c.args[0] for c in self.sleep.call_args_list), 44,
                                "retry_after must not be capped at 30s")

    def test_429_beyond_budget_gives_up_and_blocks_chat(self):
        with self.urlopen(_http_error(429, "Too Many Requests", 600), _ok()) as uo:
            self.assertIsNone(self.bot.tg_request("sendMessage", {"chat_id": "5", "text": "x"}))
        self.assertEqual(uo.call_count, 1)
        self.assertTrue(self.bot.tg_last_result().rate_limited)
        self.assertGreater(self.bot._tg_limiter().blocked_for("5"), 500)

    def test_group_window_and_preview_headroom(self):
        lim = self.m.TelegramRateLimiter(clock=lambda: 1000.0)
        cap, _window, headroom = self.m.TG_GROUP_WINDOW
        for _ in range(cap - headroom):
            self.assertEqual(lim.reserve("-100", droppable=True), 0)
        self.assertIsNone(lim.reserve("-100", droppable=True), "previews keep headroom free")
        for _ in range(headroom):
            self.assertEqual(lim.reserve("-100"), 0)
        delay = lim.reserve("-100")
        self.assertGreater(delay, 0, "21st group message in a minute must wait")

    def test_private_chat_paced(self):
        lim = self.m.TelegramRateLimiter(clock=lambda: 50.0)
        cap = self.m.TG_PRIVATE_WINDOW[0]
        for _ in range(cap):
            self.assertEqual(lim.reserve("5"), 0)
        self.assertGreater(lim.reserve("5"), 0)


class Polling(_Case):
    def setUp(self):
        super().setUp()
        self.bot._update_offset = 0
        self.bot._stop_event = MagicMock()

    def test_409_backs_off_deletes_webhook_once_and_alerts_once(self):
        conflict = _http_error(409, "Conflict: terminated by other getUpdates request")
        calls = []

        def fake_urlopen(req, timeout=None):
            method = _method(MagicMock(args=(req,)))
            calls.append(method)
            if method == "getUpdates":
                raise _http_error(409, "Conflict: terminated by other getUpdates request")
            return _ok()

        with patch.object(self.m.urllib.request, "urlopen", side_effect=fake_urlopen):
            self.assertEqual(self.bot._poll_updates(), [])
            self.assertEqual(self.bot._poll_updates(), [])
        del conflict
        self.assertEqual(calls.count("deleteWebhook"), 1)
        self.assertEqual(calls.count("sendMessage"), 1, "the conflict alert is throttled")
        waits = [c.args[0] for c in self.bot._stop_event.wait.call_args_list]
        self.assertEqual(waits, [5.0, 10.0])

    def test_backoff_caps_and_resets(self):
        self.assertEqual(self.bot._poll_backoff_delay(1), 5.0)
        self.assertEqual(self.bot._poll_backoff_delay(10), 60.0)
        self.bot._poll_fail_streak = 4
        ok = _ok()
        ok.read.return_value = json.dumps({"ok": True, "result": []}).encode()
        with self.urlopen(ok):
            self.bot._poll_updates()
        self.assertEqual(self.bot._poll_fail_streak, 0)

    def test_401_backs_off(self):
        with self.urlopen(_http_error(401, "Unauthorized"), _http_error(401, "Unauthorized")):
            self.assertEqual(self.bot._poll_updates(), [])
        self.bot._stop_event.wait.assert_called_once_with(5.0)


class OffsetPersistence(_Case):
    def test_atomic_save_and_load(self):
        self.bot._save_offset(42)
        self.assertEqual(self.bot._load_offset(), 42)
        f = self.m.DATA_DIR / "telegram_offset.json"
        with patch.object(self.m.os, "replace", side_effect=OSError("disk full")):
            self.bot._save_offset(99)
        self.assertEqual(json.loads(f.read_text())["offset"], 42,
                         "a failed write must leave the previous offset intact")

    def test_corrupt_offset_logs_warning(self):
        f = self.m.DATA_DIR / "telegram_offset.json"
        f.write_text("{trunc")
        with self.assertLogs(self.m.logger, level="WARNING") as cm:
            self.assertEqual(self.bot._load_offset(), 0)
        self.assertTrue(any("unreadable" in m for m in cm.output))
        f.unlink()


class Uploads(_Case):
    def test_multipart_json_encodes_objects(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'rel"at.pdf'
            p.write_bytes(b"%PDF")
            body, ctype = self.bot._build_multipart(p, "document", {
                "chat_id": "5",
                "reply_parameters": {"message_id": 3, "allow_sending_without_reply": True},
                "disable_notification": True,
            })
        text = body.decode("utf-8", "replace")
        self.assertIn('{"message_id": 3, "allow_sending_without_reply": true}', text)
        self.assertNotIn("'message_id'", text, "Python repr must never reach Telegram")
        self.assertIn("\r\n\r\ntrue\r\n", text)
        self.assertIn('filename="rel%22at.pdf"', text)
        self.assertIn("Content-Type: application/pdf", text)
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))

    def test_mime_types(self):
        for name, mime in (("a.png", "image/png"), ("a.csv", "text/csv"),
                           ("a.json", "application/json"), ("a.zip", "application/zip"),
                           ("a.ogg", "audio/ogg"), ("a.md", "text/markdown")):
            self.assertEqual(self.bot._upload_mime(Path(name)), mime, name)

    def test_upload_timeout_scales(self):
        self.assertEqual(self.bot._upload_timeout(0), 15.0)
        self.assertAlmostEqual(self.bot._upload_timeout(1_000_000), 25.0)
        self.assertEqual(self.bot._upload_timeout(50_000_000), 120.0)

    def test_document_reply_uses_reply_parameters(self):
        captured = {}

        def fake_upload(method, path, file_field="voice", data=None):
            captured.update(data)
            return {"ok": True, "result": {"message_id": 8}}

        self.bot._tg_upload_file = fake_upload
        mid = self.bot._send_as_document("x", chat_id="5", reply_to_message_id=3)
        self.assertEqual(mid, 8)
        self.assertNotIn("reply_to_message_id", captured)
        self.assertEqual(captured["reply_parameters"]["message_id"], 3)


class Downloads(_Case):
    def test_over_20mb_is_refused_with_reason(self):
        self.bot.tg_request = lambda m, d=None, timeout=15: {
            "ok": True, "result": {"file_path": "documents/big.zip",
                                   "file_size": 25 * 1024 * 1024}}
        with self.urlopen() as uo:
            self.assertIsNone(self.bot._download_telegram_file("fid"))
        self.assertEqual(uo.call_count, 0)
        self.assertIn("20 MB", self.bot._download_failure_text("generic"))

    def test_getfile_too_big_error_has_reason(self):
        with self.urlopen(_http_error(400, "Bad Request: file is too big")):
            self.assertIsNone(self.bot._download_telegram_file("fid"))
        self.assertIn("20 MB", self.bot._download_failure_text("generic"))

    def test_same_name_in_same_second_does_not_collide(self):
        self.bot.tg_request = lambda m, d=None, timeout=15: {
            "ok": True, "result": {"file_path": "photos/file_1.jpg", "file_size": 10}}
        content = MagicMock()
        content.read.return_value = b"img"
        content.__enter__ = lambda s: s
        content.__exit__ = lambda s, *a: False
        with tempfile.TemporaryDirectory() as d, \
                patch.object(self.m.time, "time", return_value=1700000000.0), \
                self.urlopen(content, content):
            a = self.bot._download_telegram_file("1", save_dir=Path(d), preferred_name="image.jpg")
            b = self.bot._download_telegram_file("2", save_dir=Path(d), preferred_name="image.jpg")
        self.assertNotEqual(a, b)
        self.assertEqual(self.bot._download_failure_text("generic"), "generic")


class InflightRecovery(_Case):
    def _marker(self, ts):
        d = self.m.INFLIGHT_DIR
        d.mkdir(parents=True, exist_ok=True)
        p = d / "s1.json"
        p.write_text(json.dumps({"prompt": "qual o preço do BTC?", "chat_id": "5",
                                 "thread_id": None, "ts": ts}))
        self.addCleanup(lambda: p.unlink() if p.exists() else None)
        return p

    def test_notice_tells_the_truth_and_clears_marker(self):
        p = self._marker(self.m.time.time())
        with self.urlopen(_ok()) as uo:
            self.bot._recover_inflight_prompts()
        text = _payload(uo.call_args_list[0])["text"]
        self.assertNotIn("reenviando", text)
        self.assertIn("Reenvie se ainda quiser", text)
        self.assertFalse(p.exists())

    def test_marker_kept_when_notice_fails(self):
        p = self._marker(self.m.time.time())
        with self.urlopen(_http_error(400, "Bad Request: chat not found")):
            self.bot._recover_inflight_prompts()
        self.assertTrue(p.exists(), "an undelivered notice must be retried next startup")


if __name__ == "__main__":
    unittest.main()
