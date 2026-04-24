"""Contract tests — protect persisted formats and config interfaces.

These tests guard the interfaces that the bot must keep stable across versions
so user data isn't broken by refactors.
"""
import json
import re
import subprocess
import unittest
from pathlib import Path

from tests._botload import load_bot_module

REPO_ROOT = Path(__file__).resolve().parent.parent
ROUTINES_DIR = REPO_ROOT / "vault" / "Routines"


class RealRoutinesParse(unittest.TestCase):
    """Every committed routine in vault/Routines/*.md must parse cleanly."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_all_committed_routines_parse(self):
        if not ROUTINES_DIR.is_dir():
            self.skipTest("vault/Routines/ not present in this checkout")
        files = list(ROUTINES_DIR.glob("*.md"))
        self.assertGreater(len(files), 0, "no routine files found")
        for md in files:
            with self.subTest(routine=md.name):
                fm, body = self.bot.get_frontmatter_and_body(md)
                if str(fm.get("type", "")).lower() == "index":
                    continue  # Routines.md is the hub
                # Each routine must have these fields
                for required in ("title", "type", "schedule", "model", "enabled"):
                    self.assertIn(
                        required, fm,
                        f"{md.name} missing required field `{required}`"
                    )
                # schedule must be a dict with non-empty `times`
                schedule = fm.get("schedule")
                self.assertIsInstance(schedule, dict, f"{md.name} schedule must be dict")
                times = schedule.get("times")
                self.assertIsInstance(times, list, f"{md.name} times must be list")
                self.assertGreater(len(times), 0, f"{md.name} times empty")
                # Each time must look like HH:MM
                for t in times:
                    self.assertRegex(
                        str(t), r"^\d{2}:\d{2}$",
                        f"{md.name} time {t!r} not HH:MM",
                    )

    def test_pipeline_routines_have_pipeline_block(self):
        if not ROUTINES_DIR.is_dir():
            self.skipTest("vault/Routines/ not present")
        for md in ROUTINES_DIR.glob("*.md"):
            fm, body = self.bot.get_frontmatter_and_body(md)
            if str(fm.get("type", "")).lower() == "pipeline":
                with self.subTest(pipeline=md.name):
                    steps = self.bot.parse_pipeline_body(body)
                    self.assertGreater(
                        len(steps), 0,
                        f"{md.name} declares type=pipeline but has no ```pipeline block",
                    )
                    # Every step must have id and either prompt or prompt_file
                    for s in steps:
                        self.assertIn("id", s, f"{md.name} step missing id")


class SessionsJsonRoundTrip(unittest.TestCase):
    """sessions.json format must survive a save→load cycle."""

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_round_trip_preserves_session(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            # Use bot's load_bot_module fresh so DATA_DIR points at td
            home = Path(td) / "home"
            home.mkdir()
            bot = load_bot_module(tmp_home=home)
            sm = bot.SessionManager()
            s = sm.create("contract-session")
            s.message_count = 17
            s.total_turns = 33
            s.session_id = "abc-123"
            sm.save()

            sm2 = bot.SessionManager()
            self.assertIn("contract-session", sm2.sessions)
            loaded = sm2.sessions["contract-session"]
            self.assertEqual(loaded.message_count, 17)
            self.assertEqual(loaded.total_turns, 33)
            self.assertEqual(loaded.session_id, "abc-123")

    def test_session_dataclass_has_stable_fields(self):
        # Catches unintentional removal of a sessions.json field
        expected = {
            "name", "session_id", "model", "workspace", "agent",
            "created_at", "message_count", "total_turns",
        }
        actual = {f.name for f in self.bot.Session.__dataclass_fields__.values()}
        # New fields are OK; removing is a breaking change
        missing = expected - actual
        self.assertEqual(missing, set(),
                         f"Session lost stable fields: {missing}. "
                         f"This breaks ~/.claude-bot/sessions.json compatibility.")


class PlistPlaceholders(unittest.TestCase):
    """The launchd .plist files must contain placeholders that claude-bot.sh substitutes."""

    @classmethod
    def setUpClass(cls):
        cls.PLIST_FILES = sorted(REPO_ROOT.glob("*.plist"))

    def test_plists_contain_required_placeholders(self):
        for p in self.PLIST_FILES:
            if not p.is_file():
                self.skipTest(f"{p.name} not present")
            text = p.read_text()
            with self.subTest(plist=p.name):
                self.assertIn("__HOME__", text,
                              f"{p.name} missing __HOME__ placeholder")
                self.assertIn("__SCRIPT_DIR__", text,
                              f"{p.name} missing __SCRIPT_DIR__ placeholder")

    def test_plists_are_valid_xml(self):
        # plutil ships with macOS — use it to validate
        for p in self.PLIST_FILES:
            if not p.is_file():
                continue
            with self.subTest(plist=p.name):
                # plutil dislikes the placeholders directly, so substitute first
                text = p.read_text()
                text = text.replace("__HOME__", "/Users/test")
                text = text.replace("__SCRIPT_DIR__", "/Users/test/claude-bot")
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".plist", delete=False) as tmp:
                    tmp.write(text)
                    tmp_path = tmp.name
                try:
                    result = subprocess.run(
                        ["plutil", "-lint", tmp_path],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(
                        result.returncode, 0,
                        f"{p.name} not valid plist: {result.stdout}\n{result.stderr}"
                    )
                finally:
                    Path(tmp_path).unlink(missing_ok=True)


class ModelProvidersRegistry(unittest.TestCase):
    """MODEL_PROVIDERS is the contract between Python and Swift sides.

    The Swift ModelCatalog must stay in sync with this dict. Adding or
    removing a model requires bumping both sides — this test guards against
    accidental drift.
    """

    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_model_providers_registry_complete(self):
        expected = {
            "sonnet": "anthropic",
            "opus": "anthropic",
            "haiku": "anthropic",
            "glm-5.1": "zai",
            "glm-4.7": "zai",
            "glm-4.5-air": "zai",
            "gpt-5": "openai",
            "gpt-5-codex": "openai",
        }
        self.assertEqual(
            self.bot.MODEL_PROVIDERS, expected,
            "MODEL_PROVIDERS drifted — update Swift ModelCatalog to match.",
        )

    def test_default_model_is_sonnet(self):
        self.assertEqual(self.bot.DEFAULT_MODEL, "sonnet")

    def test_model_provider_helper_known_and_unknown(self):
        self.assertEqual(self.bot.model_provider("sonnet"), "anthropic")
        self.assertEqual(self.bot.model_provider("glm-4.7"), "zai")
        # Unknown glm-* variant falls back to zai via prefix rule
        self.assertEqual(self.bot.model_provider("glm-future-99"), "zai")
        # Unknown non-glm falls back to anthropic
        self.assertEqual(self.bot.model_provider("mystery"), "anthropic")


class BotVersionFormat(unittest.TestCase):
    """BOT_VERSION must be a valid SemVer string and match Info.plist."""

    def test_version_semver_format(self):
        bot = load_bot_module()
        self.assertRegex(
            bot.BOT_VERSION,
            r"^\d+\.\d+\.\d+$",
            f"BOT_VERSION {bot.BOT_VERSION} is not MAJOR.MINOR.PATCH",
        )

    def test_version_matches_info_plist(self):
        bot = load_bot_module()
        info_plist = REPO_ROOT / "ClaudeBotManager" / "Sources" / "App" / "Info.plist"
        if not info_plist.is_file():
            self.skipTest("Info.plist not present")
        text = info_plist.read_text()
        # Look for CFBundleShortVersionString
        match = re.search(
            r"<key>CFBundleShortVersionString</key>\s*<string>([^<]+)</string>",
            text,
        )
        self.assertIsNotNone(match, "CFBundleShortVersionString not found in Info.plist")
        plist_version = match.group(1).strip()
        self.assertEqual(
            plist_version, bot.BOT_VERSION,
            f"BOT_VERSION ({bot.BOT_VERSION}) and Info.plist "
            f"CFBundleShortVersionString ({plist_version}) must match. "
            "Per CLAUDE.md, both files must be bumped together.",
        )


if __name__ == "__main__":
    unittest.main()
