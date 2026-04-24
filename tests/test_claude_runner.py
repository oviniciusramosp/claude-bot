"""Tests for ClaudeRunner stream-json event handling.

We don't actually spawn `claude` — instead we drive `_handle_event` directly
with the JSON shapes the CLI emits. This covers the parser without subprocess
flakiness.
"""
import os
import unittest
from unittest.mock import MagicMock, patch

from tests._botload import load_bot_module


class HandleEvent(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def setUp(self):
        self.runner = self.bot.ClaudeRunner()
        # The _handle_event method assumes some baseline state
        self.runner.running = True

    def test_system_event_captures_session_id(self):
        self.runner._handle_event({"type": "system", "session_id": "abc-123"})
        self.assertEqual(self.runner.captured_session_id, "abc-123")

    def test_assistant_text_block_accumulates(self):
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello "}]},
        })
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "world"}]},
        })
        self.assertEqual(self.runner.accumulated_text, "Hello world")
        self.assertEqual(self.runner.activity_type, "text")

    def test_assistant_tool_use_logs_and_changes_activity(self):
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "name": "Bash",
                "input": {"command": "ls -la"}
            }]},
        })
        self.assertEqual(len(self.runner.tool_log), 1)
        self.assertIn("Bash", self.runner.tool_log[0])
        self.assertIn("ls -la", self.runner.tool_log[0])
        # Bash maps to "running_script" per _TOOL_ACTIVITY_MAP
        self.assertEqual(self.runner.activity_type, "running_script")

    def test_assistant_thinking_block(self):
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": "..."}]},
        })
        self.assertEqual(self.runner.activity_type, "thinking")

    def test_tool_log_caps_at_200(self):
        for i in range(250):
            self.runner._handle_event({
                "type": "assistant",
                "message": {"content": [{
                    "type": "tool_use", "name": "Read",
                    "input": {"file_path": f"/tmp/{i}"}
                }]},
            })
        # Cap is 200, after that it trims to last 100
        self.assertLessEqual(len(self.runner.tool_log), 200)

    def test_result_event_records_cost_and_text(self):
        self.runner._handle_event({
            "type": "result",
            "result": "done",
            "cost_usd": 0.0023,
            "total_cost_usd": 0.0050,
            "session_id": "sess-99",
        })
        self.assertEqual(self.runner.result_text, "done")
        self.assertAlmostEqual(self.runner.cost_usd, 0.0023)
        self.assertAlmostEqual(self.runner.total_cost_usd, 0.0050)
        self.assertEqual(self.runner.captured_session_id, "sess-99")

    def test_error_event_with_known_type(self):
        self.runner._handle_event({
            "type": "error",
            "error": {"type": "overloaded_error", "message": "API overloaded"},
        })
        self.assertIn("Erro da API", self.runner.error_text)
        self.assertIn("sobrecarregada", self.runner.error_text)

    def test_error_event_with_unknown_type_falls_back_to_message(self):
        self.runner._handle_event({
            "type": "error",
            "error": {"type": "weird_error", "message": "the thing exploded"},
        })
        self.assertIn("weird_error", self.runner.error_text)

    def test_unknown_event_type_does_not_crash(self):
        # The bot must tolerate forward-compat event types from new CLI versions
        self.runner._handle_event({"type": "future_event_type", "data": "?"})
        # No exception = pass

    def test_tool_use_with_non_string_input_no_crash(self):
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "name": "TodoWrite",
                "input": {"todos": [1, 2, 3]}
            }]},
        })
        self.assertEqual(len(self.runner.tool_log), 1)


