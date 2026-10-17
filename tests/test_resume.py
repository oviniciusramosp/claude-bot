"""Tests for /resume (v3.77): continue a Claude Code session started elsewhere
(the Claude desktop app or a terminal) from Telegram.

Covers the pure discovery helpers (cwd encoding, model-alias mapping, title
cleaning, relative time, Claude.app index scan with alive/archived filtering and
recency sort) and the command/callback path (picker build, dedupe vs the bot's
own sessions, adoption into a new session, guard rails).

No network and no real Claude CLI — the Claude.app index + transcripts are
fixture files under a tmp HOME; consolidation is patched to a no-op.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._botload import load_bot_module
from tests.test_bot_integration import _BotFixture


def _write_claude_app_session(bot, *, sid, cwd, title, model="claude-opus-5",
                              last_activity_ms=None, archived=False,
                              with_transcript=True, ws="ws1", grp="grp1"):
    """Create a Claude.app index entry (+ optional live transcript) for `sid`."""
    if last_activity_ms is None:
        last_activity_ms = int(time.time() * 1000)
    idx_dir = bot.CLAUDE_APP_SESSIONS_DIR / ws / grp
    idx_dir.mkdir(parents=True, exist_ok=True)
    (idx_dir / f"local_{sid}.json").write_text(json.dumps({
        "cliSessionId": sid,
        "cwd": cwd,
        "title": title,
        "model": model,
        "lastActivityAt": last_activity_ms,
        "isArchived": archived,
    }), encoding="utf-8")
    if with_transcript:
        tdir = bot.CLAUDE_PROJECTS_DIR / bot._encode_project_dir(cwd)
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / f"{sid}.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")


class ResumeHelpers(unittest.TestCase):
    """Pure module-level helpers — no bot instance needed."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)

    def tearDown(self):
        self._td.cleanup()

    def test_encode_project_dir_matches_claude_code(self):
        self.assertEqual(
            self.bot._encode_project_dir("/Users/x/claude-bot"),
            "-Users-x-claude-bot",
        )
        # spaces, dots and underscores all collapse to '-'
        self.assertEqual(
            self.bot._encode_project_dir("/Volumes/SSD_VR4/OC Mac Mini/B"),
            "-Volumes-SSD-VR4-OC-Mac-Mini-B",
        )
        self.assertEqual(
            self.bot._encode_project_dir("/Users/x/claude-bot/vault/main"),
            "-Users-x-claude-bot-vault-main",
        )

    def test_resume_model_alias_maps_captured_ids(self):
        f = self.bot._resume_model_alias
        self.assertEqual(f("claude-opus-5[1m]"), "opus")   # strips [1m]
        self.assertEqual(f("claude-sonnet-4-6"), "sonnet")
        self.assertEqual(f("claude-haiku-4-5"), "haiku")
        self.assertEqual(f("opus"), "opus")                  # already an alias
        self.assertEqual(f("glm-4.7"), "glm-4.7")            # provider preserved
        self.assertEqual(f("gpt-5"), "gpt-5")
        self.assertIsNone(f(None))
        self.assertIsNone(f("something-weird"))

    def test_clean_title_strips_markdown_and_newlines(self):
        self.assertEqual(self.bot._clean_title("Fix `bot` *thing*\nnow"), "Fix bot thing now")
        self.assertEqual(self.bot._clean_title(""), "(sem título)")
        self.assertEqual(self.bot._clean_title(None), "(sem título)")

    def test_relative_time_buckets(self):
        f = self.bot._resume_relative_time
        now = time.time()
        self.assertEqual(f(now - 10), "agora")
        self.assertEqual(f(now - 300), "há 5min")
        self.assertEqual(f(now - 3 * 3600), "há 3h")
        self.assertEqual(f(now - 26 * 3600), "ontem")
        self.assertEqual(f(now - 5 * 86400), "há 5d")
        self.assertEqual(f(0), "?")

    def test_short_cwd_compacts_home_and_tail(self):
        home = str(Path.home())
        self.assertEqual(self.bot._short_cwd(f"{home}/claude-bot"), "~/claude-bot")
        self.assertEqual(
            self.bot._short_cwd(f"{home}/claude-bot/vault/main"), ".../vault/main")

    # -- _scan_claude_app_sessions --

    def test_scan_returns_alive_nonarchived_sorted(self):
        _write_claude_app_session(
            self.bot, sid="aaaa1111-aaaa-1111-aaaa-111111111111",
            cwd="/proj/old", title="Old one", last_activity_ms=1000)
        _write_claude_app_session(
            self.bot, sid="bbbb2222-bbbb-2222-bbbb-222222222222",
            cwd="/proj/new", title="New one", last_activity_ms=9000)
        out = self.bot._scan_claude_app_sessions()
        self.assertEqual([e["title"] for e in out], ["New one", "Old one"])  # recency
        self.assertEqual(out[0]["origin"], "claude.app")
        self.assertEqual(out[0]["last_activity"], 9.0)  # ms → s

    def test_scan_excludes_archived(self):
        _write_claude_app_session(
            self.bot, sid="cccc3333-cccc-3333-cccc-333333333333",
            cwd="/proj/arch", title="Archived", archived=True)
        self.assertEqual(self.bot._scan_claude_app_sessions(), [])

    def test_scan_excludes_pruned_transcript(self):
        _write_claude_app_session(
            self.bot, sid="dddd4444-dddd-4444-dddd-444444444444",
            cwd="/proj/pruned", title="Pruned", with_transcript=False)
        self.assertEqual(self.bot._scan_claude_app_sessions(), [])

    def test_scan_fail_open_when_dir_missing(self):
        # Fresh tmp home: no Claude.app dir at all → [] (never raises).
        self.assertEqual(self.bot._scan_claude_app_sessions(), [])


