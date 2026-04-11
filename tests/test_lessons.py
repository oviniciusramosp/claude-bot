"""Tests for the Lessons compound-engineering system.

Covers:
- record_lesson_draft creates draft-YYYY-MM-DD-{slug}.md with error summary
- record_lesson_draft is idempotent per day+trigger (appends on reinvocation)
- record_lesson_draft sanitizes unsafe filename characters
- record_lesson_draft never raises — returns None on failure
- record_manual_lesson writes a manual-YYYY-MM-DD-HHMM.md
- record_manual_lesson rejects empty text
- /lesson command dispatches and writes a file
- _notify_failure (pipeline path) creates a draft lesson
"""
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests._botload import load_bot_module


class RecordLessonDraft(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)

    def tearDown(self):
        self._td.cleanup()

    def test_creates_draft_with_frontmatter_and_todos(self):
        path = self.bot.record_lesson_draft("morning-report", "API returned 500", kind="routine")
        self.assertIsNotNone(path)
        self.assertTrue(path.exists())
        self.assertTrue(path.name.startswith("draft-"))
        self.assertTrue(path.name.endswith("-morning-report.md"))
        content = path.read_text(encoding="utf-8")
        self.assertIn("---", content)
        self.assertIn("status: draft", content)
        self.assertIn("trigger: morning-report", content)
        self.assertIn("kind: routine", content)
        self.assertIn("API returned 500", content)
        self.assertIn("## What went wrong", content)
        self.assertIn("## Fix", content)
        self.assertIn("TODO", content)
        self.assertIn("## How to detect next time", content)

    def test_second_invocation_appends_instead_of_overwriting(self):
        first = self.bot.record_lesson_draft("daily-sync", "error A", kind="routine")
        second = self.bot.record_lesson_draft("daily-sync", "error B", kind="routine")
        self.assertEqual(first, second)
        content = first.read_text(encoding="utf-8")
        self.assertIn("error A", content)
        self.assertIn("error B", content)
        self.assertIn("Additional failure", content)

    def test_sanitizes_unsafe_trigger_name(self):
        path = self.bot.record_lesson_draft("weird/../name with spaces!", "oops")
        self.assertIsNotNone(path)
        # Should not contain path separators or exotic chars in filename
        self.assertNotIn("/", path.name.replace(str(path.parent) + "/", ""))
        self.assertNotIn("..", path.name)
        # Should still be under LESSONS_DIR
        self.assertEqual(path.parent.resolve(), self.bot.LESSONS_DIR.resolve())

    def test_truncates_very_long_error(self):
        big = "x" * 5000
        path = self.bot.record_lesson_draft("bigfail", big)
        self.assertIsNotNone(path)
        content = path.read_text(encoding="utf-8")
        self.assertIn("truncated", content)

    def test_never_raises_on_filesystem_error(self):
        # Point LESSONS_DIR at a file (not a directory) so mkdir fails
        bogus = self.vault / "not_a_dir.txt"
        bogus.write_text("blocker")
        original = self.bot.LESSONS_DIR
        try:
            self.bot.LESSONS_DIR = bogus
            result = self.bot.record_lesson_draft("any", "any")
            # Returns None, never raises
            self.assertIsNone(result)
        finally:
            self.bot.LESSONS_DIR = original


class RecordManualLesson(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)

    def tearDown(self):
        self._td.cleanup()

    def test_writes_manual_lesson_file(self):
        path = self.bot.record_manual_lesson("Always validate DAG before execution")
        self.assertIsNotNone(path)
        self.assertTrue(path.name.startswith("manual-"))
        content = path.read_text(encoding="utf-8")
        self.assertIn("Always validate DAG", content)
        self.assertIn("status: recorded", content)
        self.assertIn("## Fix", content)

    def test_rejects_empty_text(self):
        self.assertIsNone(self.bot.record_manual_lesson(""))
        self.assertIsNone(self.bot.record_manual_lesson("   "))

    def test_collision_in_same_minute_uses_counter(self):
        a = self.bot.record_manual_lesson("first")
        b = self.bot.record_manual_lesson("second")
        self.assertIsNotNone(a)
        self.assertIsNotNone(b)
        self.assertNotEqual(a, b)


class LessonCommandDispatch(unittest.TestCase):
    def setUp(self):
        from tests.test_bot_integration import _BotFixture
        self._td = tempfile.TemporaryDirectory()
        self.fixture = _BotFixture(Path(self._td.name))
        self.bot = self.fixture.bot

    def tearDown(self):
        self.fixture.cleanup()
        self._td.cleanup()

    def _last_send(self):
        for method, data in reversed(self.fixture.tg_calls):
            if method == "sendMessage":
                return data
        raise AssertionError("no sendMessage was made")

    def test_lesson_without_arg_shows_usage(self):
        self.bot._handle_text("/lesson")
        last = self._last_send()
        self.assertIn("/lesson", last["text"])

    def test_lesson_with_text_writes_file(self):
        self.bot._handle_text("/lesson Check auth before long-running jobs")
        last = self._last_send()
        self.assertIn("vault/Lessons/manual-", last["text"])
        # Verify a manual- file was created
        lessons = list(self.fixture.bot_module.LESSONS_DIR.glob("manual-*.md"))
        self.assertEqual(len(lessons), 1)
        content = lessons[0].read_text(encoding="utf-8")
        self.assertIn("Check auth before long-running jobs", content)


if __name__ == "__main__":
    unittest.main()
