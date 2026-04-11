"""Tests for scripts/vault-graph-builder.py — frontmatter, wikilinks, edges."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "vault-graph-builder.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("vault_graph_under_test", str(SCRIPT_PATH))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["vault_graph_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


class ParseFrontmatter(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gb = _load_script()

    def test_no_frontmatter(self):
        self.assertEqual(self.gb.parse_frontmatter("# just markdown"), {})

    def test_simple_scalars(self):
        text = '---\ntitle: My Note\ntype: note\nenabled: true\n---\nbody'
        fm = self.gb.parse_frontmatter(text)
        self.assertEqual(fm["title"], "My Note")
        self.assertEqual(fm["type"], "note")
        self.assertIs(fm["enabled"], True)

    def test_inline_list(self):
        text = '---\ntags: [a, b, c]\n---\n'
        fm = self.gb.parse_frontmatter(text)
        self.assertEqual(fm["tags"], ["a", "b", "c"])


class ExtractWikilinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gb = _load_script()

    def test_extracts_basic_wikilink(self):
        text = "see [[Foo]] and [[Bar]]"
        self.assertEqual(self.gb.extract_wikilinks(text), ["Foo", "Bar"])

    def test_strips_alias(self):
        # [[Target|Display]] should yield "Target"
        text = "click [[RealName|Display Text]]"
        self.assertEqual(self.gb.extract_wikilinks(text), ["RealName"])

    def test_skips_frontmatter(self):
        text = "---\nrelated: [[X]]\n---\nbody [[Y]]"
        self.assertEqual(self.gb.extract_wikilinks(text), ["Y"])

    def test_skips_fenced_code_blocks(self):
        # Wikilinks inside ``` ... ``` are example code, not real graph edges.
        # See vault/CLAUDE.md "Pipeline graph" — examples shouldn't pollute.
        text = (
            "real link [[A]]\n"
            "\n"
            "```markdown\n"
            "example [[B]]\n"
            "```\n"
            "\n"
            "another real [[C]]\n"
        )
        self.assertEqual(self.gb.extract_wikilinks(text), ["A", "C"])

    def test_skips_nested_code_block(self):
        # Two adjacent fences must toggle in/out correctly.
        text = (
            "[[outside1]]\n"
            "```yaml\n"
            "[[hidden1]]\n"
            "```\n"
            "[[between]]\n"
            "```python\n"
            "[[hidden2]]\n"
            "```\n"
            "[[outside2]]\n"
        )
        self.assertEqual(
            self.gb.extract_wikilinks(text),
            ["outside1", "between", "outside2"],
        )


class NormalizeId(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gb = _load_script()

    def test_normalize_simple(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            f = vault / "Notes" / "My File.md"
            f.parent.mkdir()
            f.write_text("")
            nid = self.gb.normalize_id(f, vault)
            # Lowercase, slashes -> underscores, spaces -> dashes, no .md
            self.assertEqual(nid, "notes_my-file")


class BuildGraph(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gb = _load_script()

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.vault = Path(self._td.name)

    def tearDown(self):
        self._td.cleanup()

    def _write(self, rel: str, content: str) -> Path:
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def test_empty_vault_yields_empty_graph(self):
        graph = self.gb.build_graph(self.vault)
        self.assertEqual(graph["nodes"], [])
        self.assertEqual(graph["edges"], [])

    def test_single_node_no_edges(self):
        self._write("Notes/foo.md",
                    '---\ntitle: Foo\ntype: note\n---\nhello')
        graph = self.gb.build_graph(self.vault)
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertEqual(graph["nodes"][0]["label"], "Foo")
        self.assertEqual(graph["edges"], [])

    def test_wikilink_creates_edge(self):
        self._write("Notes/foo.md",
                    '---\ntitle: Foo\ntype: note\n---\nsee [[bar]]')
        self._write("Notes/bar.md", '---\ntitle: Bar\ntype: note\n---\nbody')
        graph = self.gb.build_graph(self.vault)
        self.assertEqual(len(graph["nodes"]), 2)
        self.assertEqual(len(graph["edges"]), 1)
        edge = graph["edges"][0]
        self.assertEqual(edge["relation"], "references")

    def test_unresolved_wikilink_no_edge(self):
        self._write("Notes/foo.md",
                    '---\ntitle: Foo\ntype: note\n---\nsee [[nonexistent]]')
        graph = self.gb.build_graph(self.vault)
        self.assertEqual(len(graph["nodes"]), 1)
        self.assertEqual(graph["edges"], [])

    def test_duplicate_edges_collapsed(self):
        self._write("Notes/foo.md",
                    '---\ntitle: Foo\ntype: note\n---\n[[bar]] and again [[bar]]')
        self._write("Notes/bar.md", '---\ntitle: Bar\ntype: note\n---\nbody')
        graph = self.gb.build_graph(self.vault)
        self.assertEqual(len(graph["edges"]), 1)

    def test_skips_dotgraph_dir(self):
        self._write(".graphs/old.md", '---\ntitle: Old\n---\n')
        self._write("Notes/keep.md", '---\ntitle: Keep\n---\n')
        graph = self.gb.build_graph(self.vault)
        labels = [n["label"] for n in graph["nodes"]]
        self.assertNotIn("Old", labels)
        self.assertIn("Keep", labels)

    def test_metadata_present(self):
        self._write("Notes/foo.md", '---\ntitle: Foo\n---\n')
        graph = self.gb.build_graph(self.vault)
        meta = graph["metadata"]
        self.assertEqual(meta["total_nodes"], 1)
        self.assertEqual(meta["total_edges"], 0)
        self.assertIn("generated_at", meta)


if __name__ == "__main__":
    unittest.main()
