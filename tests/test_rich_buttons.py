"""Buttons inside the model's answer (Bot API 10.3 RichBlockButtons).

Token syntax → native <tg-button-row> on the rich path, links/labels on the
HTML path, native tags the model writes itself, the rejection fallback, and
the reply-button callback. All Telegram I/O is faked.
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
        self.m._RICH_BUTTONS_OFF = False
        self.m._BUTTON_STYLE_OFF = False
        self.addCleanup(setattr, self.m, "_RICH_BUTTONS_OFF", False)
        self.addCleanup(setattr, self.m, "_BUTTON_STYLE_OFF", False)


class RichRendering(_Case):
    def test_row_becomes_native_block(self):
        md = self.m._rich_markdown_from_model(
            "Posso publicar?\n"
            "[button success: Sim](reply) [button danger: Não](reply: não, cancela) "
            "[button: Site](https://x.com/a?b=1&c=2)")
        lines = md.split("\n")
        self.assertEqual(lines[0], "Posso publicar?")
        start = lines.index("<tg-button-row>")
        self.assertEqual(lines[start - 1], "")           # standalone HTML block
        end = lines.index("</tg-button-row>")
        self.assertEqual(lines[end + 1], "")
        btns = lines[start + 1:end]
        self.assertEqual(btns[0], '<tg-button type="callback_data" data="rbtn:Sim" '
                                  'style="success">Sim</tg-button>')
        self.assertIn('data="rbtn:não, cancela" style="danger">Não<', btns[1])
        self.assertEqual(btns[2], '<tg-button type="url" '
                                  'url="https://x.com/a?b=1&amp;c=2">Site</tg-button>')

    def test_label_is_escaped_not_markdown_escaped(self):
        md = self.m._rich_markdown_from_model("[button: R$ 5 <b>](https://x.com)")
        self.assertIn(">R$ 5 &lt;b&gt;</tg-button>", md)

    def test_token_inside_sentence_becomes_link_or_label(self):
        md = self.m._rich_markdown_from_model(
            "Veja [button: o site](https://y.com) ou diga [button: sim](reply).")
        self.assertNotIn("<tg-button", md)
        self.assertIn("[o site](https://y.com)", md)
        self.assertIn("diga sim.", md)

    def test_code_untouched(self):
        text = "Use `[button: x](reply)` assim:\n```\n[button: y](reply)\n```"
        self.assertEqual(self.m._rich_markdown_from_model(text), text)

    def test_command_reply_is_never_a_button(self):
        md = self.m._rich_markdown_from_model("[button: Apagar](reply: /delete main)")
        self.assertNotIn("<tg-button", md)
        self.assertIn("Apagar", md)
        md2 = self.m._rich_markdown_from_model("[button: /stop](reply)")
        self.assertNotIn("<tg-button", md2)

    def test_long_reply_goes_through_cb_ref(self):
        long = "por favor " * 20
        md = self.m._rich_markdown_from_model(f"[button: Ok](reply: {long})")
        data = md.split('data="', 1)[1].split('"', 1)[0]
        self.assertTrue(data.startswith(self.m.CALLBACK_REF_PREFIX))
        self.assertLessEqual(len(data.encode()), 64)
        self.assertEqual(self.m._resolve_cb_data(data), "rbtn:" + long.strip())

    def test_buttons_off_renders_plain(self):
        self.m._RICH_BUTTONS_OFF = True
        md = self.m._rich_markdown_from_model("[button: Site](https://x.com) [button: Sim](reply)")
        self.assertNotIn("<tg-button", md)
        self.assertIn("[Site](https://x.com) · Sim", md)

    def test_native_tags_only_links_survive(self):
        md = self.m._rich_markdown_from_model(
            '<tg-button-row align="center">\n'
            '<tg-button type="url" style="success" url="https://t.me">Abrir</tg-button>\n'
            '<tg-button type="callback_data" data="delete_session:main">Ok</tg-button>\n'
            '</tg-button-row>')
        self.assertIn('url="https://t.me" style="success">Abrir</tg-button>', md)
        self.assertNotIn("delete_session", md)
        self.assertIn("Ok", md)


class HtmlFallback(_Case):
    def test_row_becomes_links_and_labels(self):
        html_out = self.m.ClaudeTelegramBot._markdown_to_html(
            "Escolha:\n[button: Site](https://x.com) [button success: Sim](reply)")
        self.assertIn('<a href="https://x.com">Site</a> · Sim', html_out)
        self.assertNotIn("[button", html_out)

    def test_native_tags_never_shown_raw(self):
        html_out = self.m.ClaudeTelegramBot._markdown_to_html(
            '<tg-button-row>\n<tg-button type="url" url="https://t.me">Abrir</tg-button>\n'
            '</tg-button-row>')
        self.assertNotIn("tg-button", html_out)
        self.assertIn('<a href="https://t.me">Abrir</a>', html_out)

    def test_code_kept_verbatim(self):
        html_out = self.m.ClaudeTelegramBot._markdown_to_html("`[button: x](reply)`")
        self.assertIn("[button: x](reply)", html_out)


class RejectionFallback(_Case):
    def setUp(self):
        super().setUp()
        cls = self.m.ClaudeTelegramBot
        self.bot = cls.__new__(cls)
        self.bot._ctx_local = threading.local()

    def test_button_rejection_resends_as_links_and_disables(self):
        md = self.m._rich_markdown_from_model("Oi\n[button: Site](https://x.com) [button: Sim](reply)")
        once = MagicMock(side_effect=[
            {"ok": False, "error_code": 400, "description": "Bad Request: BUTTON_TYPE_INVALID"},
            {"ok": True, "result": {"message_id": 3}}])
        self.bot._rich_request_once = once
        resp = self.bot._rich_request("sendRichMessage",
                                      {"chat_id": 1, "rich_message": {"markdown": md}})
        self.assertTrue(resp["ok"])
        resent = once.call_args_list[1].args[1]["rich_message"]["markdown"]
        self.assertNotIn("tg-button", resent)
        self.assertIn("[Site](https://x.com)", resent)
        self.assertTrue(self.m._RICH_BUTTONS_OFF)

    def test_unrelated_rejection_not_retried(self):
        once = MagicMock(return_value={"ok": False, "error_code": 400,
                                       "description": "Bad Request: chat not found"})
        self.bot._rich_request_once = once
        self.bot._rich_request("sendRichMessage",
                               {"chat_id": 1, "rich_message": {"markdown": "<tg-button-row>"}})
        self.assertEqual(once.call_count, 1)
        self.assertFalse(self.m._RICH_BUTTONS_OFF)


class ReplyButtonCallback(_Case):
    def setUp(self):
        super().setUp()
        cls = self.m.ClaudeTelegramBot
        self.bot = cls.__new__(cls)
        self.bot._ctx_local = threading.local()
        self.bot.answer_callback = MagicMock()
        self.bot.send_message = MagicMock(return_value=77)
        self.bot._handle_text = MagicMock()

    def _tap(self, data):
        self.bot._handle_callback({"id": "cb1", "data": data,
                                   "message": {"message_id": 10, "chat": {"id": 1}}})

    def test_tap_runs_as_user_message(self):
        self._tap("rbtn:Sim, pode publicar")
        self.bot.answer_callback.assert_called_once_with("cb1", "💬 Enviado")
        self.assertEqual(self.bot.send_message.call_args.args[0], "💬 Sim, pode publicar")
        self.assertEqual(self.bot.send_message.call_args.kwargs["reply_to_message_id"], 10)
        self.bot._handle_text.assert_called_once_with("Sim, pode publicar", user_msg_id=77)

    def test_tap_via_cb_ref(self):
        long = "texto comprido " * 10
        self._tap(self.m._cb_data("rbtn:" + long))
        self.bot._handle_text.assert_called_once_with(long.strip(), user_msg_id=77)

    def test_command_tap_refused(self):
        self._tap("rbtn:/delete main")
        self.bot._handle_text.assert_not_called()
        self.bot.send_message.assert_not_called()
        self.bot.answer_callback.assert_called_once_with("cb1", "Esse botão não pode ser usado.")

    def test_echo_failure_still_handles(self):
        self.bot.send_message.return_value = None
        self._tap("rbtn:ok")
        self.bot._handle_text.assert_called_once_with("ok", user_msg_id=None)


if __name__ == "__main__":
    unittest.main()