class AccumulatedThinking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def setUp(self):
        self.runner = self.bot.ClaudeRunner()
        self.runner.running = True

    def test_thinking_block_accumulates_content(self):
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": "Let me analyze this"}]},
        })
        self.assertEqual(self.runner.accumulated_thinking, "Let me analyze this")
        self.assertEqual(self.runner.activity_type, "thinking")

    def test_multiple_thinking_blocks_concatenated(self):
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": "First thought"}]},
        })
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": "Second thought"}]},
        })
        self.assertEqual(self.runner.accumulated_thinking, "First thought\nSecond thought")

    def test_thinking_snapshot_truncation(self):
        long_text = "x" * 5000
        self.runner.accumulated_thinking = long_text
        snapshot = self.runner.get_thinking_snapshot(max_chars=1500)
        self.assertTrue(snapshot.startswith("...\n"))
        # Content after "...\n" should be last 1500 chars
        self.assertEqual(snapshot[4:], long_text[-1500:])

    def test_thinking_snapshot_short_text_not_truncated(self):
        self.runner.accumulated_thinking = "short"
        snapshot = self.runner.get_thinking_snapshot(max_chars=1500)
        self.assertEqual(snapshot, "short")

    def test_thinking_snapshot_empty(self):
        snapshot = self.runner.get_thinking_snapshot()
        self.assertEqual(snapshot, "")

    def test_thinking_reset_on_init(self):
        self.assertEqual(self.runner.accumulated_thinking, "")

    def test_empty_thinking_block_ignored(self):
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{"type": "thinking", "thinking": ""}]},
        })
        self.assertEqual(self.runner.accumulated_thinking, "")

    def test_thinking_block_without_thinking_field(self):
        self.runner._handle_event({
            "type": "assistant",
            "message": {"content": [{"type": "thinking"}]},
        })
        self.assertEqual(self.runner.accumulated_thinking, "")


