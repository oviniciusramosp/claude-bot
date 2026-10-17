"""Telegram integration fixes (audit "Lote 1 — bugs e segurança").

Each class pins one fix:
  ReplyCommand          — a command sent as a reply is still a command
  RoutineDestination    — routines never report to an empty chat_id
  Reactions             — reaction emojis are in Telegram's allowed list
  SecondaryAllowlist    — guest chats run an explicit command allowlist
  CommandMenus          — menus only list real, Telegram-valid commands
  TurnMessageBinding    — a message sent mid-turn doesn't hijack the turn
  CallbackDataLimit     — callback_data never exceeds 64 bytes
  SmallUx               — silent startup ping, /cmd@otherbot, unauthorized callbacks
"""
import json
import re
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._botload import ensure_agent_layout
from tests.test_bot_integration import _BotFixture

PRIMARY = "123456789"          # TELEGRAM_CHAT_ID in the test harness
FORUM = "-1001111"
GUEST = "-1002222"

# Telegram Bot API — ReactionTypeEmoji.emoji allowed values (copied from
# https://core.telegram.org/bots/api#reactiontypeemoji). Escaped so variation
# selectors are explicit: "✍" is accepted, "✍️" is NOT.
TELEGRAM_ALLOWED_REACTIONS = frozenset(
    "❤ \U0001f44d \U0001f44e \U0001f525 \U0001f970 \U0001f44f \U0001f601 "
    "\U0001f914 \U0001f92f \U0001f631 \U0001f92c \U0001f622 \U0001f389 \U0001f929 "
    "\U0001f92e \U0001f4a9 \U0001f64f \U0001f44c \U0001f54a \U0001f921 \U0001f971 "
    "\U0001f974 \U0001f60d \U0001f433 ❤‍\U0001f525 \U0001f31a \U0001f32d "
    "\U0001f4af \U0001f923 ⚡ \U0001f34c \U0001f3c6 \U0001f494 \U0001f928 "
    "\U0001f610 \U0001f353 \U0001f37e \U0001f48b \U0001f595 \U0001f608 \U0001f634 "
    "\U0001f62d \U0001f913 \U0001f47b \U0001f468‍\U0001f4bb \U0001f440 "
    "\U0001f383 \U0001f648 \U0001f607 \U0001f628 \U0001f91d ✍ \U0001f917 "
    "\U0001fae1 \U0001f385 \U0001f384 ☃ \U0001f485 \U0001f92a \U0001f5ff "
    "\U0001f192 \U0001f498 \U0001f649 \U0001f984 \U0001f618 \U0001f48a \U0001f64a "
    "\U0001f60e \U0001f47e \U0001f937‍♂ \U0001f937 \U0001f937‍♀ "
    "\U0001f621".split()
)

COMMAND_NAME_RE = re.compile(r"^[a-z0-9_]{1,32}$")


def _write_agent(vault: Path, agent_id: str, *, default: bool = False,
                 chat_id: str = None, thread_id: int = None) -> None:
    base = ensure_agent_layout(vault, agent_id)
    lines = ["---", f"title: {agent_id}", f"description: Test agent {agent_id}",
             "type: agent", f"name: {agent_id}", "model: sonnet", 'icon: "🤖"']
    if default:
        lines.append("default: true")
    if chat_id:
        lines.append(f'chat_id: "{chat_id}"')
    if thread_id is not None:
        lines.append(f"thread_id: {thread_id}")
    lines += ["---", ""]
    (base / f"agent-{agent_id}.md").write_text("\n".join(lines), encoding="utf-8")


def _markup(data: dict) -> dict:
    rm = data.get("reply_markup") or {}
    return json.loads(rm) if isinstance(rm, str) else rm


