"""Unit tests for parse_frontmatter, _parse_yaml_value, get_frontmatter_and_body."""
import tempfile
import unittest
from pathlib import Path

from tests._botload import load_bot_module


class ParseYamlValue(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_bool_true(self):
        self.assertIs(self.bot._parse_yaml_value("true"), True)
        self.assertIs(self.bot._parse_yaml_value("TRUE"), True)
        self.assertIs(self.bot._parse_yaml_value("yes"), True)

    def test_bool_false(self):
        self.assertIs(self.bot._parse_yaml_value("false"), False)
        self.assertIs(self.bot._parse_yaml_value("no"), False)

    def test_int(self):
        self.assertEqual(self.bot._parse_yaml_value("42"), 42)
        self.assertEqual(self.bot._parse_yaml_value("-7"), -7)

    def test_float(self):
        self.assertEqual(self.bot._parse_yaml_value("3.14"), 3.14)

    def test_quoted_string_double(self):
        self.assertEqual(self.bot._parse_yaml_value('"hello world"'), "hello world")

    def test_quoted_string_single(self):
        self.assertEqual(self.bot._parse_yaml_value("'hello'"), "hello")

    def test_unquoted_string(self):
        self.assertEqual(self.bot._parse_yaml_value("sonnet"), "sonnet")

    def test_flow_list(self):
        self.assertEqual(
            self.bot._parse_yaml_value("[a, b, c]"),
            ["a", "b", "c"],
        )

    def test_flow_list_quoted(self):
        self.assertEqual(
            self.bot._parse_yaml_value('["08:00", "12:00"]'),
            ["08:00", "12:00"],
        )

    def test_empty_flow_list(self):
        self.assertEqual(self.bot._parse_yaml_value("[]"), [])


class ParseFrontmatter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_no_frontmatter_returns_empty(self):
        self.assertEqual(self.bot.parse_frontmatter("# just markdown\n\nbody"), {})

    def test_empty_string(self):
        self.assertEqual(self.bot.parse_frontmatter(""), {})

    def test_unclosed_frontmatter_returns_empty(self):
        text = "---\ntitle: foo\nno closing here\n\n# body"
        self.assertEqual(self.bot.parse_frontmatter(text), {})

    def test_simple_scalars(self):
        text = '---\ntitle: "My routine"\ntype: routine\nenabled: true\nmodel: sonnet\n---\nbody'
        fm = self.bot.parse_frontmatter(text)
        self.assertEqual(fm["title"], "My routine")
        self.assertEqual(fm["type"], "routine")
        self.assertIs(fm["enabled"], True)
        self.assertEqual(fm["model"], "sonnet")

    def test_nested_schedule_block(self):
        text = (
            "---\n"
            "title: r\n"
            "type: routine\n"
            "schedule:\n"
            '  times: ["08:00", "20:00"]\n'
            "  days: [mon, tue, wed]\n"
            "enabled: true\n"
            "---\n"
            "body"
        )
        fm = self.bot.parse_frontmatter(text)
        self.assertIsInstance(fm["schedule"], dict)
        self.assertEqual(fm["schedule"]["times"], ["08:00", "20:00"])
        self.assertEqual(fm["schedule"]["days"], ["mon", "tue", "wed"])
        # The block should have closed once we moved to enabled:
        self.assertIs(fm["enabled"], True)

    def test_comment_lines_ignored(self):
        text = "---\n# this is a comment\ntitle: x\ntype: routine\n---\n"
        fm = self.bot.parse_frontmatter(text)
        self.assertEqual(fm.get("title"), "x")
        self.assertNotIn("# this is a comment", fm)

    def test_get_frontmatter_and_body_returns_body(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.md"
            p.write_text("---\ntitle: t\ntype: routine\n---\nhello world\n", encoding="utf-8")
            fm, body = self.bot.get_frontmatter_and_body(p)
            self.assertEqual(fm["title"], "t")
            self.assertEqual(body, "hello world")

    def test_get_frontmatter_and_body_missing_file(self):
        fm, body = self.bot.get_frontmatter_and_body(Path("/nonexistent/file.md"))
        self.assertEqual(fm, {})
        self.assertEqual(body, "")


class ParsePipelineBody(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bot = load_bot_module()

    def test_no_block_returns_empty(self):
        self.assertEqual(self.bot.parse_pipeline_body("just prose"), [])

    def test_simple_two_steps(self):
        body = (
            "intro\n"
            "```pipeline\n"
            "steps:\n"
            "  - id: collect\n"
            "    name: Collect data\n"
            "    model: sonnet\n"
            "  - id: analyze\n"
            "    name: Analyze\n"
            "    depends_on: [collect]\n"
            "    model: opus\n"
            "```\n"
            "outro"
        )
        steps = self.bot.parse_pipeline_body(body)
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["id"], "collect")
        self.assertEqual(steps[0]["name"], "Collect data")
        self.assertEqual(steps[1]["id"], "analyze")
        self.assertEqual(steps[1]["depends_on"], ["collect"])

    def test_unclosed_block_still_parses(self):
        body = "```pipeline\nsteps:\n  - id: x\n    name: only one\n"
        steps = self.bot.parse_pipeline_body(body)
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["id"], "x")


if __name__ == "__main__":
    unittest.main()
