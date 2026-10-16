"""Turn integrity: a turn must not be lost, leaked into argv, or delivered twice.

Three hardening contracts, all of them about the boundary between the bot and
something it does not control:

1. **Dead ``--resume``** — a Claude transcript lives at
   ``~/.claude/projects/<encoded-cwd>/<id>.jsonl``, so it is bound to the cwd it
   was recorded under and is pruned after ~30 days. Passing ``--resume`` for a
   missing one makes the CLI exit with "No conversation found with session ID"
   and ``num_turns: 0`` — the user's turn is spent on an error. The runner now
   checks first and runs fresh instead.
2. **Prompt in argv** — argv is readable via ``ps`` and capped by ARG_MAX (1MB
   on macOS). The prompt now travels on stdin as a stream-json user message.
3. **Duplicate Telegram sends** — the Bot API has no idempotency key, so a
   retry after an *ambiguous* failure can deliver the same message twice. Only
   failures that prove the request never left are retried.
"""
import json
import socket
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._botload import load_bot_module


class _InlineThread:
    """Thread stand-in that runs its target on ``start()``.

    ``_spawn_and_read`` feeds stdin from a thread so a prompt larger than the
    pipe buffer cannot deadlock against the CLI's own output. Tests need that
    write to have happened before they assert, so they swap in this class.
    """

    def __init__(self, target=None, args=(), kwargs=None, **_ignored):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)


def _mock_proc():
    proc = MagicMock()
    proc.stdout = iter([])
    proc.stderr = MagicMock()
    proc.stderr.read.return_value = ""
    proc.stdin = MagicMock()
    proc.wait.return_value = 0
    proc.returncode = 0
    proc.pid = 4321
    return proc


