"""Tests for scripts/vault_frontmatter.py and scripts/vault_query.py.

Pure stdlib unittest. No bot import required — these modules are standalone.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import vault_frontmatter as vfm  # noqa: E402
import vault_query as vq  # noqa: E402


# ---------------------------------------------------------------------------
# Vault fixture builder
# ---------------------------------------------------------------------------


def _make_vault(tmp: Path) -> Path:
    """Create a minimal vault tree for tests."""
    vault = tmp / "vault"
    (vault / "Routines").mkdir(parents=True)
    (vault / "Skills").mkdir(parents=True)
    (vault / "Agents" / "crypto-bro").mkdir(parents=True)
    (vault / "Notes").mkdir(parents=True)

    # A routine with a nested schedule block
    (vault / "Routines" / "crypto-news.md").write_text(
        """---
title: "Crypto News"
description: "News pipeline."
type: pipeline
created: 2026-04-01
updated: 2026-04-09
tags: [pipeline, crypto, news]
schedule:
  times: ["09:00", "13:00"]
  days: ["*"]
model: sonnet
agent: crypto-bro
enabled: true
notify: none
---

[[Routines]]

Body content with a [[wikilink]].
""",
        encoding="utf-8",
    )

    # A simple routine
    (vault / "Routines" / "journal-audit.md").write_text(
        """---
title: "Journal Audit"
description: "Nightly audit."
type: routine
created: 2026-03-01
updated: 2026-03-01
tags: [routine, maintenance]
schedule:
  times: ["23:59"]
  days: ["*"]
model: haiku
enabled: true
---

Audit body.
""",
        encoding="utf-8",
    )

    # A disabled routine
    (vault / "Routines" / "old-routine.md").write_text(
        """---
title: "Old Routine"
description: "Disabled."
type: routine
created: 2025-01-01
updated: 2025-01-01
tags: [routine]
schedule:
  times: ["08:00"]
  days: ["mon"]
model: opus
enabled: false
---

Old body.
""",
        encoding="utf-8",
    )

    # A skill
    (vault / "Skills" / "publish-notion.md").write_text(
        """---
title: "Publish to Notion"
description: "Notion API publish."
type: skill
created: 2026-02-01
updated: 2026-02-01
tags: [skill, publish, notion]
trigger: "when posting to Notion"
---

Publish body.
""",
        encoding="utf-8",
    )

    # A note with a related block (block list of objects)
    (vault / "Notes" / "polymarket.md").write_text(
        """---
title: "Polymarket"
description: "Prediction market context."
type: note
created: 2026-04-01
updated: 2026-04-01
tags: [note, polymarket, crypto]
related:
  - file: crypto-news
    type: extracted
    reason: "shared crypto context"
---

Polymarket body.
""",
        encoding="utf-8",
    )

    # An agent metadata file
    (vault / "Agents" / "crypto-bro" / "agent.md").write_text(
        """---
title: "Crypto Bro"
description: "Crypto specialist."
type: agent
created: 2026-01-01
updated: 2026-01-01
tags: [agent, crypto]
name: "Crypto Bro"
model: sonnet
icon: "🪙"
default: false
---
""",
        encoding="utf-8",
    )

    return vault


# ---------------------------------------------------------------------------
# vault_frontmatter tests
# ---------------------------------------------------------------------------


class FrontmatterParserTest(unittest.TestCase):
    def test_simple_scalars(self):
        text = """---
title: Hello
count: 42
ratio: 1.5
flag: true
---

body
"""
        fm = vfm.parse_frontmatter(text)
        self.assertEqual(fm["title"], "Hello")
        self.assertEqual(fm["count"], 42)
        self.assertEqual(fm["ratio"], 1.5)
        self.assertIs(fm["flag"], True)

    def test_flow_list(self):
        text = """---
tags: [a, b, c]
---
"""
        fm = vfm.parse_frontmatter(text)
        self.assertEqual(fm["tags"], ["a", "b", "c"])

    def test_quoted_strings(self):
        text = """---