class _Base(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.f = _BotFixture(Path(self._td.name))
        self.bot = self.f.bot
        self.m = self.f.bot_module

    def tearDown(self):
        self.f.cleanup()
        self._td.cleanup()

    def sent_texts(self):
        return [d.get("text", "") for meth, d in self.f.tg_calls if meth == "sendMessage"]

    def make_guest(self, agent="carol"):
        _write_agent(self.f.vault, agent)
        self.bot.secondary_chats[GUEST] = {"default": agent, "topics": {}}
        self.bot.authorized_ids.add(GUEST)
        self.bot._ctx = self.bot._get_context(GUEST, None)


# ---------------------------------------------------------------------------
# 1. Reply + command
# ---------------------------------------------------------------------------

class ReplyCommand(_Base):
    def _update(self, text):
        return {"message": {
            "message_id": 50, "chat": {"id": int(PRIMARY), "type": "private"},
            "from": {"id": 1, "first_name": "V"}, "text": text,
            "reply_to_message": {"message_id": 40, "from": {"is_bot": True},
                                 "text": "resposta anterior do bot"},
        }}

    def test_command_sent_as_reply_is_dispatched_raw(self):
        with patch.object(self.bot, "_handle_text") as ht:
            self.bot._process_update(self._update("/stop"))
        ht.assert_called_once_with("/stop", user_msg_id=50)

    def test_plain_reply_keeps_reply_context(self):
        with patch.object(self.bot, "_handle_text") as ht:
            self.bot._process_update(self._update("e isso?"))
        sent = ht.call_args[0][0]
        self.assertIn("resposta anterior do bot", sent)
        self.assertTrue(sent.endswith("e isso?"))


# ---------------------------------------------------------------------------
# 2. Routine destination
# ---------------------------------------------------------------------------

class RoutineDestination(_Base):
    def setUp(self):
        super().setUp()
        _write_agent(self.f.vault, "main", default=True)
        self.task = self.m.RoutineTask(name="daily", prompt="p", model="sonnet",
                                       time_slot="07:00", agent="main")

    def _phantom_main_context(self):
        # A ("", None) context whose session runs Main — what won the old
        # dict-order scan on 2026-10-12.
        ctx = self.m.ThreadContext(chat_id="", thread_id=None)
        self.bot.sessions.create("phantom", agent="main")
        ctx.session_name = "phantom"
        self.bot._contexts[("", None)] = ctx

    def test_default_agent_prefers_forum_general_topic(self):
        _write_agent(self.f.vault, "chef", chat_id=FORUM, thread_id=77)
        self.bot.primary_chat_ids.add(FORUM)
        self.bot._refresh_agent_chat_map()
        self._phantom_main_context()
        ctx = self.bot._find_context_for_routine(self.task)
        self.assertEqual((ctx.chat_id, ctx.thread_id), (FORUM, None))

    def test_falls_back_to_private_chat_never_empty(self):
        self._phantom_main_context()
        ctx = self.bot._find_context_for_routine(self.task)
        self.assertEqual((ctx.chat_id, ctx.thread_id), (PRIMARY, None))

    def test_task_without_agent_is_deterministic(self):
        self._phantom_main_context()
        ctx = self.bot._find_context_for_routine(
            self.m.RoutineTask(name="x", prompt="p", model="sonnet", time_slot="07:00"))
        self.assertEqual(ctx.chat_id, PRIMARY)

    def test_guest_agent_routine_goes_to_its_own_chat(self):
        self.make_guest("helper")
        t = self.m.RoutineTask(name="h", prompt="p", model="sonnet",
                               time_slot="07:00", agent="helper")
        ctx = self.bot._find_context_for_routine(t)
        self.assertEqual((ctx.chat_id, ctx.thread_id), (GUEST, None))

    def test_other_agent_never_falls_back_to_guest_chat(self):
        self.make_guest("helper")
        _write_agent(self.f.vault, "other")
        self.bot._get_session().agent = "other"  # guest ctx session runs "other"
        t = self.m.RoutineTask(name="o", prompt="p", model="sonnet",
                               time_slot="07:00", agent="other")
        ctx = self.bot._find_context_for_routine(t)
        self.assertEqual(ctx.chat_id, PRIMARY)

    def test_nothing_valid_logs_error(self):
        self.bot.primary_chat_ids.clear()
        with patch.object(self.m, "TELEGRAM_CHAT_ID", ""), \
                self.assertLogs(self.m.logger, level="ERROR"):
            ctx = self.bot._find_context_for_routine(self.task)
        self.assertEqual(ctx.chat_id, "")
        self.assertNotIn(("", None), self.bot._contexts)

    def test_get_context_empty_chat_is_transient(self):
        ctx = self.bot._get_context("", None)
        self.assertEqual(ctx.chat_id, "")
        self.assertNotIn(("", None), self.bot._contexts)
        self.assertIsNone(ctx.session_name)

    def test_load_contexts_drops_empty_chat(self):
        self.m.CONTEXTS_FILE.write_text(json.dumps({"contexts": [
            {"chat_id": "", "thread_id": None, "session_name": "x"},
            {"chat_id": "0", "thread_id": None, "session_name": "y"},
            {"chat_id": PRIMARY, "thread_id": 5, "session_name": "z"},
        ]}), encoding="utf-8")
        self.bot._contexts.clear()
        self.bot._load_contexts()
        self.assertEqual(set(self.bot._contexts), {(PRIMARY, 5)})


# ---------------------------------------------------------------------------
# 3. Reactions
# ---------------------------------------------------------------------------

class Reactions(_Base):
    def test_every_reaction_is_telegram_allowed(self):
        bad = {k: v for k, v in self.m._REACTION_MAP.items()
               if v not in TELEGRAM_ALLOWED_REACTIONS}
        self.assertEqual(bad, {}, "emojis rejected by setMessageReaction")

    def test_other_literal_reactions_allowed(self):
        for emoji in ("👀", "🤔"):
            self.assertIn(emoji, TELEGRAM_ALLOWED_REACTIONS)

    def test_set_reaction_failure_warns_and_returns_false(self):
        err = urllib.error.HTTPError("u", 400, "Bad Request", {}, None)
        with patch.object(self.m.urllib.request, "urlopen", side_effect=err), \
                self.assertLogs(self.m.logger, level="WARNING") as logs:
            self.assertFalse(self.bot.set_reaction(10, "✍"))
        self.assertTrue(any("set_reaction" in line for line in logs.output))

    def test_update_reaction_not_recorded_on_failure(self):
        ctx = self.bot._ctx
        ctx.user_msg_id = 10
        ctx.last_reaction = "👀"
        runner = MagicMock(activity_type="thinking")
        with patch.object(self.bot, "set_reaction", return_value=False):
            self.bot._update_reaction(runner)
        self.assertEqual(ctx.last_reaction, "👀")
        with patch.object(self.bot, "set_reaction", return_value=True):
            self.bot._update_reaction(runner)
        self.assertEqual(ctx.last_reaction, "🤔")


# ---------------------------------------------------------------------------
# 4. Secondary allowlist
# ---------------------------------------------------------------------------

class SecondaryAllowlist(_Base):
    def setUp(self):
        super().setUp()
        self.make_guest()

    def test_admin_commands_blocked(self):
        for cmd, method in (("/restart", "cmd_restart"), ("/model", "cmd_model_keyboard"),
                            ("/effort high", "cmd_effort"), ("/delegate x", "cmd_delegate"),
                            ("/workspace /tmp", "cmd_workspace"), ("/run x", "cmd_run"),
                            ("/agent list", "cmd_agent"), ("/audio", "cmd_audio")):
            with patch.object(self.bot, method) as fn:
                self.bot._handle_text(cmd)
            fn.assert_not_called()
        self.assertTrue(all("não está disponível" in t for t in self.sent_texts()))

    def test_allowed_commands_dispatch(self):
        with patch.object(self.bot, "cmd_status") as st, \
                patch.object(self.bot, "cmd_stop") as sp:
            self.bot._handle_text("/status")
            self.bot._handle_text("/stop")
        st.assert_called_once()
        sp.assert_called_once()

    def test_help_shows_guest_text(self):
        self.bot._handle_text("/help")
        self.assertIn("Comandos disponíveis neste chat", self.sent_texts()[-1])
        self.assertNotIn("/restart", self.sent_texts()[-1])

    def test_primary_unaffected(self):
        self.bot._ctx = self.bot._get_context(PRIMARY, None)
        with patch.object(self.bot, "cmd_restart") as fn:
            self.bot._handle_text("/restart")
        fn.assert_called_once()

    def test_guest_help_lists_only_allowed(self):
        cmds = set(re.findall(r"(/[a-z_]+)", self.m.SECONDARY_HELP_TEXT))
        self.assertTrue(cmds <= self.m.SECONDARY_ALLOWED_COMMANDS, cmds - self.m.SECONDARY_ALLOWED_COMMANDS)

    def test_secondary_menu_registered_with_chat_scope(self):
        self.bot._register_commands()
        scoped = [d for meth, d in self.f.tg_calls if meth == "setMyCommands"
                  and (d.get("scope") or {}).get("type") == "chat"]
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]["scope"]["chat_id"], int(GUEST))
        names = {"/" + c["command"] for c in scoped[0]["commands"]}
        self.assertTrue(names <= self.m.SECONDARY_ALLOWED_COMMANDS)

    def test_delegate_runs_restricted_in_secondary(self):
        captured = {}
        done = threading.Event()

        class FakeRunner:
            last_activity = 0
            result_text = "ok"
            accumulated_text = ""
            stderr_text = error_text = ""
            running = False

            def run(self, **kw):
                captured.update(kw)
                done.set()

            def cancel(self):
                pass

        with patch.object(self.m, "_make_runner_for", return_value=FakeRunner()):
            self.bot.cmd_delegate("faz algo")
            self.assertTrue(done.wait(5))
        self.assertTrue(captured.get("restricted"))