class _RunnerCase(unittest.TestCase):
    """Shared plumbing for tests that spawn ClaudeRunner against a mock Popen."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def setUp(self):
        self._projects = self.bot.CLAUDE_PROJECTS_DIR
        self._tmp = tempfile.TemporaryDirectory(prefix="turn-integrity-")
        self.projects = Path(self._tmp.name) / "projects"
        self.projects.mkdir()
        self.bot.CLAUDE_PROJECTS_DIR = self.projects
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, self.bot, "CLAUDE_PROJECTS_DIR", self._projects)

    def _write_transcript(self, session_id: str, cwd: str) -> Path:
        d = self.projects / self.bot._encode_project_dir(cwd)
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{session_id}.jsonl"
        f.write_text('{"type":"user"}\n', encoding="utf-8")
        return f

    def _run(self, **kwargs):
        """Run the runner against a mock Popen; return (cmd, stdin_writes, runner)."""
        runner = self.bot.ClaudeRunner()
        proc = _mock_proc()
        kwargs.setdefault("prompt", "oi")
        kwargs.setdefault("model", "sonnet")
        kwargs.setdefault("system_prompt", None)
        with patch.object(self.bot.subprocess, "Popen", return_value=proc) as popen, \
                patch.object(self.bot.threading, "Thread", _InlineThread):
            runner.run(**kwargs)
        cmd = popen.call_args[0][0]
        writes = "".join(c.args[0] for c in proc.stdin.write.call_args_list)
        return cmd, writes, runner


class TranscriptResumeGuard(_RunnerCase):
    """--resume is only passed when the transcript the CLI would read exists."""

    WS = "/tmp/some/workspace"

    def test_missing_transcript_is_not_resumable(self):
        self.assertFalse(self.bot._claude_transcript_exists("abc123", self.WS))

    def test_existing_transcript_is_resumable(self):
        self._write_transcript("abc123", self.WS)
        self.assertTrue(self.bot._claude_transcript_exists("abc123", self.WS))

    def test_transcript_is_bound_to_its_cwd(self):
        """The agent-switch case: same id, different workspace → not resumable."""
        self._write_transcript("abc123", self.WS)
        self.assertFalse(
            self.bot._claude_transcript_exists("abc123", "/tmp/other/workspace"))

    def test_no_session_id_is_not_resumable(self):
        self.assertFalse(self.bot._claude_transcript_exists(None, self.WS))
        self.assertFalse(self.bot._claude_transcript_exists("", self.WS))

    def test_stat_error_fails_open(self):
        """An unexpected OSError must never discard a transcript that is there."""
        with patch.object(Path, "exists", side_effect=OSError("boom")):
            self.assertTrue(self.bot._claude_transcript_exists("abc123", self.WS))

    def test_run_drops_stale_resume_and_flags_it(self):
        cmd, _, runner = self._run(session_id="dead-session", workspace=self.WS)
        self.assertNotIn("--resume", cmd)
        self.assertTrue(runner.resume_dropped)

    def test_run_keeps_valid_resume(self):
        self._write_transcript("live-session", self.WS)
        cmd, _, runner = self._run(session_id="live-session", workspace=self.WS)
        self.assertIn("--resume", cmd)
        self.assertEqual(cmd[cmd.index("--resume") + 1], "live-session")
        self.assertFalse(runner.resume_dropped)

    def test_flag_resets_between_runs(self):
        _, _, runner = self._run(session_id="dead-session", workspace=self.WS)
        self.assertTrue(runner.resume_dropped)
        self._write_transcript("live-session", self.WS)
        proc = _mock_proc()
        with patch.object(self.bot.subprocess, "Popen", return_value=proc), \
                patch.object(self.bot.threading, "Thread", _InlineThread):
            runner.run(prompt="oi", model="sonnet", system_prompt=None,
                       session_id="live-session", workspace=self.WS)
        self.assertFalse(runner.resume_dropped)


class PromptViaStdin(_RunnerCase):
    """The prompt travels on stdin, never in argv."""

    def test_prompt_absent_from_argv(self):
        secret = "senha-super-secreta-no-prompt"
        cmd, _, _ = self._run(prompt=secret)
        self.assertNotIn(secret, cmd)
        self.assertFalse(any(secret in a for a in cmd))

    def test_dash_p_prompt_flag_is_gone(self):
        cmd, _, _ = self._run(prompt="oi")
        # --print stays (it is what enables print mode); the `-p <prompt>`
        # positional form must not come back.
        self.assertIn("--print", cmd)
        self.assertNotIn("-p", cmd)

    def test_input_format_is_stream_json(self):
        cmd, _, _ = self._run()
        self.assertIn("--input-format", cmd)
        self.assertEqual(cmd[cmd.index("--input-format") + 1], "stream-json")

    def test_stdin_carries_the_prompt_as_a_user_message(self):
        _, writes, _ = self._run(prompt="qual o saldo?")
        payload = json.loads(writes.strip())
        self.assertEqual(payload["type"], "user")
        self.assertEqual(payload["message"]["role"], "user")
        self.assertEqual(payload["message"]["content"][0]["text"], "qual o saldo?")

    def test_payload_is_one_newline_terminated_line(self):
        """The CLI reads newline-delimited JSON — a stray newline splits it."""
        _, writes, _ = self._run(prompt="linha 1\nlinha 2\n\nlinha 4")
        self.assertTrue(writes.endswith("\n"))
        self.assertEqual(writes.count("\n"), 1)

    def test_payload_preserves_unicode_and_newlines(self):
        prompt = "Lançamento de R$ 1.234,56\nCategoria: impostos — DARF"
        _, writes, _ = self._run(prompt=prompt)
        payload = json.loads(writes.strip())
        self.assertEqual(payload["message"]["content"][0]["text"], prompt)

    def test_feed_stdin_closes_the_pipe(self):
        pipe = MagicMock()
        self.bot.ClaudeRunner._feed_stdin(pipe, '{"type":"user"}\n')
        pipe.write.assert_called_once_with('{"type":"user"}\n')
        pipe.close.assert_called_once()

    def test_feed_stdin_logs_broken_pipe_instead_of_raising(self):
        pipe = MagicMock()
        pipe.write.side_effect = BrokenPipeError("CLI died")
        with self.assertLogs(self.bot.logger, level="ERROR") as cm:
            self.bot.ClaudeRunner._feed_stdin(pipe, "payload\n")
        self.assertTrue(any("stdin write failed" in m for m in cm.output))


class TelegramRetrySafety(unittest.TestCase):
    """A retry may never duplicate user-visible content."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def setUp(self):
        self.tg = self.bot.ClaudeTelegramBot.__new__(self.bot.ClaudeTelegramBot)
        self.tg.base_url = "https://api.telegram.org/botTEST"

    # --- method classification ---
    def test_sends_create_content(self):
        for m in ("sendMessage", "sendPhoto", "sendDocument", "sendVoice",
                  "forwardMessage", "copyMessage"):
            self.assertTrue(self.bot._tg_method_creates_content(m), m)

    def test_reads_and_idempotent_writes_do_not(self):
        for m in ("getUpdates", "getFile", "editMessageText", "deleteMessage",
                  "answerCallbackQuery", "sendChatAction"):
            self.assertFalse(self.bot._tg_method_creates_content(m), m)

    # --- transport-failure classification ---
    def test_dns_failure_on_send_is_safe(self):
        exc = urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided"))
        self.assertTrue(self.bot._tg_retry_is_safe("sendMessage", exc))

    def test_no_route_on_send_is_safe(self):
        exc = urllib.error.URLError(OSError(65, "No route to host"))
        self.assertTrue(self.bot._tg_retry_is_safe("sendMessage", exc))

    def test_handshake_timeout_on_send_is_safe(self):
        exc = urllib.error.URLError(socket.timeout("_ssl.c:1112: handshake timed out"))
        self.assertTrue(self.bot._tg_retry_is_safe("sendMessage", exc))

    def test_response_read_timeout_on_send_is_unsafe(self):
        """Bare (unwrapped) timeout = raised while reading the response."""
        self.assertFalse(
            self.bot._tg_retry_is_safe("sendMessage", socket.timeout("read timed out")))

    def test_connection_reset_on_send_is_unsafe_even_when_wrapped(self):
        """A reset can land after the body flushed, so URLError is no alibi."""
        bare = ConnectionResetError(54, "Connection reset by peer")
        self.assertFalse(self.bot._tg_retry_is_safe("sendMessage", bare))
        self.assertFalse(
            self.bot._tg_retry_is_safe("sendMessage", urllib.error.URLError(bare)))

    def test_ambiguous_failure_is_still_retried_for_reads(self):
        for m in ("getUpdates", "sendChatAction"):
            self.assertTrue(
                self.bot._tg_retry_is_safe(m, socket.timeout("read timed out")), m)

    # --- HTTP-status classification ---
    def test_http_429_always_retries(self):
        self.assertTrue(self.bot._tg_http_retry_is_safe("sendMessage", 429))
        self.assertTrue(self.bot._tg_http_retry_is_safe("getUpdates", 429))

    def test_http_4xx_is_final(self):
        self.assertFalse(self.bot._tg_http_retry_is_safe("sendMessage", 400))
        self.assertFalse(self.bot._tg_http_retry_is_safe("answerCallbackQuery", 400))
        self.assertFalse(self.bot._tg_http_retry_is_safe("sendMessage", 403))

    def test_http_5xx_retries_only_when_a_duplicate_is_impossible(self):
        self.assertFalse(self.bot._tg_http_retry_is_safe("sendMessage", 500))
        self.assertTrue(self.bot._tg_http_retry_is_safe("getUpdates", 500))

    # --- end-to-end through tg_request ---
    def _call(self, method, side_effect):
        with patch.object(self.bot.urllib.request, "urlopen",
                          side_effect=side_effect) as urlopen, \
                patch.object(self.bot.time, "sleep"):
            out = self.tg.tg_request(method, {"chat_id": 1, "text": "oi"})
        return out, urlopen.call_count

    def test_send_is_tried_once_on_ambiguous_failure(self):
        out, calls = self._call("sendMessage", socket.timeout("read timed out"))
        self.assertIsNone(out)
        self.assertEqual(calls, 1, "an ambiguous sendMessage must not be repeated")

    def test_send_retries_when_the_request_never_left(self):
        exc = urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided"))
        out, calls = self._call("sendMessage", exc)
        self.assertIsNone(out)
        self.assertEqual(calls, 3)

    def test_getupdates_retries_on_read_timeout(self):
        out, calls = self._call("getUpdates", socket.timeout("read timed out"))
        self.assertIsNone(out)
        self.assertEqual(calls, 3)

    def test_ambiguous_failure_is_logged_as_unknown_delivery(self):
        with patch.object(self.bot.urllib.request, "urlopen",
                          side_effect=socket.timeout("read timed out")), \
                patch.object(self.bot.time, "sleep"), \
                self.assertLogs(self.bot.logger, level="ERROR") as cm:
            self.tg.tg_request("sendMessage", {"chat_id": 1, "text": "oi"})
        self.assertTrue(any("delivery UNKNOWN" in m for m in cm.output))

    def test_http_400_is_not_hammered_three_times(self):
        def _raise(*_a, **_k):
            raise urllib.error.HTTPError(
                "u", 400, "Bad Request", {},
                __import__("io").BytesIO(b'{"description":"query is too old"}'))
        with patch.object(self.bot.urllib.request, "urlopen", side_effect=_raise) as urlopen, \
                patch.object(self.bot.time, "sleep"):
            out = self.tg.tg_request("answerCallbackQuery", {"callback_query_id": "x"})
        self.assertIsNone(out)
        self.assertEqual(urlopen.call_count, 1)


if __name__ == "__main__":
    unittest.main()
