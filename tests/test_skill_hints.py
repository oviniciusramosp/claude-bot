"""Tests for graph.json-based skill hint injection (_select_relevant_skills).

Covers:
- top-N truncation
- keyword scoring (exact + substring)
- stopword + short-word filtering
- empty prompt returns []
- missing graph.json returns [] (expected for new users — not an error)
- malformed graph.json returns [] (logged, not raised)
- SKILL_HINTS_ENABLED=False returns [] without touching fs
- non-skill nodes are ignored
"""
import json
import tempfile
import unittest
from pathlib import Path

from tests._botload import load_bot_module


def _write_graph(vault: Path, nodes: list) -> Path:
    gdir = vault / ".graphs"
    gdir.mkdir(parents=True, exist_ok=True)
    gfile = gdir / "graph.json"
    gfile.write_text(json.dumps({"nodes": nodes, "edges": []}), encoding="utf-8")
    return gfile


class SelectRelevantSkills(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        root = Path(self._td.name)
        self.home = root / "home"
        self.vault = root / "vault"
        self.home.mkdir()
        self.bot = load_bot_module(tmp_home=self.home, vault_dir=self.vault)
        # Always re-enable hints for the test (default is True; explicit safety)
        self.bot.SKILL_HINTS_ENABLED = True

    def tearDown(self):
        self._td.cleanup()

    def test_missing_graph_returns_empty(self):
        # No graph.json file exists — should return [] silently
        result = self.bot._select_relevant_skills("create a pipeline for reports")
        self.assertEqual(result, [])

    def test_empty_prompt_returns_empty(self):
        _write_graph(self.vault, [{
            "label": "Create Pipeline", "type": "skill",
            "source_file": "main/Skills/create-pipeline.md",
            "description": "build pipelines",
        }])
        self.assertEqual(self.bot._select_relevant_skills(""), [])
        self.assertEqual(self.bot._select_relevant_skills("   "), [])

    def test_keyword_match_picks_skill(self):
        _write_graph(self.vault, [
            {
                "label": "Create Pipeline", "type": "skill",
                "source_file": "main/Skills/create-pipeline.md",
                "description": "Build multi-step pipelines with parallel agents.",
                "tags": ["pipeline", "automation"],
            },
            {
                "label": "Create Agent", "type": "skill",
                "source_file": "main/Skills/create-agent.md",
                "description": "Create a specialized agent.",
                "tags": ["agent"],
            },
        ])
        result = self.bot._select_relevant_skills("I want to build a pipeline for my reports")
        self.assertIn("create-pipeline", result)
        # Should be first because pipeline keywords dominate
        self.assertEqual(result[0], "create-pipeline")

    def test_top_n_truncation(self):
        nodes = [
            {
                "label": f"Skill {i}", "type": "skill",
                "source_file": f"main/Skills/skill-{i}.md",
                "description": "pipeline agent routine workflow automation",
            }
            for i in range(10)
        ]
        _write_graph(self.vault, nodes)
        result = self.bot._select_relevant_skills(
            "pipeline agent workflow", max_n=3,
        )
        self.assertLessEqual(len(result), 3)

    def test_stopwords_filtered_out(self):
        _write_graph(self.vault, [{
            "label": "The Agent", "type": "skill",
            "source_file": "main/Skills/the-skill.md",
            "description": "the and or of to in is it for",
        }])
        # Only stopwords + short words → no match
        result = self.bot._select_relevant_skills("the a of to in")
        self.assertEqual(result, [])

    def test_short_words_ignored(self):
        _write_graph(self.vault, [{
            "label": "api", "type": "skill",
            "source_file": "main/Skills/api.md",
            "description": "api",
        }])
        # All tokens <=3 chars → empty
        result = self.bot._select_relevant_skills("api go do is")
        self.assertEqual(result, [])

    def test_non_skill_nodes_ignored(self):
        _write_graph(self.vault, [
            {
                "label": "pipeline note", "type": "note",
                "source_file": "main/Notes/pipeline.md",
                "description": "about pipelines",
            },
            {
                "label": "Real Skill", "type": "skill",
                "source_file": "main/Skills/real-skill.md",
                "description": "pipeline pipeline pipeline",
            },
        ])
        result = self.bot._select_relevant_skills("pipeline")
        self.assertEqual(result, ["real-skill"])

    def test_malformed_graph_returns_empty(self):
        gdir = self.vault / ".graphs"
        gdir.mkdir(parents=True)
        (gdir / "graph.json").write_text("not valid json {{{", encoding="utf-8")
        # Must not raise
        result = self.bot._select_relevant_skills("pipeline test work")
        self.assertEqual(result, [])

    def test_feature_flag_disables(self):
        _write_graph(self.vault, [{
            "label": "Create Pipeline", "type": "skill",
            "source_file": "main/Skills/create-pipeline.md",
            "description": "build pipelines",
        }])
        self.bot.SKILL_HINTS_ENABLED = False
        self.assertEqual(self.bot._select_relevant_skills("build a pipeline"), [])

    def test_source_file_prefix_counts_as_skill(self):
        # Node without type but with Skills/ path should still be scored
        _write_graph(self.vault, [{
            "label": "Orphan",
            "source_file": "main/Skills/orphan.md",
            "description": "pipeline workflow agent",
        }])
        result = self.bot._select_relevant_skills("pipeline workflow agent")
        self.assertIn("orphan", result)


if __name__ == "__main__":
    unittest.main()