# ---------------------------------------------------------------------------
# 5. Command menus
# ---------------------------------------------------------------------------

class CommandMenus(_Base):
    MENUS = ("TELEGRAM_PRIVATE_COMMANDS", "TELEGRAM_GROUP_COMMANDS",
             "TELEGRAM_SECONDARY_COMMANDS")

    def _dispatches(self, cmd: str) -> bool:
        """True iff /cmd reaches a handler (all cmd_* are mocked)."""
        before = len(self.f.tg_calls)
        names = [n for n in dir(self.bot) if n.startswith("cmd_")]
        patches = [patch.object(self.bot, n) for n in names]
        for p in patches:
            p.start()
        try:
            self.bot._handle_text(f"/{cmd} arg")
        finally:
            for p in patches:
                p.stop()
        return not any("Comando desconhecido" in d.get("text", "")
                       for meth, d in self.f.tg_calls[before:] if meth == "sendMessage")

    def test_menu_commands_valid_and_dispatch(self):
        for menu in self.MENUS:
            entries = getattr(self.m, menu)
            self.assertLessEqual(len(entries), 100, menu)
            for cmd, desc in entries:
                self.assertRegex(cmd, COMMAND_NAME_RE, f"{menu}: {cmd}")
                self.assertTrue(0 < len(desc) <= 256, f"{menu}: {cmd}")
                self.assertTrue(self._dispatches(cmd), f"{menu}: /{cmd} not in handler_map")

    def test_underscore_aliases(self):
        for alias, method in (("restart_agent", "cmd_restart_agent"),
                              ("active_memory", "cmd_active_memory"),
                              ("dry_run", "cmd_dry_run"),
                              ("dry-run", "cmd_dry_run")):
            with patch.object(self.bot, method) as fn:
                self.bot._handle_text(f"/{alias}")
            fn.assert_called_once()

    def test_help_text_commands_are_tappable(self):
        self.assertIsNone(re.search(r"`/[a-z]", self.m.HELP_TEXT),
                          "commands inside backticks render as <code> (not tappable)")
        for hyphen in ("/restart-agent", "/active-memory", "/dry-run"):
            self.assertNotIn(hyphen, self.m.HELP_TEXT)
        html = self.bot._markdown_to_html(self.m.HELP_TEXT)
        self.assertNotIn("<i>", html)