class AgentIdInjection(unittest.TestCase):
    """Verify ClaudeRunner.run() injects agent routing env vars into the subprocess."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def _mock_popen(self, mock_popen):
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock(read=MagicMock(return_value=""))
        mock_proc.wait.return_value = 0
        mock_proc.poll.return_value = 0
        mock_proc.stdin = MagicMock()
        mock_popen.return_value = mock_proc

    def _get_env(self, mock_popen):
        call_kwargs = mock_popen.call_args
        return call_kwargs.kwargs.get("env") or call_kwargs[1].get("env")

    @patch("subprocess.Popen")
    def test_telegram_notify_always_injected(self, mock_popen):
        """TELEGRAM_NOTIFY must always be set, even without agent_id."""
        self._mock_popen(mock_popen)
        runner = self.bot.ClaudeRunner()
        runner.run(prompt="test", agent_id=None)
        env = self._get_env(mock_popen)
        self.assertIn("TELEGRAM_NOTIFY", env)
        self.assertTrue(env["TELEGRAM_NOTIFY"].endswith("telegram_notify.py"))

    @patch("subprocess.Popen")
    def test_agent_id_injected_into_env(self, mock_popen):
        """When agent_id is provided, AGENT_ID must be in the env dict."""
        self._mock_popen(mock_popen)
        runner = self.bot.ClaudeRunner()
        runner.run(prompt="test", agent_id="crypto-bro")
        env = self._get_env(mock_popen)
        self.assertIsNotNone(env, "Popen must be called with env=")
        self.assertEqual(env.get("AGENT_ID"), "crypto-bro")

    @patch("subprocess.Popen")
    def test_agent_id_not_injected_when_none(self, mock_popen):
        """When agent_id is None, AGENT_ID should not be added to env."""
        self._mock_popen(mock_popen)
        runner = self.bot.ClaudeRunner()
        os.environ.pop("AGENT_ID", None)
        runner.run(prompt="test", agent_id=None)
        env = self._get_env(mock_popen)
        self.assertNotIn("AGENT_ID", env)

    @patch("subprocess.Popen")
    def test_agent_routing_vars_injected_when_agent_has_chat_id(self, mock_popen):
        """AGENT_CHAT_ID and AGENT_THREAD_ID injected when agent frontmatter has them."""
        import tempfile
        from pathlib import Path

        self._mock_popen(mock_popen)

        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            (vault / "myagent").mkdir(parents=True)
            (vault / "myagent" / "agent-myagent.md").write_text(
                "---\nchat_id: -100999\nthread_id: 7\n---\n"
            )
            # Patch VAULT_DIR so load_agent finds the temp file
            orig = self.bot.VAULT_DIR
            self.bot.VAULT_DIR = vault
            try:
                runner = self.bot.ClaudeRunner()
                runner.run(prompt="test", agent_id="myagent")
            finally:
                self.bot.VAULT_DIR = orig

        env = self._get_env(mock_popen)
        self.assertEqual(env.get("AGENT_CHAT_ID"), "-100999")
        self.assertEqual(env.get("AGENT_THREAD_ID"), "7")

    @patch("subprocess.Popen")
    def test_agent_routing_vars_absent_when_no_frontmatter(self, mock_popen):
        """AGENT_CHAT_ID not injected when agent file is missing."""
        self._mock_popen(mock_popen)
        runner = self.bot.ClaudeRunner()
        # Use an agent that doesn't exist in vault
        runner.run(prompt="test", agent_id="nonexistent-agent-xyz")
        env = self._get_env(mock_popen)
        self.assertNotIn("AGENT_CHAT_ID", env)
        self.assertNotIn("AGENT_THREAD_ID", env)


class GetSnapshot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_snapshot_combines_text_and_tools(self):
        runner = self.bot.ClaudeRunner()
        runner.running = True
        runner._handle_event({
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "hello"}]},
        })
        runner._handle_event({
            "type": "assistant",
            "message": {"content": [{
                "type": "tool_use", "name": "Read",
                "input": {"file_path": "x.py"}
            }]},
        })
        snapshot = runner.get_snapshot()
        self.assertIsInstance(snapshot, str)
        self.assertGreater(len(snapshot), 0)


class ProviderRouting(unittest.TestCase):
    """Env injection for GLM vs Anthropic models.

    ClaudeRunner.run() must inject ANTHROPIC_BASE_URL + ANTHROPIC_AUTH_TOKEN
    into the subprocess env when the requested model is a GLM variant (routed
    through z.AI's Anthropic-compatible gateway), and must fail loud if the
    user requested GLM without configuring ZAI_API_KEY.
    """

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    # Env vars we touch across tests — snapshot + restore so host env
    # (which may already have ANTHROPIC_BASE_URL, API_TIMEOUT_MS, etc. set
    # by the Claude agent that ran this test) is preserved between cases.
    _MUTATED_ENV_VARS = (
        "ANTHROPIC_BASE_URL",
        "ANTHROPIC_AUTH_TOKEN",
        "ANTHROPIC_API_KEY",
        "API_TIMEOUT_MS",
    )

    def setUp(self):
        self._orig_zai_key = self.bot.ZAI_API_KEY
        self._env_snapshot = {k: os.environ.get(k) for k in self._MUTATED_ENV_VARS}
        # Clear them so tests start from a clean slate — this isolates the
        # bot's injection behavior from whatever the host happens to have set.
        for k in self._MUTATED_ENV_VARS:
            os.environ.pop(k, None)

    def tearDown(self):
        self.bot.ZAI_API_KEY = self._orig_zai_key
        for k, v in self._env_snapshot.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def _make_mock_popen_proc(self):
        """Return a MagicMock process with empty stdout/stderr so
        _read_stream() exits immediately without blocking."""
        proc = MagicMock()
        proc.stdout = iter([])           # empty iterator -> for-loop exits
        proc.stderr = MagicMock()
        proc.stderr.read.return_value = ""
        proc.stdin = MagicMock()
        proc.wait.return_value = 0
        proc.returncode = 0
        proc.pid = 12345
        return proc

    def test_anthropic_model_does_not_inject_zai_env(self):
        self.bot.ZAI_API_KEY = ""
        runner = self.bot.ClaudeRunner()
        with patch.object(self.bot.subprocess, "Popen") as mock_popen:
            mock_popen.return_value = self._make_mock_popen_proc()
            runner.run(prompt="hi", model="sonnet", system_prompt=None)
        mock_popen.assert_called_once()
        env = mock_popen.call_args.kwargs["env"]
        self.assertNotIn("ANTHROPIC_BASE_URL", env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)

    def test_glm_model_injects_zai_env(self):
        # GLM models now route through a local proxy (bypasses Claude CLI's client-side
        # model validation). ANTHROPIC_BASE_URL → local proxy; AUTH_TOKEN → "zai-proxy".
        self.bot.ZAI_API_KEY = "fake-key"
        runner = self.bot.ClaudeRunner()
        with patch.object(self.bot.subprocess, "Popen") as mock_popen:
            mock_popen.return_value = self._make_mock_popen_proc()
            runner.run(prompt="hi", model="glm-4.7", system_prompt=None)
        mock_popen.assert_called_once()
        env = mock_popen.call_args.kwargs["env"]
        base_url = env.get("ANTHROPIC_BASE_URL", "")
        self.assertTrue(
            base_url.startswith("http://127.0.0.1:"),
            f"Expected local proxy URL, got: {base_url}",
        )
        self.assertEqual(env.get("ANTHROPIC_AUTH_TOKEN"), "zai-proxy")
        self.assertEqual(env.get("API_TIMEOUT_MS"), "3000000")

    def test_glm_model_strips_anthropic_api_key(self):
        self.bot.ZAI_API_KEY = "fake-key"
        os.environ["ANTHROPIC_API_KEY"] = "leaked"
        runner = self.bot.ClaudeRunner()
        with patch.object(self.bot.subprocess, "Popen") as mock_popen:
            mock_popen.return_value = self._make_mock_popen_proc()
            runner.run(prompt="hi", model="glm-4.7", system_prompt=None)
        mock_popen.assert_called_once()
        env = mock_popen.call_args.kwargs["env"]
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_glm_without_key_fails_loud(self):
        self.bot.ZAI_API_KEY = ""
        runner = self.bot.ClaudeRunner()
        with patch.object(self.bot.subprocess, "Popen") as mock_popen:
            runner.run(prompt="hi", model="glm-4.7", system_prompt=None)
        mock_popen.assert_not_called()
        self.assertIn("ZAI_API_KEY", runner.error_text)
        self.assertFalse(runner.running)

    def test_glm_prefix_inference(self):
        self.assertEqual(self.bot.model_provider("glm-future-99"), "zai")
        self.assertEqual(self.bot.model_provider("sonnet"), "anthropic")
        self.assertEqual(self.bot.model_provider("opus"), "anthropic")
        self.assertEqual(self.bot.model_provider("haiku"), "anthropic")
        self.assertEqual(self.bot.model_provider("glm-4.7"), "zai")


class CodexHandleEvent(unittest.TestCase):
    """Parser tests for CodexRunner._handle_event. Drives the JSONL shapes
    documented by the Codex CLI (thread.started, item.started/completed,
    turn.completed, error) to lock the normalization contract. # VERIFY field
    names against real sample output during smoke test."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def setUp(self):
        self.runner = self.bot.CodexRunner()
        self.runner.running = True

    def test_thread_started_captures_session_id(self):
        self.runner._handle_event({"type": "thread.started", "thread_id": "thr-xyz"})
        self.assertEqual(self.runner.captured_session_id, "thr-xyz")

    def test_agent_message_item_accumulates_text(self):
        self.runner._handle_event({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Olá "},
        })
        self.runner._handle_event({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "mundo"},
        })
        self.assertEqual(self.runner.accumulated_text, "Olá mundo")
        self.assertEqual(self.runner.activity_type, "text")

    def test_reasoning_item_accumulates_thinking(self):
        self.runner._handle_event({
            "type": "item.completed",
            "item": {"type": "reasoning", "text": "pensando..."},
        })
        self.assertIn("pensando", self.runner.accumulated_thinking)
        self.assertEqual(self.runner.activity_type, "thinking")

    def test_command_execution_logs_tool_call(self):
        self.runner._handle_event({
            "type": "item.started",
            "item": {"type": "command_execution", "command": "ls -la /tmp"},
        })
        self.assertEqual(len(self.runner.tool_log), 1)
        self.assertIn("Bash", self.runner.tool_log[0])
        self.assertIn("ls -la", self.runner.tool_log[0])

    def test_file_change_logs_edit(self):
        self.runner._handle_event({
            "type": "item.started",
            "item": {"type": "file_change", "path": "src/models/user.py"},
        })
        self.assertEqual(len(self.runner.tool_log), 1)
        self.assertIn("Edit", self.runner.tool_log[0])

    def test_turn_completed_finalizes_result_text(self):
        self.runner.accumulated_text = "resposta acumulada"
        self.runner._handle_event({"type": "turn.completed", "usage": {"input_tokens": 10}})
        self.assertEqual(self.runner.result_text, "resposta acumulada")

    def test_error_event_sets_error_text_translated(self):
        self.runner._handle_event({
            "type": "error",
            "error": {"message": "rate limit exceeded, try later"},
        })
        self.assertIn("Rate limit", self.runner.error_text)

    def test_unknown_event_does_not_crash(self):
        self.runner._handle_event({"type": "fancy.new.event", "data": "?"})

    def test_tool_log_caps_at_200(self):
        for i in range(250):
            self.runner._handle_event({
                "type": "item.started",
                "item": {"type": "command_execution", "command": f"echo {i}"},
            })
        self.assertLessEqual(len(self.runner.tool_log), 200)


