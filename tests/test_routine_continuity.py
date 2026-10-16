"""v3.82 — routine `script:`, run history + `context_from`, `failure_deliver`,
and native CLI auto-compaction.

Script routines really execute /bin/bash (cheap, deterministic commands);
Telegram is a fake tg_request; no Claude CLI is spawned.
"""
import inspect
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests._botload import load_bot_module


class _BotFixture:
    """Minimal ClaudeTelegramBot with all I/O mocked (see test_context_isolation)."""

    def __init__(self, tmp_root: Path):
        self.home = tmp_root / "home"
        self.vault = tmp_root / "vault"
        self.home.mkdir()
        self.m = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        self.tg_calls = []
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
                return {"ok": True, "result": {"message_id": len(self.tg_calls)}}

        self.bot.tg_request = fake_tg_request

    def sent_texts(self):
        return [d.get("text", "") for m, d in self.tg_calls if m == "sendMessage"]

    def cleanup(self):
        for p in self._patches:
            p.stop()


class FrontmatterParsing(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def task(self, **fm):
        return self.m.routine_task_from_frontmatter("daily", fm, "body", "07:00", "main")

    def test_defaults_unchanged(self):
        t = self.task(model="opus", effort="high", voice=True, context="minimal")
        self.assertIsNone(t.script)
        self.assertEqual(t.context_from, [])
        self.assertEqual(t.failure_deliver, "notify")
        self.assertEqual((t.model, t.effort, t.voice, t.minimal_context),
                         ("opus", "high", True, True))

    def test_script_and_timeout_clamp(self):
        t = self.task(script="  echo hi  ", timeout=99999)
        self.assertEqual(t.script, "echo hi")
        self.assertEqual(t.script_timeout, self.m.ROUTINE_SCRIPT_MAX_TIMEOUT)
        self.assertEqual(self.task(script="x", timeout="junk").script_timeout, 300)

    def test_context_from_forms(self):
        self.assertEqual(self.task(context_from="self").context_from, ["self"])
        self.assertEqual(self.task(context_from="Self, other").context_from, ["self", "other"])
        self.assertEqual(self.task(context_from=["self", "x"], context_runs=3).context_runs, 3)
        self.assertEqual(self.task(context_from="self", context_runs=0).context_runs, 1)

    def test_invalid_failure_deliver_falls_back_to_notify(self):
        self.assertEqual(self.task(failure_deliver="SILENT").failure_deliver, "silent")
        self.assertEqual(self.task(failure_deliver="loud").failure_deliver, "notify")


class RunHistory(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.m = load_bot_module(tmp_home=Path(self._td.name))

    def tearDown(self):
        self._td.cleanup()

    def test_record_and_trim(self):
        for i in range(self.m.ROUTINE_HISTORY_KEEP + 5):
            self.m.record_routine_run("main", "daily", "07:00", "completed", output=f"run {i}")
        runs = self.m.load_routine_history("main", "daily", 100)
        self.assertEqual(len(runs), self.m.ROUTINE_HISTORY_KEEP)
        self.assertEqual(runs[-1]["output"], f"run {self.m.ROUTINE_HISTORY_KEEP + 4}")

    def test_context_block_renders_statuses(self):
        self.m.record_routine_run("main", "daily", "07:00", "completed", output="BTC 100k")
        self.m.record_routine_run("main", "daily", "07:00", "failed", error="API down")
        self.m.record_routine_run("main", "daily", "07:00", "completed", output="NO_REPLY")
        block = self.m.build_routine_context_block("main", "daily", ["self"], 3)
        self.assertIn("BTC 100k", block)
        self.assertIn("(falhou: API down)", block)
        self.assertIn("(sem saída)", block)
        self.assertLess(block.index("BTC 100k"), block.index("API down"))  # oldest first

    def test_context_block_truncates_and_is_empty_without_history(self):
        self.assertEqual(self.m.build_routine_context_block("main", "daily", ["self"], 1), "")
        self.m.record_routine_run("main", "daily", "07:00", "completed", output="x" * 10000)
        block = self.m.build_routine_context_block("main", "daily", ["self"], 1)
        self.assertIn("…(truncado)", block)
        self.assertLess(len(block), self.m.ROUTINE_HISTORY_INJECT_CHARS + 300)

    def test_context_is_agent_isolated(self):
        self.m.record_routine_run("crypto-bro", "daily", "07:00", "completed", output="secret")
        self.assertEqual(self.m.build_routine_context_block("main", "daily", ["self"], 1), "")


class ScriptRoutines(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fx = _BotFixture(Path(self._td.name))
        self.bot, self.m = self.fx.bot, self.fx.m

    def tearDown(self):
        self.fx.cleanup()
        self._td.cleanup()

    def run_script(self, script, **fm):
        task = self.m.routine_task_from_frontmatter(
            "probe", dict(script=script, **fm), "", "07:00", "main")
        with patch.object(self.bot, "_run_claude_prompt") as llm:
            self.bot._execute_routine_task(task)
            llm.assert_not_called()  # the whole point: no model turn
        return self.m.load_routine_history("main", "probe", 1)[-1]

    def test_empty_stdout_is_silent(self):
        run = self.run_script("true")
        self.assertEqual(run["status"], "completed")
        self.assertEqual(self.fx.sent_texts(), [])

    def test_stdout_delivered_verbatim(self):
        self.run_script("echo '*not bold* <b>' ; echo \"agent=$AGENT_ID\"")
        texts = self.fx.sent_texts()
        self.assertEqual(texts, ["*not bold* <b>\nagent=main"])
        sends = [d for m, d in self.fx.tg_calls if m == "sendMessage"]
        self.assertNotIn("parse_mode", sends[0])

    def test_no_reply_sentinel_is_silent(self):
        self.run_script("echo NO_REPLY")
        self.assertEqual(self.fx.sent_texts(), [])

    def test_runs_from_repo_root(self):
        self.run_script("test -d scripts && echo here")
        self.assertEqual(self.fx.sent_texts(), ["here"])

    def test_nonzero_exit_fails_with_stderr(self):
        run = self.run_script("echo boom >&2; exit 3")
        self.assertEqual(run["status"], "failed")
        self.assertIn("exit 3", run["error"])
        self.assertIn("boom", run["error"])
        self.assertTrue(any("FAILED" in t and "boom" in t for t in self.fx.sent_texts()))

    def test_timeout_fails(self):
        run = self.run_script("sleep 5", timeout=1)
        self.assertEqual(run["status"], "failed")
        self.assertIn("timeout", run["error"])

    def test_silent_failure_sends_nothing(self):
        run = self.run_script("exit 1", failure_deliver="silent")
        self.assertEqual(run["status"], "failed")
        self.assertEqual(self.fx.sent_texts(), [])

    def test_blocked_for_secondary_chat_agents(self):
        self.bot.secondary_chats = {"-100": {"default": "main", "topics": {}}}
        run = self.run_script("echo should-not-run")
        self.assertEqual(run["status"], "failed")
        self.assertIn("secundários", run["error"])
        self.assertFalse(any("should-not-run" in t for t in self.fx.sent_texts()))


class ModelRoutineContinuity(unittest.TestCase):
    """context_from reaches the prompt; outputs and failures land in history."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fx = _BotFixture(Path(self._td.name))
        self.bot, self.m = self.fx.bot, self.fx.m
        self.runner = SimpleNamespace(error_text="", exit_code=0,
                                      result_text="today's briefing", accumulated_text="")
        self._p = [
            patch.object(type(self.bot), "runner", property(lambda s: self.runner)),
            patch.object(self.m, "vault_checkpoint_create", lambda *a, **k: None),
        ]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()
        self.fx.cleanup()
        self._td.cleanup()

    def run_task(self, **fm):
        task = self.m.routine_task_from_frontmatter(
            "briefing", dict(model="sonnet", **fm), "Write the briefing.", "07:00", "main")
        prompts = []
        with patch.object(self.bot, "_run_claude_prompt",
                          side_effect=lambda p, **k: prompts.append(p)):
            self.bot._execute_routine_task(task)
        return prompts[0]

    def test_previous_output_injected(self):
        self.m.record_routine_run("main", "briefing", "07:00", "completed", output="yesterday: BTC 99k")
        prompt = self.run_task(context_from="self")
        self.assertIn("yesterday: BTC 99k", prompt)
        self.assertLess(prompt.index("yesterday"), prompt.index("Write the briefing."))

    def test_no_injection_without_context_from(self):
        self.m.record_routine_run("main", "briefing", "07:00", "completed", output="yesterday")
        self.assertNotIn("yesterday", self.run_task())

    def test_success_recorded(self):
        self.run_task()
        last = self.m.load_routine_history("main", "briefing", 1)[-1]
        self.assertEqual((last["status"], last["output"]), ("completed", "today's briefing"))

    def test_silent_failure_recorded_without_failed_message(self):
        self.runner.error_text = "❌ API overloaded"
        self.run_task(failure_deliver="silent")
        last = self.m.load_routine_history("main", "briefing", 1)[-1]
        self.assertEqual(last["status"], "failed")
        texts = self.fx.sent_texts() + [d.get("text", "") for m, d in self.fx.tg_calls
                                        if m == "editMessageText"]
        self.assertFalse(any("FAILED" in t for t in texts))


class NativeCompaction(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = load_bot_module()

    def test_compact_boundary_event_captured(self):
        r = self.m.ClaudeRunner()
        r.running = True
        r._handle_event({"type": "system", "subtype": "compact_boundary",
                         "compact_metadata": {"trigger": "auto", "pre_tokens": 156697,
                                              "post_tokens": 3122}})
        self.assertEqual(r.native_compact["pre_tokens"], 156697)

    def test_window_default(self):
        self.assertEqual(self.m.AUTO_COMPACT_WINDOW, 400000)

    def _spawn_env(self, model):
        proc = MagicMock()
        proc.stdout = iter([])
        proc.stderr = MagicMock()
        proc.stderr.read.return_value = ""
        proc.stdin = MagicMock()
        proc.wait.return_value = 0
        proc.returncode = 0
        proc.pid = 4321
        with tempfile.TemporaryDirectory() as ws, \
                patch.object(self.m.subprocess, "Popen", return_value=proc) as popen:
            self.m.ClaudeRunner().run(prompt="hi", model=model, workspace=ws,
                                      system_prompt=None)
        return popen.call_args.kwargs["env"]

    def test_window_reaches_claude_cli(self):
        os.environ.pop("CLAUDE_CODE_AUTO_COMPACT_WINDOW", None)
        self.assertEqual(self._spawn_env("sonnet")["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "400000")

    def test_explicit_env_wins(self):
        os.environ["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "150000"
        try:
            self.assertEqual(self._spawn_env("sonnet")["CLAUDE_CODE_AUTO_COMPACT_WINDOW"], "150000")
        finally:
            os.environ.pop("CLAUDE_CODE_AUTO_COMPACT_WINDOW", None)

    def test_turn_count_no_longer_compacts(self):
        src = inspect.getsource(self.m.ClaudeTelegramBot)
        self.assertNotIn("AUTO_COMPACT_INTERVAL", src)
        self.assertIn("_auto_compact(session, compact=False)", src)


if __name__ == "__main__":
    unittest.main()
