"""Colored inline buttons (Bot API 9.4 ``InlineKeyboardButton.style``).

Covers the ``_btn`` helper, where colors are applied, and the safety net in
``_tg_call`` / ``_rich_request``: a 400 blaming ``style`` re-sends once without
colors and turns them off for the process. All Telegram I/O is faked.
"""
import threading
import unittest
from unittest.mock import MagicMock

from tests._botload import load_bot_module


class _Case(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def setUp(self):
        self.m._BUTTON_STYLE_OFF = False
        self.m._RICH_BUTTONS_OFF = False
        self.addCleanup(setattr, self.m, "_BUTTON_STYLE_OFF", False)
        self.addCleanup(setattr, self.m, "_RICH_BUTTONS_OFF", False)
        cls = self.m.ClaudeTelegramBot
        self.bot = cls.__new__(cls)
        self.bot._ctx_local = threading.local()

    def styled_markup(self):
        return {"inline_keyboard": [[
            self.m._btn("✅ Aprovar", "approve:1", style="success"),
            self.m._btn("❌ Cancelar", "reject:1", style="danger"),
        ]]}


class BtnHelper(_Case):
    def test_known_styles_kept(self):
        for style in ("primary", "success", "danger"):
            self.assertEqual(self.m._btn("x", "d", style=style)["style"], style)

    def test_unknown_or_missing_style_dropped(self):
        self.assertNotIn("style", self.m._btn("x", "d", style="link"))
        self.assertNotIn("style", self.m._btn("x", "d"))

    def test_url_button(self):
        self.assertEqual(self.m._btn("Site", url="https://t.me"),
                         {"text": "Site", "url": "https://t.me"})

    def test_strip_is_a_copy(self):
        markup = self.styled_markup()
        stripped = self.m._strip_button_styles(markup)
        self.assertFalse(self.m._markup_has_styles(stripped))
        self.assertTrue(self.m._markup_has_styles(markup))  # input untouched
        self.assertEqual(stripped["inline_keyboard"][0][0],
                         {"text": "✅ Aprovar", "callback_data": "approve:1"})

    def test_has_styles_tolerates_junk(self):
        for junk in (None, {}, {"inline_keyboard": None}, {"inline_keyboard": [None, ["x"]]}):
            self.assertFalse(self.m._markup_has_styles(junk))


class TgCallSafetyNet(_Case):
    def _fake_raw(self, *results):
        calls = []
        queue = list(results)

        def raw(method, data=None, **kw):
            calls.append((method, data))
            return queue.pop(0)
        self.bot._tg_call_raw = raw
        return calls

    def test_style_rejection_resends_once_without_colors(self):
        T = self.m.TgResult
        calls = self._fake_raw(
            T(status=400, description='Bad Request: field "style" is invalid'),
            T(ok=True, status=200, body={"ok": True, "result": {"message_id": 9}}))
        res = self.bot._tg_call("sendMessage", {"chat_id": 1, "text": "oi",
                                                "reply_markup": self.styled_markup()})
        self.assertTrue(res.ok)
        self.assertEqual(len(calls), 2)
        self.assertTrue(self.m._markup_has_styles(calls[0][1]["reply_markup"]))
        self.assertFalse(self.m._markup_has_styles(calls[1][1]["reply_markup"]))
        self.assertTrue(self.m._BUTTON_STYLE_OFF)

    def test_after_switch_colors_stripped_up_front(self):
        self.m._BUTTON_STYLE_OFF = True
        T = self.m.TgResult
        calls = self._fake_raw(T(ok=True, status=200, body={"ok": True}))
        self.bot._tg_call("sendMessage", {"chat_id": 1, "text": "oi",
                                          "reply_markup": self.styled_markup()})
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.m._markup_has_styles(calls[0][1]["reply_markup"]))

    def test_other_400_not_retried(self):
        T = self.m.TgResult
        calls = self._fake_raw(T(status=400, description="Bad Request: chat not found"))
        res = self.bot._tg_call("sendMessage", {"chat_id": 1, "text": "oi",
                                                "reply_markup": self.styled_markup()})
        self.assertFalse(res.ok)
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.m._BUTTON_STYLE_OFF)

    def test_unstyled_payload_never_retried(self):
        T = self.m.TgResult
        calls = self._fake_raw(T(status=400, description="style something"))
        self.bot._tg_call("sendMessage", {"chat_id": 1, "text": "oi"})
        self.assertEqual(len(calls), 1)
        self.assertFalse(self.m._BUTTON_STYLE_OFF)


class RichRequestSafetyNet(_Case):
    def test_reply_markup_style_rejection_on_rich_send(self):
        once = MagicMock(side_effect=[
            {"ok": False, "error_code": 400, "description": "Bad Request: invalid button style"},
            {"ok": True, "result": {"message_id": 3}}])
        self.bot._rich_request_once = once
        resp = self.bot._rich_request("sendRichMessage", {
            "chat_id": 1, "rich_message": {"markdown": "oi"},
            "reply_markup": self.styled_markup()})
        self.assertTrue(resp["ok"])
        self.assertEqual(once.call_count, 2)
        self.assertFalse(self.m._markup_has_styles(once.call_args_list[1].args[1]["reply_markup"]))
        self.assertTrue(self.m._BUTTON_STYLE_OFF)


class ColorsApplied(_Case):
    def test_busy_choice_card_colors(self):
        self.bot.send_message = MagicMock(return_value=None)  # no card → resolves now
        self.bot._resolve_busy_choice = MagicMock()
        ctx = self.m.ThreadContext(chat_id="1")
        ctx.runner = MagicMock()
        ctx.runner.can_inject.return_value = True
        self.bot._offer_busy_choice(ctx, "oi", 7)
        row = self.bot.send_message.call_args.kwargs["reply_markup"]["inline_keyboard"][0]
        styles = {b["callback_data"].rsplit(":", 1)[1]: b.get("style") for b in row}
        self.assertEqual(styles, {"now": "success", "later": None, "stop": "danger"})

    def test_stream_stop_button_is_red(self):
        self.bot._reasoning_toggles = {}
        row = self.bot._reasoning_button_markup(1)["inline_keyboard"][0]
        self.assertEqual([b.get("style") for b in row], [None, "danger"])


if __name__ == "__main__":
    unittest.main()
