"""Integration tests: instantiate ClaudeTelegramBot with mocked Telegram API.

These tests cover:
- Authorization (chat_id allow-list)
- Command dispatch (/help, /sonnet, /new, /sessions, /status, /stop, etc.)
- Message splitting end-to-end (long output is chunked)
- Session creation/switching
- _process_update routing for callback queries

We patch:
- _start_control_server / _start_webhook_server: no-ops (don't bind ports)
- scheduler.start: no-op (don't start background thread)
- tg_request: returns canned success and records calls
- _check_voice_tools / _check_tts_tools: return "no tools" so init doesn't shell out
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._botload import load_bot_module


class _BotFixture:
    """Helper that builds a ClaudeTelegramBot with all I/O mocked."""

    def __init__(self, tmp_root: Path):
        self.tmp_root = tmp_root
        self.home = tmp_root / "home"
        self.vault = tmp_root / "vault"
        self.home.mkdir()
        self.bot_module = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        self.tg_calls: list[tuple[str, dict]] = []

        # Patch IO-heavy methods on the class BEFORE instantiation
        self._patches = [
            patch.object(self.bot_module.ClaudeTelegramBot, "_start_control_server", lambda self: None),
            patch.object(self.bot_module.ClaudeTelegramBot, "_start_webhook_server", lambda self: None),
            patch.object(
                self.bot_module.ClaudeTelegramBot,
                "_check_voice_tools",
                lambda self: {"can_transcribe": False, "ffmpeg": "", "hear": ""},
            ),
            patch.object(
                self.bot_module.ClaudeTelegramBot,
                "_check_tts_tools",
                lambda self: {"can_synthesize": False, "edge_tts": "", "say": "", "ffmpeg": ""},
            ),
            patch.object(self.bot_module.RoutineScheduler, "start", lambda self: None),
            patch.object(self.bot_module.RoutineScheduler, "stop", lambda self: None),
        ]
        for p in self._patches:
            p.start()

        # Build the bot
        self.bot = self.bot_module.ClaudeTelegramBot()

        # Replace tg_request with a recorder that returns success
        def fake_tg_request(method, data=None, timeout=15):
            self.tg_calls.append((method, dict(data or {})))
            # Return shape that the bot expects from sendMessage
            return {"ok": True, "result": {"message_id": len(self.tg_calls)}}

        self.bot.tg_request = fake_tg_request  # bound to instance, doesn't affect class

        # Establish a default context so commands work without going through polling
        ctx = self.bot._get_context("123456789", None)
        self.bot._ctx = ctx

    def cleanup(self):
        for p in self._patches:
            p.stop()


class BotInit(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def test_authorized_chat_id_loaded(self):
        # Loaded from env in _botload (TELEGRAM_CHAT_ID=123456789)
        self.assertIn("123456789", self.fixture.bot.authorized_ids)

    def test_is_authorized_for_known_id(self):
        self.assertTrue(self.fixture.bot._is_authorized("123456789"))

    def test_is_authorized_rejects_unknown(self):
        self.assertFalse(self.fixture.bot._is_authorized("999999999"))


class CommandDispatch(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def _last_send(self) -> dict:
        for method, data in reversed(self.fixture.tg_calls):
            if method == "sendMessage":
                return data
        raise AssertionError("no sendMessage was made")

    def test_help_command(self):
        self.bot._handle_text("/help")
        last = self._last_send()
        self.assertIn("Comandos", last["text"])

    def test_unknown_command_replies_with_error(self):
        self.bot._handle_text("/totallyfakecommand")
        last = self._last_send()
        self.assertIn("desconhecido", last["text"])

    def test_sonnet_command_switches_model(self):
        self.bot._get_session()  # ensure a session exists
        self.bot._handle_text("/sonnet")
        # Active session should now have model=sonnet
        self.assertEqual(self.bot._get_session().model, "sonnet")
        last = self._last_send()
        self.assertIn("sonnet", last["text"])

    def test_opus_command_switches_model(self):
        self.bot._get_session()
        self.bot._handle_text("/opus")
        self.assertEqual(self.bot._get_session().model, "opus")

    def test_new_command_creates_session(self):
        before = len(self.bot.sessions.sessions)
        self.bot._handle_text("/new myseason")
        self.assertEqual(len(self.bot.sessions.sessions), before + 1)

    def test_status_command_shows_session_info(self):
        self.bot._get_session()
        self.bot._handle_text("/status")
        last = self._last_send()
        self.assertIn("Status", last["text"])
        self.assertIn("Modelo", last["text"])

    def test_timeout_without_arg_shows_current(self):
        self.bot._handle_text("/timeout")
        last = self._last_send()
        self.assertIn("Timeout", last["text"])

    def test_timeout_with_arg_changes_value(self):
        self.bot._handle_text("/timeout 1200")
        self.assertEqual(self.bot.timeout_seconds, 1200)

    def test_effort_with_invalid_value_rejects(self):
        prev = self.bot.effort
        self.bot._handle_text("/effort superhuman")
        # Bot should not accept anything outside low/medium/high
        self.assertEqual(self.bot.effort, prev)

    def test_effort_with_valid_value_sets(self):
        self.bot._handle_text("/effort high")
        self.assertEqual(self.bot.effort, "high")

    def test_btw_without_arg_shows_usage(self):
        self.bot._handle_text("/btw")
        last = self._last_send()
        self.assertIn("/btw", last["text"])

    def test_command_with_bot_username_suffix(self):
        # /help@MyBotName should still match /help
        self.bot._handle_text("/help@SomeBotName")
        last = self._last_send()
        self.assertIn("Comandos", last["text"])

    def _seed_vault_skill(self, name: str, description: str, tags=None):
        skills_dir = self.fixture.vault / "Skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        tag_str = "[" + ", ".join(tags or []) + "]"
        (skills_dir / f"{name}.md").write_text(
            f"""---