class MakeRunnerForDispatch(unittest.TestCase):
    """Ensure _make_runner_for picks CodexRunner vs ClaudeRunner by provider."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_gpt_returns_codex_runner(self):
        r = self.bot._make_runner_for("gpt-5")
        self.assertIsInstance(r, self.bot.CodexRunner)

    def test_gpt_codex_returns_codex_runner(self):
        r = self.bot._make_runner_for("gpt-5-codex")
        self.assertIsInstance(r, self.bot.CodexRunner)

    def test_sonnet_returns_claude_runner(self):
        r = self.bot._make_runner_for("sonnet")
        self.assertIsInstance(r, self.bot.ClaudeRunner)

    def test_glm_returns_claude_runner(self):
        # GLM still uses ClaudeRunner (via z.AI proxy), not CodexRunner
        r = self.bot._make_runner_for("glm-5.1")
        self.assertIsInstance(r, self.bot.ClaudeRunner)


class CodexRunnerAuthGate(unittest.TestCase):
    """Ensure CodexRunner fails loud before subprocess when auth is missing."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_missing_binary_sets_error_and_bails(self):
        # Patch the detector too — the runner re-detects when disabled, so on
        # machines that actually have codex installed the test would otherwise
        # fall through to the real binary.
        self.bot.CODEX_ENABLED = False
        self.bot.CODEX_PATH = None
        runner = self.bot.CodexRunner()
        with patch.object(self.bot, "_detect_codex_path", return_value=None), \
             patch.object(self.bot.subprocess, "Popen") as mock_popen:
            runner.run(prompt="hi", model="gpt-5", system_prompt=None)
        mock_popen.assert_not_called()
        self.assertIn("Codex CLI", runner.error_text)

    def test_missing_auth_sets_error_and_bails(self):
        self.bot.CODEX_ENABLED = True
        self.bot.CODEX_PATH = "/tmp/fake-codex-that-exists"
        # Make the fake binary actually exist so the early guard passes
        open(self.bot.CODEX_PATH, "w").close()
        # Point auth file at a non-existent path
        self.bot._CODEX_AUTH_FILE = self.bot.Path("/tmp/__definitely_not_there__codex_auth.json")
        try:
            runner = self.bot.CodexRunner()
            with patch.object(self.bot.subprocess, "Popen") as mock_popen:
                runner.run(prompt="hi", model="gpt-5", system_prompt=None)
            mock_popen.assert_not_called()
            self.assertIn("codex login", runner.error_text)
        finally:
            os.remove(self.bot.CODEX_PATH)


if __name__ == "__main__":
    unittest.main()
