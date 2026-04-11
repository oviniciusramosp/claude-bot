"""Tests for scripts/journal-audit.py — frontmatter validation, repair, audit report."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "journal-audit.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("journal_audit_under_test", str(SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["journal_audit_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class FrontmatterValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ja = _load_script()

    def test_valid_frontmatter(self):
        text = (
            "---\n"
            'title: "Journal 2026-04-10"\n'
            "type: journal\n"
            "---\n"
            "## 08:00 — Started day\n"
        )
        ok, issues = self.ja.validate_frontmatter(text)
        self.assertTrue(ok, f"Expected valid, got issues: {issues}")

    def test_missing_opening_dashes(self):
        text = "title: x\ntype: journal\n---\nbody"
        ok, issues = self.ja.validate_frontmatter(text)
        self.assertFalse(ok)
        self.assertTrue(any("opening" in i for i in issues))

    def test_missing_closing_dashes_with_markdown_first(self):
        text = "---\ntitle: x\ntype: journal\n# heading without closing\nbody"
        ok, issues = self.ja.validate_frontmatter(text)
        self.assertFalse(ok)

    def test_missing_required_field_type(self):
        text = '---\ntitle: "x"\n---\nbody'
        ok, issues = self.ja.validate_frontmatter(text)
        self.assertFalse(ok)
        self.assertTrue(any("type" in i for i in issues))


class FrontmatterRepair(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ja = _load_script()

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def test_fix_no_frontmatter_at_all(self):
        p = self.tmpdir / "j.md"
        p.write_text("## 08:00 — start\n- did stuff\n")
        result = self.ja.fix_frontmatter(p, "main", "2026-04-10")
        self.assertIn("repaired", result)
        ok, issues = self.ja.validate_frontmatter(p.read_text())
        self.assertTrue(ok, f"after repair, still invalid: {issues}")

    def test_fix_unclosed_frontmatter(self):
        p = self.tmpdir / "j.md"
        p.write_text(
            "---\n"
            "title: x\n"
            "type: journal\n"
            "## 08:00 — entry\nbody\n"
        )
        self.ja.fix_frontmatter(p, "main", "2026-04-10")
        ok, issues = self.ja.validate_frontmatter(p.read_text())
        self.assertTrue(ok, f"after repair, still invalid: {issues}")

    def test_fix_preserves_existing_body(self):
        p = self.tmpdir / "j.md"
        p.write_text(
            "## 08:00 — Important note\n"
            "- bullet point we don't want to lose\n"
        )
        self.ja.fix_frontmatter(p, "main", "2026-04-10")
        new = p.read_text()
        self.assertIn("Important note", new)
        self.assertIn("bullet point we don't want to lose", new)

    def test_create_journal_file_from_scratch(self):
        p = self.tmpdir / "fresh.md"
        self.ja.create_journal_file(p, "main", "2026-04-10")
        self.assertTrue(p.exists())
        ok, issues = self.ja.validate_frontmatter(p.read_text())
        self.assertTrue(ok, f"created file invalid: {issues}")
        # Has the required fields
        text = p.read_text()
        self.assertIn("title:", text)
        self.assertIn("type: journal", text)
        self.assertIn("created: 2026-04-10", text)

    def test_create_journal_file_has_no_wikilinks(self):
        # Daily journal entries are excluded from the knowledge graph (see
        # vault-graph-builder.py::is_ephemeral). They MUST NOT contain any
        # wikilinks — adding [[Journal]] would create a dangling edge in
        # Obsidian and pollute the graph view.
        p = self.tmpdir / "fresh.md"
        self.ja.create_journal_file(p, "main", "2026-04-10")
        self.assertNotIn("[[", p.read_text())
        # Same rule for agent journals
        p2 = self.tmpdir / "agent.md"
        self.ja.create_journal_file(p2, "myagent", "2026-04-10")
        self.assertNotIn("[[", p2.read_text())

    def test_fix_strips_legacy_journal_wikilink(self):
        # Old journal files written before the rule change have a [[Journal]]
        # or [[agent/Journal|Journal]] line right after the frontmatter.
        # The repair pass should remove it.
        p = self.tmpdir / "legacy.md"
        p.write_text(
            "---\n"
            'title: "Journal 2026-04-10"\n'
            "type: journal\n"
            "## 08:00 — entry\nbody\n"
        )
        self.ja.fix_frontmatter(p, "main", "2026-04-10")
        text = p.read_text()
        self.assertNotIn("[[Journal]]", text)
        self.assertIn("## 08:00", text)

    def test_fix_strips_legacy_agent_journal_wikilink(self):
        p = self.tmpdir / "legacy_agent.md"
        # Simulate a file that already has the legacy agent wikilink
        p.write_text(
            "---\n"
            'title: "Journal 2026-04-10"\n'
            "type: journal\n"
            "[[crypto-bro/Journal|Journal]]\n\n"
            "## 09:00 — note\n"
        )
        self.ja.fix_frontmatter(p, "crypto-bro", "2026-04-10")
        text = p.read_text()
        self.assertNotIn("[[", text)
        self.assertIn("## 09:00", text)

    def test_create_for_agent_uses_agent_path(self):
        agent_journal = self.ja.get_journal_path(self.tmpdir, "myagent", "2026-04-10")
        self.assertEqual(
            agent_journal,
            self.tmpdir / "Agents" / "myagent" / "Journal" / "2026-04-10.md",
        )


class TimeMatching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ja = _load_script()

    def test_time_close_within_tolerance(self):
        self.assertTrue(self.ja.time_close("08:00", "08:25"))
        self.assertTrue(self.ja.time_close("08:00", "07:35"))

    def test_time_close_outside_tolerance(self):
        self.assertFalse(self.ja.time_close("08:00", "09:00"))

    def test_time_close_invalid_input(self):
        self.assertFalse(self.ja.time_close("garbage", "08:00"))

    def test_extract_entry_times(self):
        content = "## 08:00 — first\n\n## 14:30 — afternoon\n\nbody"
        times = self.ja.extract_entry_times(content)
        self.assertEqual(times, ["08:00", "14:30"])

    def test_is_covered(self):
        journal_times = ["08:00", "14:00"]
        self.assertTrue(self.ja.is_covered("08:15", journal_times))
        self.assertFalse(self.ja.is_covered("23:00", journal_times))


class FullAuditReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ja = _load_script()

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.vault = Path(self._td.name) / "vault"
        (self.vault / "Journal" / ".activity").mkdir(parents=True)

    def tearDown(self):
        self._td.cleanup()

    def test_no_activity_log_message(self):
        # No fixture written -> load_activity_log returns []
        entries = self.ja.load_activity_log(self.vault, "2026-04-10")
        self.assertEqual(entries, [])

    def test_activity_log_loaded(self):
        log_path = self.vault / "Journal" / ".activity" / "2026-04-10.jsonl"
        log_path.write_text(
            json.dumps({"agent": "main", "type": "interactive", "session": "s1",
                        "time": "08:00", "user": "hi", "response": "hello"}) + "\n"
            + json.dumps({"agent": "main", "type": "routine", "routine": "r1",
                          "time": "08:01"}) + "\n"
        )
        entries = self.ja.load_activity_log(self.vault, "2026-04-10")
        self.assertEqual(len(entries), 2)

    def test_activity_log_skips_corrupt_lines(self):
        log_path = self.vault / "Journal" / ".activity" / "2026-04-10.jsonl"
        log_path.write_text(
            json.dumps({"agent": "main", "time": "08:00"}) + "\n"
            + "this is not json\n"
            + json.dumps({"agent": "main", "time": "09:00"}) + "\n"
        )
        entries = self.ja.load_activity_log(self.vault, "2026-04-10")
        self.assertEqual(len(entries), 2)

    def test_fix_all_creates_missing(self):
        entries = [
            {"agent": "main", "type": "interactive", "session": "s1",
             "time": "08:00", "user": "hi", "response": "hello"},
        ]
        actions = self.ja.fix_all(self.vault, "2026-04-10", entries)
        self.assertEqual(len(actions), 1)
        self.assertIn("CREATED", actions[0])
        # And the file is now there + valid
        journal = self.vault / "Journal" / "2026-04-10.md"
        self.assertTrue(journal.exists())
        ok, _ = self.ja.validate_frontmatter(journal.read_text())
        self.assertTrue(ok)

    def test_fix_all_idempotent(self):
        entries = [{"agent": "main", "time": "08:00"}]
        self.ja.fix_all(self.vault, "2026-04-10", entries)
        # Second run should not re-create
        actions2 = self.ja.fix_all(self.vault, "2026-04-10", entries)
        self.assertEqual(actions2, [])


if __name__ == "__main__":
    unittest.main()