title: "Hello: world"
desc: 'with #hash'
---
"""
        fm = vfm.parse_frontmatter(text)
        self.assertEqual(fm["title"], "Hello: world")
        self.assertEqual(fm["desc"], "with #hash")

    def test_nested_block(self):
        text = """---
schedule:
  times: ["09:00", "13:00"]
  days: ["*"]
  until: 2026-12-31
model: sonnet
---
"""
        fm = vfm.parse_frontmatter(text)
        self.assertIn("schedule", fm)
        self.assertEqual(fm["schedule"]["times"], ["09:00", "13:00"])
        self.assertEqual(fm["schedule"]["days"], ["*"])
        self.assertEqual(fm["model"], "sonnet")

    def test_block_scalar_literal(self):
        text = """---
prompt: |
  Line 1
  Line 2
  Line 3
title: After
---
"""
        fm = vfm.parse_frontmatter(text)
        self.assertEqual(fm["prompt"], "Line 1\nLine 2\nLine 3")
        self.assertEqual(fm["title"], "After")

    def test_block_list_of_objects(self):
        text = """---
related:
  - file: foo
    type: extracted
    reason: "bar"
  - file: baz
    type: inferred
    reason: "qux"
---
"""
        fm = vfm.parse_frontmatter(text)
        self.assertEqual(len(fm["related"]), 2)
        self.assertEqual(fm["related"][0]["file"], "foo")
        self.assertEqual(fm["related"][0]["type"], "extracted")
        self.assertEqual(fm["related"][1]["file"], "baz")
        self.assertEqual(fm["related"][1]["type"], "inferred")

    def test_no_frontmatter(self):
        self.assertEqual(vfm.parse_frontmatter("just body"), {})
        self.assertEqual(vfm.parse_frontmatter(""), {})

    def test_extract_wikilinks_skips_code_blocks(self):
        text = """---
t: x
---

Real link: [[foo]]

```python
code = "[[not-a-link]]"
```

