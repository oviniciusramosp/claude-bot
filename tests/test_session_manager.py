"""Unit tests for Session, SessionManager, _make_session_name."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from tests._botload import load_bot_module


class SessionManagerCRUD(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.home = Path(self._td.name) / "home"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home)

    def tearDown(self):
        self._td.cleanup()

    def test_create_persists(self):
        sm = self.bot.SessionManager()
        s = sm.create("alpha")
        self.assertEqual(s.name, "alpha")
        self.assertEqual(sm.active_session, "alpha")
        self.assertTrue(self.bot.SESSIONS_FILE.exists())
        # Reload from disk → should round-trip
        sm2 = self.bot.SessionManager()
        self.assertIn("alpha", sm2.sessions)
        self.assertEqual(sm2.active_session, "alpha")

    def test_switch(self):
        sm = self.bot.SessionManager()
        sm.create("a")
        sm.create("b")
        self.assertEqual(sm.active_session, "b")
        result = sm.switch("a")
        self.assertIsNotNone(result)
        self.assertEqual(sm.active_session, "a")

    def test_switch_unknown_returns_none(self):
        sm = self.bot.SessionManager()
        sm.create("a")
        self.assertIsNone(sm.switch("nope"))
        self.assertEqual(sm.active_session, "a")

    def test_delete(self):
        sm = self.bot.SessionManager()
        sm.create("a")
        sm.create("b")
        self.assertTrue(sm.delete("a"))
        self.assertNotIn("a", sm.sessions)
        # Active still 'b'
        self.assertEqual(sm.active_session, "b")

    def test_delete_active_picks_new_active(self):
        sm = self.bot.SessionManager()
        sm.create("a")
        sm.create("b")
        # active is 'b'
        self.assertTrue(sm.delete("b"))
        self.assertEqual(sm.active_session, "a")

    def test_delete_unknown_returns_false(self):
        sm = self.bot.SessionManager()
        self.assertFalse(sm.delete("missing"))

    def test_list(self):
        sm = self.bot.SessionManager()
        sm.create("a")
        sm.create("b")
        names = sorted(s.name for s in sm.list())
        self.assertEqual(names, ["a", "b"])

    def test_get_active_none_when_empty(self):
        sm = self.bot.SessionManager()
        self.assertIsNone(sm.get_active())

    def test_ensure_active_creates_when_empty(self):
        sm = self.bot.SessionManager()
        s = sm.ensure_active()
        self.assertIsNotNone(s)
        self.assertIn(s.name, sm.sessions)

    def test_unknown_field_in_json_does_not_crash(self):
        # Bot must tolerate sessions.json from older versions with extra fields.
        payload = {
            "sessions": {
                "old": {
                    "name": "old",
                    "session_id": "abc",
                    "model": "sonnet",
                    "workspace": "/tmp",
                    "agent": None,
                    "created_at": time.time(),
                    "message_count": 5,
                    "total_turns": 10,
                    "deprecated_field": "should be ignored",
                }
            },
            "active_session": "old",
            "cumulative_turns": 7,
        }
        self.bot.SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.bot.SESSIONS_FILE.write_text(json.dumps(payload))
        sm = self.bot.SessionManager()
        self.assertIn("old", sm.sessions)
        self.assertEqual(sm.sessions["old"].message_count, 5)
        self.assertEqual(sm.cumulative_turns, 7)

    def test_corrupt_json_does_not_crash(self):
        self.bot.SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.bot.SESSIONS_FILE.write_text("not json {{{")
        sm = self.bot.SessionManager()
        # Should start empty rather than raise
        self.assertEqual(sm.sessions, {})

    def test_evict_old_sessions(self):
        # Manually craft a sessions.json with an ancient session
        ancient = time.time() - (self.bot.SESSION_MAX_AGE_DAYS + 1) * 86400
        recent = time.time()
        payload = {
            "sessions": {
                "old": {
                    "name": "old",
                    "session_id": None,
                    "model": "sonnet",
                    "workspace": "/tmp",
                    "agent": None,
                    "created_at": ancient,
                    "message_count": 0,
                    "total_turns": 0,
                },
                "new": {
                    "name": "new",
                    "session_id": None,
                    "model": "sonnet",
                    "workspace": "/tmp",
                    "agent": None,
                    "created_at": recent,
                    "message_count": 0,
                    "total_turns": 0,
                },
            },
            "active_session": "old",
            "cumulative_turns": 0,
        }
        self.bot.SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        self.bot.SESSIONS_FILE.write_text(json.dumps(payload))
        sm = self.bot.SessionManager()
        self.assertNotIn("old", sm.sessions)
        self.assertIn("new", sm.sessions)
        # Active should be reassigned to surviving session
        self.assertEqual(sm.active_session, "new")

    def test_save_uses_atomic_replace(self):
        sm = self.bot.SessionManager()
        sm.create("a")
        # The .tmp file should not be left behind
        tmp = self.bot.SESSIONS_FILE.with_suffix(".tmp")
        self.assertFalse(tmp.exists())
        self.assertTrue(self.bot.SESSIONS_FILE.exists())

    def test_clone_copies_metadata_and_switches(self):
        sm = self.bot.SessionManager()
        src = sm.create("branch-main")
        src.session_id = "claude-abc-123"
        src.model = "opus"
        src.message_count = 7
        src.total_turns = 9
        sm.save()
        clone = sm.clone("branch-main", "branch-exp")
        self.assertIsNotNone(clone)
        # Shares Claude session to continue the thread
        self.assertEqual(clone.session_id, "claude-abc-123")
        self.assertEqual(clone.model, "opus")
        self.assertEqual(clone.message_count, 7)
        # Fresh turn counter for this branch
        self.assertEqual(clone.total_turns, 0)
        # Clone becomes active session
        self.assertEqual(sm.active_session, "branch-exp")
        # Clone persists
        sm2 = self.bot.SessionManager()
        self.assertIn("branch-exp", sm2.sessions)
        self.assertEqual(sm2.sessions["branch-exp"].session_id, "claude-abc-123")

    def test_clone_isolation_editing_clone_does_not_affect_source(self):
        sm = self.bot.SessionManager()
        sm.create("src")
        sm.sessions["src"].model = "sonnet"
        sm.clone("src", "dst")
        sm.sessions["dst"].model = "haiku"
        sm.sessions["dst"].total_turns = 42
        sm.save()
        # Source must stay untouched
        self.assertEqual(sm.sessions["src"].model, "sonnet")
        self.assertEqual(sm.sessions["src"].total_turns, 0)

    def test_clone_missing_source_returns_none(self):
        sm = self.bot.SessionManager()
        self.assertIsNone(sm.clone("missing", "dst"))

    def test_clone_existing_dest_returns_none(self):
        sm = self.bot.SessionManager()
        sm.create("a")
        sm.create("b")
        self.assertIsNone(sm.clone("a", "b"))


class MakeSessionName(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_name_for_main_agent(self):
        name = self.bot._make_session_name(None, {})
        # YYYY-MM-DD-HH-MM-main-1
        parts = name.split("-")
        self.assertEqual(parts[-2], "main")
        self.assertEqual(parts[-1], "1")

    def test_name_for_specific_agent(self):
        name = self.bot._make_session_name("crypto", {})
        self.assertIn("-crypto-1", name)

    def test_increments_when_collision(self):
        # Build the prefix using the same time format the bot uses
        prefix = time.strftime("%Y-%m-%d-%H-%M") + "-main-"
        existing = {f"{prefix}1": object(), f"{prefix}2": object()}
        name = self.bot._make_session_name(None, existing)
        # Suffix should be 3
        self.assertEqual(name, f"{prefix}3")


if __name__ == "__main__":
    unittest.main()
