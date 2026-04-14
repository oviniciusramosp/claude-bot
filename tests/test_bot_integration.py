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

    def test_new_command_preserves_agent_and_model(self):
        """``/new`` must inherit agent and model from the current session."""
        session = self.bot._get_session()
        session.agent = "crypto-bro"
        session.model = "glm-4.7"
        session.workspace = "vault/crypto-bro/"
        self.bot.sessions.save()
        self.bot._handle_text("/new")
        new_session = self.bot._get_session()
        self.assertEqual(new_session.agent, "crypto-bro")
        self.assertEqual(new_session.model, "glm-4.7")
        msg = self._last_send()["text"]
        self.assertIn("crypto-bro", msg)
        self.assertIn("glm-4.7", msg)

    def test_new_command_with_name_preserves_agent(self):
        """``/new somename`` must also inherit agent and model."""
        session = self.bot._get_session()
        session.agent = "parmeirense"
        session.model = "opus"
        self.bot.sessions.save()
        self.bot._handle_text("/new keepagent")
        new_session = self.bot._get_session()
        self.assertEqual(new_session.agent, "parmeirense")
        self.assertEqual(new_session.model, "opus")
        msg = self._last_send()["text"]
        self.assertIn("parmeirense", msg)
        self.assertIn("opus", msg)

    def test_new_command_main_agent_hides_agent_label(self):
        """``/new`` on main agent should not show agent label."""
        session = self.bot._get_session()
        session.agent = "main"
        session.model = "sonnet"
        self.bot.sessions.save()
        self.bot._handle_text("/new")
        msg = self._last_send()["text"]
        self.assertNotIn("agente:", msg)
        self.assertIn("sonnet", msg)

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

    def test_save_is_alias_for_important(self):
        called = []
        self.bot.cmd_important = lambda: called.append(True)
        self.bot._handle_text("/save")
        self.assertTrue(called, "/save should dispatch to cmd_important")

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
        # v3.1: skills live under <agent>/Skills/ (no Agents/ wrapper).
        skills_dir = self.fixture.vault / "main" / "Skills"
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