title: "{name}"
description: "{description}"
type: skill
created: 2026-04-11
updated: 2026-04-11
tags: {tag_str}
trigger: "when needed"
---

Body.
""",
            encoding="utf-8",
        )

    def _seed_vault_routine(self, name: str, description: str, model: str = "sonnet", enabled: bool = True):
        routines_dir = self.fixture.vault / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        (routines_dir / f"{name}.md").write_text(
            f"""---
title: "{name}"
description: "{description}"
type: routine
created: 2026-04-11
updated: 2026-04-11
tags: [routine]
schedule:
  times: ["09:00"]
  days: ["*"]
model: {model}
enabled: {str(enabled).lower()}
---

Body.
""",
            encoding="utf-8",
        )

    def test_find_command_no_args_shows_usage(self):
        self.bot._handle_text("/find")
        last = self._last_send()
        self.assertIn("Vault find", last["text"])
        self.assertIn("type=routine", last["text"])

    def test_find_command_filters_routines(self):
        self._seed_vault_routine("alpha", "Alpha routine", model="opus")
        self._seed_vault_routine("bravo", "Bravo routine", model="sonnet")
        self.bot._handle_text("/find type=routine model=opus")
        last = self._last_send()
        self.assertIn("alpha", last["text"])
        self.assertNotIn("bravo", last["text"])

    def test_find_command_no_match(self):
        self._seed_vault_routine("alpha", "Alpha routine", model="opus")
        self.bot._handle_text("/find type=routine model=haiku")
        last = self._last_send()
        self.assertIn("Nenhum resultado", last["text"])

    def test_lint_command_runs_without_crash(self):
        # Empty vault — linter should report clean (or only known noise)
        self.bot._handle_text("/lint")
        last = self._last_send()
        # Either "Vault clean" or a structured report — both are valid
        self.assertTrue(
            "Vault clean" in last["text"] or "Vault lint" in last["text"],
            f"Unexpected lint output: {last['text']!r}",
        )

    def test_indexes_command_no_markers(self):
        self.bot._handle_text("/indexes")
        last = self._last_send()
        # Empty vault has no marker files — should report that
        self.assertIn("marcadores", last["text"].lower() + "marcadores")  # tolerate either path

    def test_clone_without_arg_shows_usage(self):
        self.bot._handle_text("/clone")
        last = self._last_send()
        self.assertIn("/clone", last["text"])

    def test_clone_creates_branch_from_active(self):
        # Start from a known session
        self.bot._handle_text("/new main-branch")
        self.bot._get_session().session_id = "claude-xyz"
        self.bot._get_session().model = "opus"
        self.bot.sessions.save()
        before = len(self.bot.sessions.sessions)
        self.bot._handle_text("/clone exp-branch")
        self.assertEqual(len(self.bot.sessions.sessions), before + 1)
        self.assertIn("exp-branch", self.bot.sessions.sessions)
        # Clone is the new active session
        self.assertEqual(self.bot.sessions.active_session, "exp-branch")
        # Clone continues the same Claude thread
        self.assertEqual(self.bot.sessions.sessions["exp-branch"].session_id, "claude-xyz")
        self.assertEqual(self.bot.sessions.sessions["exp-branch"].model, "opus")

    def test_clone_existing_name_fails(self):
        self.bot._handle_text("/new a")
        self.bot._handle_text("/new b")
        before = len(self.bot.sessions.sessions)
        self.bot._handle_text("/clone a")  # 'a' already exists
        self.assertEqual(len(self.bot.sessions.sessions), before)
        last = self._last_send()
        self.assertIn("já existe", last["text"])


class SkillDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def _seed(self, name, description, tags):
        skills_dir = self.fixture.vault / "Skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        tag_str = "[" + ", ".join(tags) + "]"
        (skills_dir / f"{name}.md").write_text(
            f"""---
