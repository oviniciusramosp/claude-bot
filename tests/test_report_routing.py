"""Agents report to the owner's private chat by default, and ChatGPT is the
last fallback (v3.90).

* AGENT_REPORT_TO=private (default): routines, pipeline notices and scripts
  (AGENT_CHAT_ID / telegram_notify.py) go to the agent's topic in the owner's
  private chat (frontmatter private_chat_id + private_thread_id, created by
  /agent topicos) — where live drafts, widgets and effects work. No private
  topic, or AGENT_REPORT_TO=group → the group topic, as before.
* "gpt" is the ChatGPT account's default model: Codex gets no --model, so the
  slug never goes stale (2026-11-16: gpt-5 and gpt-5.5 were both refused and
  the account default was gpt-6.1-sol).
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._botload import load_bot_module
from tests.test_agent_routing import FORUM, _write_agent
from tests.test_bot_integration import _BotFixture

OWNER = "123456789"
REPO = Path(__file__).resolve().parent.parent


class _Fixture:
    def __init__(self):
        self._td = tempfile.TemporaryDirectory()
        self.fx = _BotFixture(Path(self._td.name))
        self.bot, self.m, self.vault = self.fx.bot, self.fx.bot_module, self.fx.vault
        _write_agent(self.vault, "main", default=True)
        _write_agent(self.vault, "chef", chat_id=FORUM, thread_id=11329)
        _write_agent(self.vault, "solo", chat_id=FORUM, thread_id=500)
        self.bot.primary_chat_ids.update({OWNER, FORUM})
        self.m.set_agent_frontmatter_fields("chef", {"private_chat_id": OWNER, "private_thread_id": 77})
        self.m.set_agent_frontmatter_fields("main", {"private_chat_id": OWNER, "private_thread_id": 70})
        self.bot._refresh_agent_chat_map()
        self.saved = self.m.AGENT_REPORT_TO

    def task(self, agent):
        return self.m.RoutineTask(name="r", prompt="p", model="haiku", time_slot="08:00", agent=agent)

    def dest(self, agent):
        ctx = self.bot._find_context_for_routine(self.task(agent))
        return ctx.chat_id, ctx.thread_id

    def cleanup(self):
        self.m.AGENT_REPORT_TO = self.saved
        self.fx.cleanup()
        self._td.cleanup()


class RoutineDestination(unittest.TestCase):
    def setUp(self):
        self.f = _Fixture()
        self.addCleanup(self.f.cleanup)

    def test_private_topic_is_the_default(self):
        self.assertEqual(self.f.m.AGENT_REPORT_TO, "private")
        self.assertEqual(self.f.dest("chef"), (OWNER, 77))
        self.assertEqual(self.f.dest("main"), (OWNER, 70))

    def test_agent_without_private_topic_keeps_its_group_topic(self):
        self.assertEqual(self.f.dest("solo"), (FORUM, 500))

    def test_default_agent_without_any_topic_goes_to_owner_private_chat(self):
        hub = self.f.vault / "main" / "agent-main.md"
        hub.write_text(hub.read_text(encoding="utf-8")
                       .replace("private_chat_id", "x_private_chat_id"), encoding="utf-8")
        self.assertEqual(self.f.dest("main"), (OWNER, None))

    def test_group_mode_restores_the_old_behaviour(self):
        self.f.m.AGENT_REPORT_TO = "group"
        self.assertEqual(self.f.dest("chef"), (FORUM, 11329))
        self.assertEqual(self.f.dest("main"), (FORUM, None))  # General topic

    def test_route_helper_and_bad_thread(self):
        m = self.f.m
        self.assertEqual(m.agent_report_route({"chat_id": FORUM, "thread_id": 3,
                                               "private_chat_id": OWNER}), (OWNER, None))
        with self.assertLogs(m.logger, level="ERROR"):
            self.assertEqual(m.agent_report_route({"private_chat_id": OWNER,
                                                   "private_thread_id": "x"}), (OWNER, None))
        self.assertEqual(m.agent_report_route(None), (None, None))


class TelegramNotifyScript(unittest.TestCase):
    def _load(self):
        spec = importlib.util.spec_from_file_location("tg_notify", REPO / "scripts" / "telegram_notify.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_same_rule_as_the_bot(self):
        mod = self._load()
        with tempfile.TemporaryDirectory() as td:
            mod.VAULT_DIR = Path(td)
            (Path(td) / "chef").mkdir()
            (Path(td) / "chef" / "agent-chef.md").write_text(
                f"---\nchat_id: {FORUM}\nthread_id: 11329\nprivate_chat_id: {OWNER}\n"
                "private_thread_id: 77\n---\n", encoding="utf-8")
            with patch.dict(os.environ, {"AGENT_REPORT_TO": "private"}):
                self.assertEqual(mod.resolve_agent_routing("chef"), (OWNER, 77))
            with patch.dict(os.environ, {"AGENT_REPORT_TO": "group"}):
                self.assertEqual(mod.resolve_agent_routing("chef"), (FORUM, 11329))


class ChatGptFallback(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def test_gpt_is_last_in_the_default_chain(self):
        self.assertEqual(self.m.DEFAULT_FALLBACK_CHAIN[-1], "gpt")
        self.assertEqual(self.m.model_provider("gpt"), "openai")

    def test_display_name_is_the_account_default(self):
        with patch.object(self.m, "codex_default_model", return_value="gpt-6.1-sol"):
            self.assertEqual(self.m.model_display_name("gpt"), "GPT-6.1-sol")
        with patch.object(self.m, "codex_default_model", return_value=None):
            self.assertEqual(self.m.model_display_name("gpt"), "GPT")

    def _codex_cmd(self, model):
        with tempfile.TemporaryDirectory() as home:
            m = load_bot_module(tmp_home=Path(home))
            (Path(home) / ".codex").mkdir()
            (Path(home) / ".codex" / "auth.json").write_text("{}")
            fake = Path(home) / "codex"
            fake.write_text("#!/bin/sh\n")
            m.CODEX_PATH, m.CODEX_ENABLED = str(fake), True
            proc = MagicMock(stdout=iter([]), returncode=0, pid=1)
            proc.stderr.read.return_value = ""
            proc.wait.return_value = 0
            with patch.object(m.subprocess, "Popen", return_value=proc) as popen:
                m.CodexRunner().run(prompt="oi", model=model, workspace=home, system_prompt=None)
            self.assertTrue(popen.called, "codex was not spawned")
            return popen.call_args.args[0]

    def test_account_default_keys_send_no_model_flag(self):
        for key in ("gpt", "gpt-5"):
            self.assertNotIn("--model", self._codex_cmd(key), key)

    def test_explicit_model_is_passed(self):
        cmd = self._codex_cmd("gpt-6.1-sol")
        self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-6.1-sol")

    def test_anthropic_rate_limit_falls_through_to_gpt(self):
        with patch.object(self.m, "CODEX_ENABLED", True), \
                patch.object(self.m, "MODEL_FALLBACK_CHAIN", ["opus", "sonnet-5", "haiku", "gpt"]):
            self.assertEqual(self.m.get_fallback_model("opus", self.m.ErrorKind.RATE_LIMIT), "gpt")
            self.assertEqual(self.m.get_fallback_model("haiku", self.m.ErrorKind.UNKNOWN
                                                       if hasattr(self.m.ErrorKind, "UNKNOWN")
                                                       else self.m.ErrorKind.RATE_LIMIT), "gpt")


if __name__ == "__main__":
    unittest.main()
