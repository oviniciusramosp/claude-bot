"""v3.94 UX: buttons go away after a tap, drafts don't type the answer
letter by letter, effects are opt-in, and voice notes use the SpeechAnalyzer
transcriber with hear as fallback."""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._botload import load_bot_module
from tests.test_bot_integration import _BotFixture


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.fx = _BotFixture(Path(self._td.name))
        self.addCleanup(self.fx.cleanup)
        self.bot, self.m = self.fx.bot, self.fx.bot_module
        self.calls = []
        self.bot.tg_request = lambda method, data=None, timeout=15: (
            self.calls.append((method, data)) or {"ok": True, "result": {"message_id": 1}})
        self.rich = []
        self.bot._rich_request_once = lambda method, data, timeout=30: (
            self.rich.append((method, data)) or {"ok": True, "result": {"message_id": 77}})


class TappedButtons(_Base):
    def cb(self, data, rows, mid=5):
        return {"id": "c", "data": data, "message": {
            "message_id": mid, "chat": {"id": 123456789},
            "reply_markup": {"inline_keyboard": rows}}}

    def test_choices_removed_links_kept(self):
        rows = [[{"text": "A", "callback_data": "model:opus"}],
                [{"text": "site", "url": "https://x.y"}]]
        self.bot._retire_tapped_buttons(self.cb("model:opus", rows), "model:opus")
        method, data = self.calls[-1]
        self.assertEqual(method, "editMessageReplyMarkup")
        self.assertEqual(data["reply_markup"], {"inline_keyboard": [[{"text": "site", "url": "https://x.y"}]]})

    def test_voice_choice_keeps_its_buttons(self):
        rows = [[{"text": "Áudio", "callback_data": "voicepick:a:audio"}]]
        self.bot._retire_tapped_buttons(self.cb("voicepick:a:audio", rows), "voicepick:a:audio")
        self.assertEqual(self.calls, [])

    def test_answer_buttons_are_edited_out_of_the_text(self):
        md = "Resposta.\n\n<tg-button-row>\n<tg-button>Sim</tg-button>\n</tg-button-row>\n"
        self.bot._rich_request("sendRichMessage", {"chat_id": 123456789, "rich_message": {"markdown": md}})
        copy = [[{"text": "Copiar", "copy_text": {"text": "x"}}]]
        self.bot._retire_tapped_buttons(self.cb("rbtn:Sim", copy, mid=77), "rbtn:Sim")
        method, data = self.rich[-1]
        self.assertEqual(method, "editMessageText")
        self.assertEqual(data["message_id"], 77)
        self.assertEqual(data["rich_message"]["markdown"], "Resposta.")
        self.assertEqual(data["reply_markup"], {"inline_keyboard": copy})

    def test_strip_rows(self):
        self.assertEqual(self.m._strip_rich_button_rows(
            "a\n\n<tg-button-row><tg-button>x</tg-button></tg-button-row>\n\nb"), "a\n\nb")


class DraftWithoutLiveAnswer(_Base):
    def test_answer_text_not_streamed_by_default(self):
        self.assertFalse(self.m.LIVE_DRAFT_ANSWER)
        runner = MagicMock()
        runner.get_reasoning_entries.return_value = []
        text, _ = self.bot._build_draft_display("Olá mundo, resposta longa", runner)
        self.assertEqual(text, self.m.LIVE_DRAFT_WRITING)
        self.assertNotIn("Olá", text)

    def test_effects_are_opt_in(self):
        self.assertFalse(self.m.MESSAGE_EFFECTS_ENABLED)


class SentenceBySentence(unittest.TestCase):
    """v3.95: previews grow by whole sentences."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def test_prefix(self):
        f = self.m._sentence_prefix
        self.assertEqual(f("Olá. Tudo bem? Estou escre"), "Olá. Tudo bem?")
        self.assertEqual(f("sem ponto ainda"), "")
        self.assertEqual(f("linha um\nlinha do"), "linha um")
        self.assertEqual(f("Valor 3.5 mil e"), "")

    def test_draft_hands_over_to_a_message_when_the_answer_starts(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        fx = _BotFixture(Path(td.name))
        self.addCleanup(fx.cleanup)
        bot = fx.bot
        ctx = bot._get_context("123456789", None)
        ctx.draft_id = 9
        runner = MagicMock()
        runner.get_snapshot.return_value = "Primeira frase. Segunda"
        with patch.object(bot, "_send_stream_placeholder") as ph, \
                patch.object(bot, "_send_draft") as draft:
            bot._stream_draft_tick(ctx, runner, time.time())
        self.assertTrue(ph.called)
        self.assertFalse(draft.called)
        self.assertEqual(ctx.draft_id, 0)


class VoiceTranscription(_Base):
    def _voice(self, native, hear):
        b = self.bot
        b._voice_tools = {"transcribe": "/x/transcribe", "ffmpeg": "/x/ffmpeg", "hear": "/x/hear",
                          "can_transcribe": True}
        audio = Path(self._td.name) / "a.ogg"
        audio.write_bytes(b"x")
        prompts = []
        with patch.object(b, "_download_telegram_file", return_value=audio), \
                patch.object(b, "_transcribe_native", return_value=native) as nat, \
                patch.object(b, "_convert_ogg_to_wav", return_value=audio.with_suffix(".wav")), \
                patch.object(b, "_transcribe_audio", return_value=hear) as hr, \
                patch.object(b, "_voice_status"), \
                patch.object(b, "_run_claude_prompt", lambda p, **k: prompts.append(p)):
            b._handle_voice({"voice": {"file_id": "f", "duration": 3}})
        return prompts, nat, hr

    def test_native_transcriber_first(self):
        prompts, nat, hr = self._voice("Texto completo.", "parcial")
        self.assertTrue(nat.called)
        self.assertFalse(hr.called)
        self.assertIn("Texto completo.", prompts[0])

    def test_falls_back_to_hear(self):
        prompts, nat, hr = self._voice(None, "via hear")
        self.assertTrue(hr.called)
        self.assertIn("via hear", prompts[0])

    def test_transcriber_ready_tracks_source(self):
        m = self.m
        with tempfile.TemporaryDirectory() as td:
            src, binp = Path(td) / "t.swift", Path(td) / "t"
            src.write_text("x")
            with patch.object(m, "TRANSCRIBE_SOURCE", src), patch.object(m, "TRANSCRIBE_BIN", binp):
                self.assertFalse(m.transcriber_ready())
                binp.write_text("bin")
                self.assertTrue(m.transcriber_ready())
                import os
                os.utime(src, (time.time() + 60, time.time() + 60))
                self.assertFalse(m.transcriber_ready())


if __name__ == "__main__":
    unittest.main()
