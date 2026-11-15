"""Telegram date_time entity (<tg-time>) helpers and their path through the
HTML converter, sanitizer, chunk rebalancer, rich escaper and plain fallback.
All Telegram I/O is mocked."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._botload import load_bot_module
from tests.test_telegram_delivery import _http_error, _ok, _payload

UNIX = 1794751200  # 2026-11-15 11:00 -03


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.m = load_bot_module(tmp_home=Path(cls._tmp.name))
        cls.B = cls.m.ClaudeTelegramBot

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()


class Helper(_Case):
    def test_tag_shape(self):
        t = self.m.tg_time(UNIX, "wDT")
        self.assertTrue(t.startswith(f'<tg-time unix="{UNIX}" format="wDT">'))
        self.assertTrue(t.endswith("</tg-time>"))
        self.assertNotEqual(self.B._strip_html_tags(t).strip(), "")

    def test_invalid_format_falls_back(self):
        self.assertIn('format="dt"', self.m.tg_time(UNIX, "xyz"))

    def test_format_regex(self):
        for ok in ("", "r", "w", "wDT", "dt", "T", "wd"):
            self.assertTrue(self.m._tg_time_valid_format(ok), ok)
        for bad in ("rw", "tw", "dd", "x"):
            self.assertFalse(self.m._tg_time_valid_format(bad), bad)

    def test_text_is_escaped(self):
        self.assertIn("a &amp; b", self.m.tg_time(UNIX, "t", text="a & b"))

    def test_to_plain(self):
        self.assertEqual(self.m._tg_time_to_plain(f'x <tg-time unix="{UNIX}">amanhã</tg-time> y'),
                         "x amanhã y")
        self.assertNotIn("<", self.m._tg_time_to_plain(f'<tg-time unix="{UNIX}" format="t"/>'))

    def test_local_unix_today(self):
        self.assertIsNotNone(self.m._local_unix_today("09:30"))
        self.assertIsNone(self.m._local_unix_today("interval-1"))
        self.assertIsNone(self.m._local_unix_today("25:00"))


class HtmlPath(_Case):
    def test_markdown_keeps_tag(self):
        src = f'**Reunião** <tg-time unix="{UNIX}" format="wDT">dom 11h</tg-time> & mais'
        out = self.B._markdown_to_html(src)
        self.assertIn(f'<tg-time unix="{UNIX}" format="wDT">dom 11h</tg-time>', out)
        self.assertIn("<b>Reunião</b>", out)
        self.assertIn("&amp; mais", out)

    def test_self_closing_gets_text(self):
        out = self.B._markdown_to_html(f'<tg-time unix="{UNIX}" format="t"/>')
        self.assertRegex(out, r'<tg-time unix="\d+" format="t">\d\d:\d\d</tg-time>')

    def test_invalid_tag_degrades_to_text(self):
        out = self.B._markdown_to_html('<tg-time unix="soon">logo</tg-time>')
        self.assertEqual(out, "logo")

    def test_inside_code_stays_literal(self):
        out = self.B._markdown_to_html(f'`<tg-time unix="{UNIX}">x</tg-time>`')
        self.assertIn("&lt;tg-time", out)

    def test_bot_tag_inside_bold(self):
        out = self.B._markdown_to_html(f"*Início:* {self.m.tg_time(UNIX, 't')}")
        self.assertIn('<tg-time unix=', out)

    def test_table_uses_plain_text(self):
        src = f"| a | b |\n|---|---|\n| x | <tg-time unix=\"{UNIX}\">dom 11h</tg-time> |"
        out = self.B._markdown_to_html(src)
        self.assertNotIn("tg-time", out)
        self.assertIn("dom 11h", out)

    def test_sanitizer(self):
        s = self.B._sanitize_telegram_html
        good = f'<tg-time unix="{UNIX}" format="t">11:00</tg-time>'
        self.assertEqual(s(good), good)
        self.assertEqual(s('<tg-time format="t">11:00</tg-time>'), "11:00")
        self.assertEqual(s(f'<tg-time unix="{UNIX}">x'), f'<tg-time unix="{UNIX}">x</tg-time>')

    def test_rebalance(self):
        a, b = self.B._rebalance_html_chunks([f'<tg-time unix="{UNIX}">dom', ' 11h</tg-time>'])
        self.assertTrue(a.endswith("</tg-time>"))
        self.assertTrue(b.startswith(f'<tg-time unix="{UNIX}">'))


class RichPath(_Case):
    def test_rich_markdown_keeps_tag(self):
        tag = f'<tg-time unix="{UNIX}" format="wDT">dom ~11h $5</tg-time>'
        md = self.m._rich_markdown_from_model(f"Custa $5 em {tag}")
        self.assertIn(f'<tg-time unix="{UNIX}" format="wDT">dom ~11h $5</tg-time>', md)
        self.assertIn("\\$5 em", md)


class StatusMessages(_Case):
    def test_status_message_start_line(self):
        msg = self.m._format_status_message("Rotina: x — FAILED", started_at=UNIX, duration_seconds=70)
        self.assertIn("🕐 Início: <tg-time", msg)
        self.assertIn("⏱️ Duração: 1m10s", msg)

    def test_routine_time_label(self):
        self.assertIn("<tg-time", self.B._routine_time_label({"time": "08:30"}))
        self.assertEqual(self.B._routine_time_label({"time": "every-30m"}), "`every-30m`")

    def test_system_prompt_mentions_tag(self):
        self.assertIn("<tg-time", self.m.SYSTEM_PROMPT)


class SendFallback(_Case):
    def setUp(self):
        self.bot = self.B.__new__(self.B)
        self.bot.base_url = "https://api.telegram.org/botTEST"
        self.bot.token = "TEST"
        self.bot._ctx_local = threading.local()
        self.bot._active_msgs = MagicMock()
        self.bot.primary_chat_ids = {"111"}
        patch.object(self.m.time, "sleep").start()
        self.addCleanup(patch.stopall)

    def test_html_send_then_plain_fallback_is_readable(self):
        text = f"Próxima: {self.m.tg_time(UNIX, 'dt')}"
        with patch.object(self.m.urllib.request, "urlopen", side_effect=[
                _http_error(400, "Bad Request: can't parse entities"), _ok(7)]) as uo:
            self.bot.send_message(text, chat_id="5")
        first, second = _payload(uo.call_args_list[0]), _payload(uo.call_args_list[1])
        self.assertIn("<tg-time unix=", first["text"])
        self.assertEqual(first["parse_mode"], "HTML")
        self.assertNotIn("<", second["text"])
        self.assertRegex(second["text"], r"Próxima: \d\d/\d\d/\d{4} \d\d:\d\d")


if __name__ == "__main__":
    unittest.main()