class ResumeCommand(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot
        self.mod = self.fixture.bot_module
        # Never spawn the consolidator subprocess in tests.
        self._cons = patch.object(
            type(self.bot), "_consolidate_session_background", lambda self, s=None: None)
        self._cons.start()

    def tearDown(self):
        self._cons.stop()
        self.fixture.cleanup()
        self._td.cleanup()

    def _last_send(self) -> dict:
        for method, data in reversed(self.fixture.tg_calls):
            if method == "sendMessage":
                return data
        raise AssertionError("no sendMessage was made")

    def test_resume_no_candidates(self):
        self.bot._handle_text("/resume")
        self.assertIn("Nenhuma sessão recente", self._last_send()["text"])

    def test_resume_lists_claude_app_session(self):
        real_cwd = str(self.fixture.vault / "main")  # exists via ensure_agent_layout
        _write_claude_app_session(
            self.mod, sid="eeee5555-eeee-5555-eeee-555555555555",
            cwd=real_cwd, title="Telegram session continuation")
        self.bot.cmd_resume()
        last = self._last_send()
        self.assertIn("Retomar conversa", last["text"])
        kb = last["reply_markup"]["inline_keyboard"]
        self.assertEqual(len(kb), 1)
        self.assertIn("Telegram session continuation", kb[0][0]["text"])
        self.assertTrue(kb[0][0]["callback_data"].startswith("resume:"))

    def test_resume_dedupes_and_excludes_active(self):
        # Bot session A (inactive, resumable) + B (active, excluded).
        a = self.bot.sessions.create("sess-A", agent="main")
        a.session_id = "shared-sid-123"
        b = self.bot.sessions.create("sess-B", agent="main")  # becomes active
        self.bot.sessions.save()
        self.assertEqual(self.bot.sessions.active_session, "sess-B")
        # A Claude.app entry with the SAME session_id must be deduped away.
        _write_claude_app_session(
            self.mod, sid="shared-sid-123", cwd=str(self.fixture.vault / "main"),
            title="dup")
        cands = self.bot._build_resume_candidates()
        ids = [c["session_id"] for c in cands]
        self.assertEqual(ids.count("shared-sid-123"), 1)        # deduped
        self.assertTrue(all(c["title"] != "sess-B" for c in cands))  # active excluded
        self.assertTrue(any(c["origin"] == "bot" for c in cands))

    def test_pick_adopts_into_new_session(self):
        real_cwd = str(self.fixture.vault / "main")
        sid = "ffff6666-ffff-6666-ffff-666666666666"
        _write_claude_app_session(
            self.mod, sid=sid, cwd=real_cwd, title="Fix 401",
            model="claude-sonnet-4-6")
        self.bot.cmd_resume()
        token = next(iter(self.bot._resume_candidates))
        before = set(self.bot.sessions.sessions)
        self.bot._handle_resume_callback({"id": "cb"}, f"{token}:0")
        new_names = set(self.bot.sessions.sessions) - before
        self.assertEqual(len(new_names), 1)
        new = self.bot.sessions.sessions[next(iter(new_names))]
        self.assertEqual(new.session_id, sid)
        self.assertEqual(new.workspace, real_cwd)
        self.assertEqual(new.model, "sonnet")  # captured id → alias
        self.assertEqual(self.bot.sessions.active_session, new.name)
        self.assertIn("Sessão retomada", self._last_send()["text"])

    def test_pick_rejects_missing_directory(self):
        c = {"session_id": "x", "cwd": "/no/such/dir/ever", "title": "t",
             "model": "opus", "origin": "claude.app"}
        self.bot._adopt_resumed_session(c)
        self.assertIn("não existe mais", self._last_send()["text"])

    def test_expired_token_callback_is_graceful(self):
        # No such token → friendly "expired" ack, no crash, no new session.
        before = set(self.bot.sessions.sessions)
        self.bot._handle_resume_callback({"id": "cb"}, "deadbeef:0")
        self.assertEqual(set(self.bot.sessions.sessions), before)

    def test_secondary_chat_blocked(self):
        with patch.object(type(self.bot), "_block_if_secondary", lambda self, a: True):
            self.bot.cmd_resume()
        self.assertEqual(self.bot._resume_candidates, {})  # never built a picker

    def test_resume_registered_in_dispatch(self):
        self.bot._handle_text("/resume")
        # Reaches cmd_resume (no "unknown command" error).
        self.assertNotIn("desconhecido", self._last_send()["text"])