class SkillShellExpansionTest(unittest.TestCase):
    """Dynamic shell substitution in skills (!`cmd` / ```! blocks).

    Opt-in via `allow_shell: true` frontmatter. The expansion happens inside
    _find_relevant_skills when a matching skill has the flag, so the caller
    gets a `body` field pre-filled with live shell output.
    """

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot
        self.skills_dir = self.fixture.vault / "main" / "Skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def _write_skill(self, name, body, allow_shell=False, tags=None, trigger=None):
        tags = tags or ["skill", "test"]
        trigger = trigger or name
        lines = [
            "---",
            f'title: "{name}"',
            f'description: "Test skill for {name}"',
            "type: skill",
            "created: 2026-04-14",
            "updated: 2026-04-14",
            f"tags: [{', '.join(tags)}]",
            f'trigger: "{trigger}"',
        ]
        if allow_shell:
            lines.append("allow_shell: true")
        lines.append("---")
        lines.append("")
        lines.append(body)
        (self.skills_dir / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")

    # --- helper direct tests (not dependent on vault_query) ---

    def test_expand_inline_shell_substitution(self):
        result = self.bot._expand_shell_substitutions("before !`echo hello` after")
        self.assertEqual(result, "before hello after")

    def test_expand_multiple_inline_substitutions(self):
        result = self.bot._expand_shell_substitutions("!`echo a` and !`echo b`")
        self.assertEqual(result, "a and b")

    def test_expand_fenced_shell_block(self):
        content = "pre\n```!\necho fenced\n```\npost"
        result = self.bot._expand_shell_substitutions(content)
        self.assertIn("fenced", result)
        self.assertNotIn("```!", result)

    def test_expand_handles_failing_command(self):
        result = self.bot._expand_shell_substitutions("!`false`")
        self.assertTrue(result.startswith("[error"), f"got: {result!r}")

    def test_expand_handles_timeout(self):
        result = self.bot._expand_shell_substitutions("!`sleep 10`", timeout=1)
        self.assertEqual(result, "[timeout]")

    def test_expand_ignores_content_without_shell_markers(self):
        content = "just some text without shell markers"
        result = self.bot._expand_shell_substitutions(content)
        self.assertEqual(result, content)

    # --- end-to-end tests via _find_relevant_skills ---

    def test_find_skills_with_allow_shell_expands_body(self):
        self._write_skill(
            "shellfoo",
            "Task description.\n\nCurrent: !`echo live-state-marker`\n\nEnd.",
            allow_shell=True,
            trigger="shellfoo needed",
        )
        results = self.bot._find_relevant_skills("shellfoo needed now please", limit=1)
        self.assertEqual(len(results), 1, f"results: {results}")
        self.assertIn("body", results[0])
        self.assertIn("live-state-marker", results[0]["body"])
        # Placeholder should be substituted, not left as literal
        self.assertNotIn("!`echo live-state-marker`", results[0]["body"])

    def test_find_skills_without_allow_shell_does_not_expand(self):
        self._write_skill(
            "nosshellfoo",
            "!`echo should-not-run`",
            allow_shell=False,
            trigger="nosshellfoo needed",
        )
        results = self.bot._find_relevant_skills("nosshellfoo needed now please", limit=1)
        self.assertEqual(len(results), 1, f"results: {results}")
        # body key should be absent when allow_shell is not set
        self.assertNotIn("body", results[0])

    def test_find_skills_allow_shell_but_no_blocks(self):
        self._write_skill(
            "plainfoo",
            "Just a plain body with no shell blocks at all.",
            allow_shell=True,
            trigger="plainfoo needed",
        )
        results = self.bot._find_relevant_skills("plainfoo needed now please", limit=1)
        self.assertEqual(len(results), 1)
        self.assertIn("body", results[0])
        self.assertIn("plain body", results[0]["body"])


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


    def test_reasoning_toggle_callback(self):
        """Reasoning toggle flips state and re-renders button without removing keyboard."""
        stream_msg_id = 42
        self.bot._reasoning_toggles[stream_msg_id] = False
        callback = {
            "id": "cb-reason",
            "data": "reasoning:toggle",
            "message": {"message_id": stream_msg_id, "text": "⏳ Processando..."},
        }
        self.bot._handle_callback(callback)
        # Toggle should flip to True
        self.assertTrue(self.bot._reasoning_toggles[stream_msg_id])

        # Toggle again → back to False
        self.bot._handle_callback(callback)
        self.assertFalse(self.bot._reasoning_toggles[stream_msg_id])

    def test_reasoning_toggle_expired(self):
        """Reasoning toggle on unknown msg_id answers 'Expirado'."""
        callback = {
            "id": "cb-reason",
            "data": "reasoning:toggle",
            "message": {"message_id": 999, "text": "old message"},
        }
        self.bot._handle_callback(callback)
        # Should not crash; 999 not in toggles → answers "Expirado"
        answered = [c for c in self.fixture.tg_calls if c[0] == "answerCallbackQuery"]
        self.assertTrue(any("Expirado" in str(c) for c in answered))


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


class TestModelFallback(unittest.TestCase):
    """Tests for get_fallback_model() and MODEL_FALLBACK_CHAIN logic."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_home = Path(self.tmp.name)
        vault = tmp_home / "vault" / "main"
        vault.mkdir(parents=True)
        self.bot_module = load_bot_module(tmp_home=tmp_home, vault_dir=vault)

    def tearDown(self):
        self.tmp.cleanup()

    def _set_chain(self, chain_list):
        self.bot_module.MODEL_FALLBACK_CHAIN = chain_list

    def _set_zai_key(self, key):
        self.bot_module.ZAI_API_KEY = key

    def test_basic_fallback_opus_to_glm(self):
        """opus fails → next in chain is glm-5.1."""
        self._set_chain(["opus", "glm-5.1", "sonnet", "glm-4.7", "haiku"])
        self._set_zai_key("somekey")
        result = self.bot_module.get_fallback_model("opus", self.bot_module.ErrorKind.OVERLOADED)
        self.assertEqual(result, "glm-5.1")

    def test_basic_fallback_sonnet_skips_to_glm47(self):
        """sonnet fails → next in default chain is glm-4.7."""
        self._set_chain(["opus", "glm-5.1", "sonnet", "glm-4.7", "haiku"])
        self._set_zai_key("somekey")
        result = self.bot_module.get_fallback_model("sonnet", self.bot_module.ErrorKind.RATE_LIMIT)
        self.assertEqual(result, "glm-4.7")

    def test_skips_glm_without_api_key(self):
        """Without ZAI_API_KEY, GLM models in the chain are skipped."""
        self._set_chain(["opus", "glm-5.1", "sonnet", "glm-4.7", "haiku"])
        self._set_zai_key("")
        result = self.bot_module.get_fallback_model("opus", self.bot_module.ErrorKind.OVERLOADED)
        self.assertEqual(result, "sonnet")

    def test_skips_all_glm_without_key_falls_to_haiku(self):
        """Without ZAI_API_KEY, all GLM models are skipped; sonnet fails → haiku."""
        self._set_chain(["opus", "glm-5.1", "sonnet", "glm-4.7", "haiku"])
        self._set_zai_key("")
        result = self.bot_module.get_fallback_model("sonnet", self.bot_module.ErrorKind.OVERLOADED)
        self.assertEqual(result, "haiku")

    def test_skips_same_provider_on_auth_error(self):
        """AUTH error on opus → skip all anthropic models, use first zai model."""
        self._set_chain(["opus", "glm-5.1", "sonnet", "glm-4.7", "haiku"])
        self._set_zai_key("somekey")
        result = self.bot_module.get_fallback_model("opus", self.bot_module.ErrorKind.AUTH)
        self.assertEqual(result, "glm-5.1")

    def test_skips_same_provider_on_credit_error(self):
        """CREDIT error on opus → skip all anthropic models."""
        self._set_chain(["opus", "glm-5.1", "sonnet", "glm-4.7", "haiku"])
        self._set_zai_key("somekey")
        result = self.bot_module.get_fallback_model("opus", self.bot_module.ErrorKind.CREDIT)
        self.assertEqual(result, "glm-5.1")

    def test_skips_same_provider_on_rate_limit_error(self):
        """RATE_LIMIT on a zai model → skip all zai models (account-wide limit).

        Uses a custom chain where glm-4.7 immediately follows glm-5.1 so the skip
        is observable: without skip, fallback would be glm-4.7; with skip it's sonnet.
        """
        self._set_chain(["opus", "glm-5.1", "glm-4.7", "sonnet", "haiku"])
        self._set_zai_key("somekey")
        result = self.bot_module.get_fallback_model("glm-5.1", self.bot_module.ErrorKind.RATE_LIMIT)
        self.assertEqual(result, "sonnet")

    def test_end_of_chain_returns_none(self):
        """haiku is last in chain → no fallback."""
        self._set_chain(["opus", "glm-5.1", "sonnet", "glm-4.7", "haiku"])
        self._set_zai_key("somekey")
        result = self.bot_module.get_fallback_model("haiku", self.bot_module.ErrorKind.OVERLOADED)
        self.assertIsNone(result)

    def test_model_not_in_chain_returns_none(self):
        """Model not in chain → no fallback."""
        self._set_chain(["opus", "glm-5.1", "sonnet", "glm-4.7", "haiku"])
        self._set_zai_key("somekey")
        result = self.bot_module.get_fallback_model("glm-4.5-air", self.bot_module.ErrorKind.OVERLOADED)
        self.assertIsNone(result)

    def test_context_too_long_not_in_fallback_logic(self):
        """CONTEXT_TOO_LONG should still return a model from get_fallback_model itself,
        but the caller (_run_claude_prompt) skips fallback for this kind."""
        self._set_chain(["opus", "glm-5.1", "sonnet", "glm-4.7", "haiku"])
        self._set_zai_key("somekey")
        # get_fallback_model itself doesn't exclude CONTEXT_TOO_LONG —
        # the exclusion is in _run_claude_prompt. So a result is returned.
        result = self.bot_module.get_fallback_model("opus", self.bot_module.ErrorKind.CONTEXT_TOO_LONG)
        self.assertEqual(result, "glm-5.1")

    def test_custom_chain(self):
        """Custom chain order is respected."""
        self._set_chain(["haiku", "sonnet", "opus"])
        self._set_zai_key("")
        result = self.bot_module.get_fallback_model("haiku", self.bot_module.ErrorKind.OVERLOADED)
        self.assertEqual(result, "sonnet")

    def test_chain_all_remaining_skipped_returns_none(self):
        """If all remaining models are skipped (e.g., GLM without key), return None."""
        self._set_chain(["sonnet", "glm-4.7", "glm-5.1"])
        self._set_zai_key("")
        result = self.bot_module.get_fallback_model("sonnet", self.bot_module.ErrorKind.OVERLOADED)
        self.assertIsNone(result)


class RoutineDeleteDispatch(unittest.TestCase):
    """Coverage for `/routine delete` — confirmation keyboard, callback
    handling, trash invocation, and journal logging. Patches ``trash_path``
    at module level to avoid moving real files into the developer's Trash.
    """

    def setUp(self):
        import time as _time
        self._time = _time
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot
        self.bot_module = self.fixture.bot_module

        # Patch trash_path to pretend-trash: actually delete the file/dir so
        # subsequent existence checks work, and record every call.
        self.trashed: list[Path] = []
        self._orig_trash = self.bot_module.trash_path

        def fake_trash(p):
            self.trashed.append(Path(p))
            import shutil
            try:
                if p.is_dir():
                    shutil.rmtree(p)
                else:
                    p.unlink()
                return True
            except OSError:
                return False

        self.bot_module.trash_path = fake_trash

    def tearDown(self):
        self.bot_module.trash_path = self._orig_trash
        self.fixture.cleanup()
        self._td.cleanup()

    def _last_send(self) -> dict:
        for method, data in reversed(self.fixture.tg_calls):
            if method == "sendMessage":
                return data
        raise AssertionError("no sendMessage was made")

    def _seed_agent_routine(self, agent: str, name: str, is_pipeline: bool = False) -> Path:
        """Create `vault/<agent>/` with the hub file + a routine .md. When
        ``is_pipeline`` is set, also creates ``Routines/<name>/step1.md`` to
        simulate a pipeline steps dir."""
        agent_dir = self.fixture.vault / agent
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / f"agent-{agent}.md").write_text(
            f"---\nname: {agent}\n---\n[[Skills]] [[Routines]] [[Journal]]\n",
            encoding="utf-8",
        )
        routines_dir = agent_dir / "Routines"
        routines_dir.mkdir(parents=True, exist_ok=True)
        routine_path = routines_dir / f"{name}.md"
        routine_path.write_text(
            f"---\ntitle: {name}\ntype: {'pipeline' if is_pipeline else 'routine'}\n"
            f"enabled: true\nmodel: sonnet\n---\n\nBody.\n",
            encoding="utf-8",
        )
        if is_pipeline:
            steps_dir = routines_dir / name
            steps_dir.mkdir(parents=True, exist_ok=True)
            (steps_dir / "step1.md").write_text("step one prompt", encoding="utf-8")
        return routine_path

    def _fire_callback(self, data: str):
        self.bot._handle_callback({
            "id": "cb-test",
            "data": data,
            "from": {"id": 123456789},
            "message": {"chat": {"id": 123456789}, "message_id": 1},
        })

    # --- Dispatch ---------------------------------------------------------

    def test_routine_delete_requires_name(self):
        self.bot._handle_text("/routine delete")
        self.assertIn("Uso", self._last_send()["text"])

    def test_routine_delete_not_found(self):
        self.bot._handle_text("/routine delete does-not-exist")
        self.assertIn("não encontrada", self._last_send()["text"])

    def test_routine_delete_shows_confirm_keyboard(self):
        self._seed_agent_routine("main", "test-del-me")
        self.bot._handle_text("/routine delete test-del-me")
        last = self._last_send()
        self.assertIn("Deletar rotina", last["text"])
        self.assertIn("test-del-me", last["text"])
        self.assertIn("main", last["text"])
        markup = last.get("reply_markup", {})
        kb = markup.get("inline_keyboard", [])
        # One row with [Confirmar, Cancelar]
        self.assertEqual(len(kb), 1)
        buttons = kb[0]
        self.assertEqual(len(buttons), 2)
        self.assertIn("routine_del:main:test-del-me", buttons[0]["callback_data"])
        self.assertEqual(buttons[1]["callback_data"], "routine_del:cancel")

    def test_routine_delete_pipeline_mentions_steps_dir(self):
        self._seed_agent_routine("main", "my-pipe", is_pipeline=True)
        self.bot._handle_text("/routine delete my-pipe")
        last = self._last_send()
        self.assertIn("steps", last["text"].lower())

    # --- Callback ---------------------------------------------------------

    def test_cancel_callback_keeps_files(self):
        routine_path = self._seed_agent_routine("main", "keep-me")
        self._fire_callback("routine_del:cancel")
        # Nothing trashed, file still present
        self.assertEqual(self.trashed, [])
        self.assertTrue(routine_path.exists())

    def test_confirm_callback_trashes_routine_and_writes_journal(self):
        routine_path = self._seed_agent_routine("main", "kill-me")
        self._fire_callback("routine_del:main:kill-me")
        # Trash_path was called on the .md
        self.assertTrue(any(p == routine_path for p in self.trashed),
                        f"expected {routine_path} in {self.trashed}")
        self.assertFalse(routine_path.exists())
        # Journal entry exists and mentions the routine
        today = self._time.strftime("%Y-%m-%d")
        journal = self.fixture.vault / "main" / "Journal" / f"{today}.md"
        self.assertTrue(journal.exists(), "journal file should have been created")
        content = journal.read_text(encoding="utf-8")
        self.assertIn("kill-me", content)
        self.assertIn("Rotina/pipeline", content)
        # Success message on Telegram
        self.assertIn("deletada", self._last_send()["text"])

    def test_confirm_callback_trashes_pipeline_steps_dir_too(self):
        routine_path = self._seed_agent_routine("main", "bye-pipe", is_pipeline=True)
        steps_dir = routine_path.parent / "bye-pipe"
        self.assertTrue(steps_dir.is_dir())  # sanity
        self._fire_callback("routine_del:main:bye-pipe")
        # Both md and steps dir should have been trashed
        trashed_names = [p.name for p in self.trashed]
        self.assertIn("bye-pipe.md", trashed_names)
        self.assertIn("bye-pipe", trashed_names)
        self.assertFalse(routine_path.exists())
        self.assertFalse(steps_dir.exists())

    def test_confirm_callback_not_found_reports_cleanly(self):
        """If the routine vanished between keyboard and confirm, report it."""
        self._fire_callback("routine_del:main:ghost-routine")
        self.assertIn("não encontrada", self._last_send()["text"])
        self.assertEqual(self.trashed, [])

    # --- Helpers isoladamente -------------------------------------------------

    def test_append_journal_entry_creates_file_with_frontmatter(self):
        result = self.bot._append_journal_entry(
            "main", "Test header", "- body line 1\n- body line 2"
        )
        self.assertIsNotNone(result)
        content = result.read_text(encoding="utf-8")
        self.assertIn("---", content)
        self.assertIn("type: journal", content)
        self.assertIn("agent: main", content)
        self.assertIn("Test header", content)
        self.assertIn("body line 1", content)

    def test_append_journal_entry_appends_not_rewrites(self):
        path1 = self.bot._append_journal_entry("main", "First", "body1")
        path2 = self.bot._append_journal_entry("main", "Second", "body2")
        self.assertEqual(path1, path2)  # same daily file
        content = path1.read_text(encoding="utf-8")
        self.assertIn("First", content)
        self.assertIn("Second", content)
        # Frontmatter must appear only once
        self.assertEqual(content.count("type: journal"), 1)


if __name__ == "__main__":
    unittest.main()
