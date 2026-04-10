"""Tests for ClaudeRunner stream-json event handling.

We don't actually spawn `claude` — instead we drive `_handle_event` directly
with the JSON shapes the CLI emits. This covers the parser without subprocess
flakiness.
"""
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


if __name__ == "__main__":
    unittest.main()