# ---------------------------------------------------------------------------
# 6. Message during a running turn
# ---------------------------------------------------------------------------

class TurnMessageBinding(_Base):
    def test_busy_message_does_not_hijack_running_turn(self):
        ctx = self.bot._ctx
        ctx.user_msg_id = 7
        ctx.last_reaction = "🤔"
        ctx.turn_owner = -1  # another thread owns the turn
        ctx.runner = MagicMock(running=True)
        ctx.runner.send_btw.return_value = False
        with patch.object(self.bot, "set_reaction") as sr, \
                patch.object(self.bot, "_spawn_background_review") as review:
            self.bot._handle_text("outra coisa", user_msg_id=42)
        self.assertEqual(ctx.user_msg_id, 7)
        self.assertEqual(ctx.last_reaction, "🤔")
        sr.assert_not_called()
        review.assert_not_called()
        self.assertEqual(ctx.pending, [("outra coisa", 42)])

    def test_queued_item_replies_to_its_own_message(self):
        ctx = self.bot._ctx
        ctx.pending.extend([("a", 41), ("b", 42), "btw sem id"])
        seen = []
        with patch.object(self.bot, "set_reaction", return_value=True), \
                patch.object(self.bot, "_run_claude_prompt_owned",
                             side_effect=lambda p, *a, **k: seen.append((p, ctx.user_msg_id))):
            self.bot._process_pending()
        self.assertEqual(seen, [("a\n\nb\n\nbtw sem id", 42)])

    def test_winning_message_binds_and_reacts(self):
        ctx = self.bot._ctx
        with patch.object(self.bot, "set_reaction", return_value=True) as sr, \
                patch.object(self.bot, "_run_claude_prompt_owned") as owned, \
                patch.object(self.bot, "_spawn_background_review"):
            self.bot._handle_text("oi", user_msg_id=99)
        owned.assert_called_once()
        sr.assert_called_with(99, "👀")
        self.assertEqual(ctx.user_msg_id, 99)
        self.assertEqual(ctx.last_reaction, "👀")


