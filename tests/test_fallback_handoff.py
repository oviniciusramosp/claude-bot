"""Fallback order and conversation handoff (v3.91).

* Order: Fable → Opus; any other Claude failure (Opus, Sonnet, Haiku) → GPT.
* A turn that crosses Claude ↔ GPT gets the conversation so far: read from
  the Claude session file (persistent), written in full to
  ~/.claude-bot/handoffs/ (0600) and summarised at the top of the prompt.
"""
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._botload import load_bot_module

CHAIN = ["fable", "opus", "gpt"]


class FallbackOrder(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def nxt(self, model, kind="UNKNOWN", codex=True):
        with patch.object(self.m, "CODEX_ENABLED", codex), \
                patch.object(self.m, "MODEL_FALLBACK_CHAIN", list(CHAIN)):
            return self.m.get_fallback_model(model, getattr(self.m.ErrorKind, kind))

    def test_default_chain(self):
        self.assertEqual(self.m.DEFAULT_FALLBACK_CHAIN, CHAIN)

    def test_fable_goes_to_opus(self):
        self.assertEqual(self.nxt("fable"), "opus")
        self.assertEqual(self.nxt("fable", "OVERLOADED"), "opus")

    def test_every_other_claude_goes_to_gpt(self):
        for model in ("opus", "sonnet", "sonnet-5", "haiku"):
            self.assertEqual(self.nxt(model), "gpt", model)

    def test_account_wide_errors_skip_opus(self):
        for kind in ("RATE_LIMIT", "AUTH", "CREDIT"):
            self.assertEqual(self.nxt("fable", kind), "gpt", kind)

    def test_gpt_is_the_end(self):
        self.assertIsNone(self.nxt("gpt"))

    def test_no_codex_means_no_gpt(self):
        self.assertIsNone(self.nxt("haiku", codex=False))
        self.assertEqual(self.nxt("fable", codex=False), "opus")


def _write_transcript(projects, workspace, sid, records):
    d = projects / workspace.replace("/", "-")
    d.mkdir(parents=True, exist_ok=True)
    with open(d / f"{sid}.jsonl", "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name)
        self.m = load_bot_module(tmp_home=self.home)
        self.projects = self.home / "projects"
        self.m.CLAUDE_PROJECTS_DIR = self.projects
        self.m.DATA_DIR = self.home / "data"
        self.ws = "/Users/x/vault/main"
        _write_transcript(self.projects, self.ws, "sid1", [
            {"type": "queue-operation"},
            {"type": "user", "message": {"role": "user", "content": "<hint>skills</hint>\nme chame de Vinizeira"}},
            {"type": "assistant", "message": {"content": [{"type": "thinking", "thinking": "hmm"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Combinado,"}]}},
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "ok"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "Vinizeira."}]}},
            {"type": "user", "isMeta": True, "message": {"content": "caveat"}},
            {"type": "user", "isSidechain": True, "message": {"content": "subagent"}},
            {"type": "user", "message": {"content": "qual a capital da França?"}},
            "not a dict",
        ])

    def tearDown(self):
        self._td.cleanup()

    def bot(self):
        b = self.m.ClaudeTelegramBot.__new__(self.m.ClaudeTelegramBot)
        b._transcripts, b._handoff_pending = {}, {}
        b._transcripts_lock = threading.Lock()
        return b


class ReadTranscript(_Base):
    def test_keeps_only_what_was_said(self):
        turns = self.m.read_claude_transcript("sid1", self.ws)
        self.assertEqual([t["role"] for t in turns], ["user", "assistant", "user"])
        self.assertEqual(turns[0]["text"], "me chame de Vinizeira")
        self.assertEqual(turns[1]["text"], "Combinado,\n\nVinizeira.")

    def test_missing_session_is_empty(self):
        self.assertEqual(self.m.read_claude_transcript(None, self.ws), [])
        self.assertEqual(self.m.read_claude_transcript("nope", self.ws), [])


class Handoff(_Base):
    def session(self):
        return self.m.Session(name="s", session_id="sid1", model="opus", workspace=self.ws)

    def test_fallback_to_gpt_hands_over_the_session_file(self):
        b = self.bot()
        self.assertTrue(b._arm_handoff(self.session(), "opus", "gpt"))
        p = b._handoff_pending["s"]
        block = b._build_handoff_block("s", p["from_model"], p["to_model"],
                                       claude_session_id=p["claude_session_id"],
                                       workspace=p["workspace"])
        self.assertIn("Vinizeira", block)
        self.assertIn("capital da França", block)
        path = Path(block.split("em `")[1].split("`")[0])
        self.assertTrue(path.is_file())
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        self.assertIn("arquivo da sessão do Claude", path.read_text(encoding="utf-8"))

    def test_nothing_to_hand_over(self):
        b = self.bot()
        s = self.m.Session(name="s", session_id=None, model="opus", workspace=self.ws)
        self.assertFalse(b._arm_handoff(s, "opus", "gpt"))
        self.assertEqual(b._handoff_pending, {})

    def test_back_from_gpt_uses_the_memory_buffer(self):
        b = self.bot()
        b._append_transcript("s", "user", "pergunta no gpt", "gpt")
        b._append_transcript("s", "assistant", "resposta do gpt", "gpt")
        self.assertTrue(b._arm_handoff(self.session(), "gpt", "opus"))
        self.assertEqual(b._handoff_pending["s"]["claude_session_id"], "")
        block = b._build_handoff_block("s", "gpt", "opus")
        self.assertIn("resposta do gpt", block)

    def test_old_handoff_files_are_pruned(self):
        b = self.bot()
        d = self.m.DATA_DIR / "handoffs"
        d.mkdir(parents=True)
        old = d / "old.md"
        old.write_text("x")
        os.utime(old, (1, 1))
        b._build_handoff_block("s", "opus", "gpt", claude_session_id="sid1", workspace=self.ws)
        self.assertFalse(old.exists())



class UsageLimits(unittest.TestCase):
    """v3.92: two kinds of limit. A model's own cap (Fable) → Opus; the
    account's 5-hour or weekly cap → GPT."""

    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def test_scope(self):
        sc = self.m.usage_limit_scope
        self.assertEqual(sc("You've reached your Fable limit."), "model")
        self.assertEqual(sc("You've hit your Opus limit · resets 3pm"), "model")
        self.assertEqual(sc("You've hit your session limit · resets 4:20am (America/Sao_Paulo)"), "account")
        self.assertEqual(sc("You've hit your weekly limit · resets Nov 20, 4pm"), "account")
        self.assertIsNone(sc("API Error: 500 internal"))

    def test_session_limit_is_a_rate_limit(self):
        # Before v3.92 this was UNKNOWN, so no limit handling ran.
        self.assertEqual(self.m.classify_error("You've hit your session limit · resets 8pm"),
                         self.m.ErrorKind.RATE_LIMIT)

    def test_friendly_message(self):
        t = self.m._translate_error("You've hit your weekly limit · resets Nov 20, 4pm (America/Sao_Paulo)")
        self.assertIn("limite semanal da conta", t)
        self.assertIn("Nov 20, 4pm", t)
        self.assertIn("limite do Fable", self.m._translate_error("You've reached your Fable limit."))

    def test_reset_time_is_parsed(self):
        ttl = self.m.parse_rate_limit_reset("You've hit your session limit · resets 4:20am (America/Sao_Paulo)")
        self.assertIsNotNone(ttl)
        self.assertGreater(ttl, 0)
        self.assertLessEqual(ttl, 86400)

    def nxt(self, model, raw):
        kind = self.m.classify_error(raw)
        with patch.object(self.m, "CODEX_ENABLED", True), \
                patch.object(self.m, "MODEL_FALLBACK_CHAIN", list(CHAIN)):
            return self.m.get_fallback_model(model, kind, limit_scope=self.m.usage_limit_scope(raw))

    def test_fable_limit_offers_opus(self):
        self.assertEqual(self.nxt("fable", "You've reached your Fable limit."), "opus")

    def test_account_limit_offers_gpt(self):
        for raw in ("You've hit your session limit · resets 8pm",
                    "You've hit your weekly limit · resets Nov 20, 4pm"):
            self.assertEqual(self.nxt("fable", raw), "gpt", raw)
            self.assertEqual(self.nxt("opus", raw), "gpt", raw)


class AskBeforeSwitching(_Base):
    """v3.92: the model never changes without the user's ✅."""

    def setUp(self):
        super().setUp()
        b = self.bot()
        b._model_offers, b._model_offers_lock = {}, threading.Lock()
        b.sent, b.edits, b.answers, b.ran = [], [], [], []
        b.send_message = lambda text, **kw: (b.sent.append((text, kw)), 1)[1]
        b.edit_message = lambda mid, text, **kw: b.edits.append(text) or True
        b.answer_callback = lambda cid, text=None, **kw: b.answers.append(text)
        b._run_claude_prompt = lambda prompt, *a, **kw: b.ran.append(prompt) or True
        b._ctx_local = threading.local()
        b._ctx = type("Ctx", (), {"chat_id": "42", "thread_id": None})()
        self.s = self.m.Session(name="s", session_id="sid1", model="opus", workspace=self.ws)
        b.sessions = type("SM", (), {"sessions": {"s": self.s}, "save": lambda self: None})()
        self.b = b

    def offer(self, raw="You've hit your session limit · resets 8pm"):
        self.b._offer_model_switch(self.s, "opus", "gpt", "rate_limit",
                                   self.m.usage_limit_scope(raw), raw, "qual a capital?")
        text, kw = self.b.sent[-1]
        yes, no = kw["reply_markup"]["inline_keyboard"][0]
        return text, yes["callback_data"], no["callback_data"]

    def tap(self, data):
        self.b._handle_callback({"id": "c", "data": data, "message": {"message_id": 9, "text": "q"}})

    def test_offer_changes_nothing(self):
        text, _, _ = self.offer()
        self.assertIn("Trocar para", text)
        self.assertIn("limite de 5 horas da conta", text)
        self.assertEqual(self.s.model, "opus")
        self.assertEqual(self.b._handoff_pending, {})

    def test_yes_switches_hands_over_and_answers(self):
        _, yes, _ = self.offer()
        self.tap(yes)
        self.assertEqual(self.s.model, "gpt")
        self.assertEqual(self.s.preferred_model, "opus")
        self.assertGreater(self.s.rate_limit_until, 0)
        self.assertIn("s", self.b._handoff_pending)
        self.assertEqual(self.b.ran, ["qual a capital?"])

    def test_no_keeps_the_model(self):
        _, _, no = self.offer()
        self.tap(no)
        self.assertEqual(self.s.model, "opus")
        self.assertEqual(self.b.ran, [])

    def test_button_works_once(self):
        _, yes, _ = self.offer()
        self.tap(yes)
        self.tap(yes)
        self.assertEqual(self.b.ran, ["qual a capital?"])
        self.assertIn("expirou", self.b.answers[-1])

    def test_going_back_is_also_asked(self):
        self.s.model, self.s.preferred_model = "gpt", "opus"
        self.b._offer_model_return(self.s)
        self.assertEqual(self.s.model, "gpt")
        yes = self.b.sent[-1][1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        self.tap(yes)
        self.assertEqual(self.s.model, "opus")
        self.assertIsNone(self.s.preferred_model)
        self.assertEqual(self.b.ran, [])  # going back runs nothing by itself



class RoutineAutoFallback(unittest.TestCase):
    """v3.93: `fallback: auto` lets a routine switch model without asking."""

    def test_field_parsing(self):
        m = load_bot_module()
        f = m.routine_task_from_frontmatter
        self.assertFalse(f("r", {}, "b", "08:00", "main").auto_fallback)
        self.assertTrue(f("r", {"fallback": "auto"}, "b", "08:00", "main").auto_fallback)
        self.assertTrue(f("r", {"fallback": True}, "b", "08:00", "main").auto_fallback)
        with self.assertLogs(m.logger, level="WARNING"):
            self.assertFalse(f("r", {"fallback": "talvez"}, "b", "08:00", "main").auto_fallback)

    def _run(self, auto, routine=True):
        from tests.test_bot_integration import _BotFixture
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        fx = _BotFixture(Path(td.name))
        self.addCleanup(fx.cleanup)
        bot, m = fx.bot, fx.bot_module
        calls = []

        def fake_run(runner, prompt, model, **kw):
            calls.append(model)
            if model == "gpt":
                runner.exit_code, runner.result_text = 0, "ok"
            else:
                runner.exit_code = 1
                runner.result_text = "You've hit your session limit · resets 8pm (America/Sao_Paulo)"

        sent = []
        with patch.object(m, "CODEX_ENABLED", True), \
                patch.object(m, "MODEL_FALLBACK_CHAIN", list(CHAIN)), \
                patch.object(m.ClaudeRunner, "run", fake_run), \
                patch.object(m.CodexRunner, "run", fake_run), \
                patch.object(bot, "_stream_updates", lambda t, r, **k: t.join()), \
                patch.object(bot, "_watchdog", lambda *a, **k: None), \
                patch.object(bot, "_finalize_response", lambda *a, **k: None), \
                patch.object(bot, "_offer_model_switch", lambda *a, **k: sent.append("offer")), \
                patch.object(bot, "send_message", lambda text, **k: sent.append(text) or 1):
            bot._get_session().model = "opus"
            bot._run_claude_prompt_owned("tarefa", routine_mode=routine,
                                         system_prompt=None, auto_fallback=auto)
        return calls, sent, bot._get_session()

    def test_auto_routine_switches_without_asking(self):
        calls, sent, session = self._run(auto=True)
        self.assertEqual(calls, ["opus", "gpt"])
        self.assertNotIn("offer", sent)
        self.assertTrue(any("troca automática" in str(t) for t in sent))
        self.assertEqual(session.model, "opus")  # only that run changed

    def test_default_routine_does_not_switch(self):
        calls, sent, _ = self._run(auto=False)
        self.assertEqual(calls, ["opus"])
        self.assertNotIn("offer", sent)

    def test_chat_still_asks(self):
        calls, sent, session = self._run(auto=True, routine=False)
        self.assertEqual(calls, ["opus"])
        self.assertIn("offer", sent)
        self.assertEqual(session.model, "opus")


if __name__ == "__main__":
    unittest.main()