[[bar]]
"""
        links = vfm.extract_wikilinks(text)
        self.assertEqual(set(links), {"foo", "bar"})

    def test_get_frontmatter_and_body(self):
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            f = tmp / "x.md"
            f.write_text("---\ntitle: T\n---\n\nbody here\n")
            fm, body = vfm.get_frontmatter_and_body(f)
            self.assertEqual(fm["title"], "T")
            self.assertEqual(body, "body here")

    def test_serialize_round_trip_scalars(self):
        fm = {"title": "Hello", "count": 42, "flag": True, "tags": ["a", "b"]}
        s = vfm.serialize_frontmatter(fm)
        parsed = vfm.parse_frontmatter(f"---\n{s}\n---\n")
        self.assertEqual(parsed["title"], "Hello")
        self.assertEqual(parsed["count"], 42)
        self.assertIs(parsed["flag"], True)
        self.assertEqual(parsed["tags"], ["a", "b"])

    def test_serialize_nested_dict(self):
        fm = {"schedule": {"times": ["09:00"], "days": ["mon"]}, "model": "sonnet"}
        s = vfm.serialize_frontmatter(fm)
        parsed = vfm.parse_frontmatter(f"---\n{s}\n---\n")
        self.assertEqual(parsed["schedule"]["times"], ["09:00"])
        self.assertEqual(parsed["schedule"]["days"], ["mon"])
        self.assertEqual(parsed["model"], "sonnet")


# ---------------------------------------------------------------------------
# vault_query tests
# ---------------------------------------------------------------------------


class VaultQueryTest(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.vault = _make_vault(self.tmp)
        self.vi = vq.load_vault(self.vault)

    def tearDown(self):
        self._td.cleanup()

    def test_load_count(self):
        # 3 routines + 1 skill + 1 note + 1 agent = 6
        self.assertEqual(len(self.vi), 6)

    def test_get_by_rel_path(self):
        f = self.vi.get("Routines/crypto-news.md")
        self.assertIsNotNone(f)
        self.assertEqual(f.title, "Crypto News")

    def test_get_by_node_id(self):
        f = self.vi.get("routines_crypto-news")
        self.assertIsNotNone(f)
        self.assertEqual(f.type, "pipeline")

    def test_find_by_type(self):
        routines = self.vi.find(type="routine")
        self.assertEqual(len(routines), 2)
        names = {r.path.stem for r in routines}
        self.assertEqual(names, {"journal-audit", "old-routine"})

    def test_find_by_type_and_enabled(self):
        active = self.vi.find(type="routine", enabled=True)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].path.stem, "journal-audit")

    def test_find_pipeline_by_agent(self):
        result = self.vi.find(type="pipeline", agent="crypto-bro")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path.stem, "crypto-news")

    def test_find_tags_contains(self):
        result = self.vi.find(tags__contains="publish")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path.stem, "publish-notion")

    def test_find_tags_contains_crypto(self):
        result = self.vi.find(tags__contains="crypto")
        # crypto-news (pipeline), polymarket (note), crypto-bro/agent.md
        self.assertEqual(len(result), 3)

    def test_find_in_operator(self):
        result = self.vi.find(model__in=["sonnet", "haiku"])
        names = {r.path.stem for r in result}
        self.assertIn("crypto-news", names)
        self.assertIn("journal-audit", names)
        self.assertNotIn("old-routine", names)

    def test_find_exists(self):
        with_trigger = self.vi.find(trigger__exists=True)
        self.assertEqual(len(with_trigger), 1)
        self.assertEqual(with_trigger[0].path.stem, "publish-notion")

    def test_search_text_title(self):
        result = self.vi.search_text("polymarket")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path.stem, "polymarket")

    def test_search_text_tag(self):
        result = self.vi.search_text("notion")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].path.stem, "publish-notion")

    def test_related_via_wikilinks_fallback(self):
        # No graph.json — falls back to wikilinks
        # crypto-news has [[wikilink]] but no real target file by that name
        result = self.vi.related("Routines/crypto-news.md", depth=1)
        # Should not crash, may be empty
        self.assertIsInstance(result, list)

    def test_filter_expression_parser(self):
        d = vq.parse_filter_expression("type=routine model=opus enabled=true")
        self.assertEqual(d, {"type": "routine", "model": "opus", "enabled": True})

    def test_filter_expression_with_quotes(self):
        d = vq.parse_filter_expression('title="Hello world" type=note')
        self.assertEqual(d["title"], "Hello world")
        self.assertEqual(d["type"], "note")

    def test_excluded_dirs(self):
        # Add a file inside .obsidian — should be excluded
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "config.md").write_text(
            "---\ntitle: Config\ntype: config\n---\n"
        )
        vi = vq.load_vault(self.vault)
        self.assertEqual(len(vi), 6)  # unchanged


# ---------------------------------------------------------------------------
# Parity check: vault_frontmatter parses what the bot's parser parses
# ---------------------------------------------------------------------------


class BotParserParityTest(unittest.TestCase):
    """Verify that vault_frontmatter.parse_frontmatter produces the same
    result as the bot's parse_frontmatter on representative inputs. This
    catches drift if either parser changes."""

    def setUp(self):
        # Lazy-import the bot only here so test_vault_query.py runs even if
        # the bot import is broken (we want to know it's broken via this test).
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from _botload import load_bot_module

        self._td = tempfile.TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.bot = load_bot_module(self.tmp)

    def tearDown(self):
        self._td.cleanup()

    def _assert_same(self, text):
        a = vfm.parse_frontmatter(text)
        b = self.bot.parse_frontmatter(text)
        self.assertEqual(a, b, f"Parser drift on: {text!r}")

    def test_parity_simple(self):
        self._assert_same("---\ntitle: T\n---\n")

    def test_parity_nested_schedule(self):
        self._assert_same(
            """---
title: T
schedule:
  times: ["09:00"]
  days: ["*"]
model: sonnet
---
"""
        )

    def test_parity_block_scalar(self):
        self._assert_same(
            """---
title: T
prompt: |
  Line 1
  Line 2
---
"""
        )

    def test_parity_flow_list(self):
        self._assert_same("---\ntags: [a, b, c]\n---\n")


if __name__ == "__main__":
    unittest.main()