# ---------------------------------------------------------------------------
# 7. callback_data 64-byte limit
# ---------------------------------------------------------------------------

class CallbackDataLimit(_Base):
    LONG = "agente-" + "x" * 53  # 60 chars

    def test_short_payload_passes_through(self):
        self.assertEqual(self.m._cb_data("agent:main"), "agent:main")

    def test_long_payload_mapped_and_resolved(self):
        full = f"topic_invite:bind:{FORUM}:12345:{self.LONG}"
        self.assertGreater(len(full.encode()), 64)
        short = self.m._cb_data(full)
        self.assertLessEqual(len(short.encode()), 64)
        self.assertEqual(self.m._resolve_cb_data(short), full)
        self.assertEqual(self.m._cb_data(full), short)  # stable on re-render

    def test_utf8_bytes_counted(self):
        full = "skill:run:" + "ç" * 30  # 40 chars, 70 bytes
        self.assertTrue(self.m._cb_data(full).startswith(self.m.CALLBACK_REF_PREFIX))

    def test_agent_keyboard_with_long_agent(self):
        _write_agent(self.f.vault, self.LONG)
        self.bot.cmd_agent_keyboard()
        markup = _markup([d for meth, d in self.f.tg_calls if meth == "sendMessage"][-1])
        datas = [b["callback_data"] for row in markup["inline_keyboard"] for b in row]
        self.assertTrue(all(len(x.encode()) <= 64 for x in datas), datas)

    def test_callback_handler_resolves_ref(self):
        short = self.m._cb_data(f"agent:{self.LONG}")
        with patch.object(self.bot, "cmd_agent_switch") as sw:
            self.bot._handle_callback({"id": "c1", "data": short, "message": {}})
        sw.assert_called_once_with(self.LONG)

    def test_unknown_ref_reports_expired(self):
        self.bot._handle_callback({"id": "c2", "data": "cbref:deadbeef0000", "message": {}})
        answers = [d for meth, d in self.f.tg_calls if meth == "answerCallbackQuery"]
        self.assertIn("expirado", answers[-1]["text"])

    def test_refs_survive_restart(self):
        short = self.m._cb_data(f"invite:bind:{GUEST}:{self.LONG}")
        self.m._callback_refs.clear()
        self.m._callback_refs_loaded = False
        self.assertEqual(self.m._resolve_cb_data(short), f"invite:bind:{GUEST}:{self.LONG}")


# ---------------------------------------------------------------------------
# 8. Small UX
# ---------------------------------------------------------------------------

class SmallUx(_Base):
    def test_startup_ping_is_silent(self):
        self.bot._notify_startup()
        pings = [d for meth, d in self.f.tg_calls if meth == "sendMessage"]
        self.assertTrue(pings)
        self.assertTrue(all(d.get("disable_notification") for d in pings))

    def test_command_for_other_bot_ignored(self):
        self.bot._bot_username = "MyBot"
        with patch.object(self.bot, "cmd_status") as st:
            self.bot._handle_text("/status@otherbot")
            st.assert_not_called()
            self.bot._handle_text("/status@mybot")
            st.assert_called_once()
        self.assertFalse(any("desconhecido" in t for t in self.sent_texts()))

    def test_unknown_username_strips_suffix(self):
        self.bot._bot_username = None
        with patch.object(self.bot, "cmd_status") as st:
            self.bot._handle_text("/status@whatever")
        st.assert_called_once()

    def test_fetch_bot_identity(self):
        self.bot.tg_request = lambda method, data=None, timeout=15: (
            {"ok": True, "result": {"username": "ClaudeBot"}} if method == "getMe" else {"ok": True})
        self.bot._fetch_bot_identity()
        self.assertEqual(self.bot._bot_username, "ClaudeBot")

    def test_unauthorized_callback_answered(self):
        self.bot._process_update({"callback_query": {
            "id": "cb9", "data": "model:opus",
            "message": {"chat": {"id": -100999}, "message_id": 3}}})
        answers = [d for meth, d in self.f.tg_calls if meth == "answerCallbackQuery"]
        self.assertEqual(answers, [{"callback_query_id": "cb9", "text": "Não autorizado"}])


if __name__ == "__main__":
    unittest.main()