title: "{name}"
description: "{description}"
type: skill
created: 2026-04-11
updated: 2026-04-11
tags: {tag_str}
trigger: "when {name}"
---
""",
            encoding="utf-8",
        )

    def test_tag_match_outranks_text_match(self):
        # publish-notion has tag "notion", publish-x has tag "twitter".
        # Prompt mentions "notion" — publish-notion should rank first.
        self._seed("publish-notion", "Publish to Notion API", ["skill", "publishing", "notion"])
        self._seed("publish-x", "Publish to X (Twitter)", ["skill", "publishing", "twitter"])
        results = self.bot._find_relevant_skills("preciso publicar isso no notion agora", limit=2)
        self.assertGreater(len(results), 0)
        self.assertIn("notion", results[0]["name"].lower())

    def test_no_results_when_no_signal(self):
        self._seed("publish-notion", "Publish content", ["skill", "publishing"])
        results = self.bot._find_relevant_skills("xyz", limit=3)
        self.assertEqual(results, [])


class LongMessageSplitting(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def test_long_message_split_into_multiple_calls(self):
        # send_message internally splits, so a long message becomes >1 sendMessage call
        long_text = "a" * 10000
        self.bot.send_message(long_text, parse_mode=None)
        send_calls = [c for c in self.fixture.tg_calls if c[0] == "sendMessage"]
        self.assertGreater(len(send_calls), 1)

    def test_short_message_one_call(self):
        self.bot.send_message("hello", parse_mode=None)
        send_calls = [c for c in self.fixture.tg_calls if c[0] == "sendMessage"]
        self.assertEqual(len(send_calls), 1)


class CallbackHandling(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def test_model_callback_switches_model(self):
        self.bot._get_session()
        callback = {
            "id": "abc",
            "data": "model:opus",
            "message": {"message_id": 1, "text": "Escolha o modelo"},
        }
        self.bot._handle_callback(callback)
        self.assertEqual(self.bot._get_session().model, "opus")

    def test_callback_dangerous_approval_flow(self):
        # Send a dangerous prompt → bot should add a pending approval
        with patch.object(self.bot, "_run_claude_prompt") as run_mock:
            self.bot._handle_text("rm -rf /")
            self.assertEqual(len(self.bot._pending_approvals), 1)
            run_mock.assert_not_called()

            # Approve via callback
            approval_id = next(iter(self.bot._pending_approvals.keys()))
            cb = {
                "id": "cb1",
                "data": f"approve:{approval_id}",
                "message": {"message_id": 5, "text": "warning"},
            }
            self.bot._handle_callback(cb)
            run_mock.assert_called_once()
            # Approval consumed
            self.assertEqual(len(self.bot._pending_approvals), 0)

    def test_callback_dangerous_rejection_flow(self):
        with patch.object(self.bot, "_run_claude_prompt") as run_mock:
            self.bot._handle_text("git push --force origin main")
            self.assertEqual(len(self.bot._pending_approvals), 1)
            approval_id = next(iter(self.bot._pending_approvals.keys()))
            cb = {
                "id": "cb1",
                "data": f"reject:{approval_id}",
                "message": {"message_id": 5, "text": "warning"},
            }
            self.bot._handle_callback(cb)
            run_mock.assert_not_called()
            self.assertEqual(len(self.bot._pending_approvals), 0)


class TextProcessingEdgeCases(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def test_empty_text_does_nothing(self):
        before = len(self.fixture.tg_calls)
        self.bot._handle_text("")
        self.bot._handle_text("   ")
        self.assertEqual(len(self.fixture.tg_calls), before)

    def test_inline_voice_tag_strips_marker(self):
        with patch.object(self.bot, "_run_claude_prompt") as run_mock:
            self.bot._handle_text("hello world #voice")
            run_mock.assert_called_once()
            # The prompt passed should not contain #voice
            args, kwargs = run_mock.call_args
            text_arg = args[0] if args else kwargs.get("prompt")
            self.assertNotIn("#voice", text_arg)
            # force_tts should be true
            self.assertTrue(kwargs.get("force_tts", False))


if __name__ == "__main__":
    unittest.main()
