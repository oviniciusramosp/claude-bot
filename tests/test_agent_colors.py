"""Tests for the Obsidian graph-view color-group sync."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests._botload import ensure_agent_layout, load_bot_module


def _seed_obsidian_graph_json(vault: Path, color_groups: list | None = None) -> Path:
    obs = vault / ".obsidian"
    obs.mkdir(parents=True, exist_ok=True)
    path = obs / "graph.json"
    payload = {"collapse-filter": False, "colorGroups": color_groups or []}
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_agent_info(vault: Path, agent_id: str, color: str | None = None) -> None:
    base = vault / agent_id
    base.mkdir(parents=True, exist_ok=True)
    color_line = f"color: {color}\n" if color else ""
    (base / f"agent-{agent_id}.md").write_text(
        "---\n"
        f"title: {agent_id}\n"
        f"description: Test agent {agent_id}\n"
        "type: agent\n"
        f"name: {agent_id}\n"
        "model: sonnet\n"
        'icon: "🤖"\n'
        f"{color_line}"
        "---\n",
        encoding="utf-8",
    )


class ResolveAgentColorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.bot = load_bot_module(tmp_home=self.tmp / "home", vault_dir=self.vault)

    def test_known_names_resolve(self) -> None:
        self.assertEqual(self.bot.resolve_agent_color("grey"), 0x9E9E9E)
        self.assertEqual(self.bot.resolve_agent_color("green"), 0x4CAF50)
        self.assertEqual(self.bot.resolve_agent_color("orange"), 0xFF9800)

    def test_case_insensitive_and_trims(self) -> None:
        self.assertEqual(self.bot.resolve_agent_color("  GREEN "), 0x4CAF50)

    def test_unknown_falls_back_to_default(self) -> None:
        default = self.bot.AGENT_COLOR_PALETTE[self.bot.DEFAULT_AGENT_COLOR]
        self.assertEqual(self.bot.resolve_agent_color("mauve"), default)
        self.assertEqual(self.bot.resolve_agent_color(None), default)
        self.assertEqual(self.bot.resolve_agent_color(""), default)


class SyncObsidianGraphColorGroupsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.vault = self.tmp / "vault"
        self.vault.mkdir()
        self.bot = load_bot_module(tmp_home=self.tmp / "home", vault_dir=self.vault)
        # ensure_agent_layout writes agent-info.md; we overwrite it with our
        # own content below (with the color field).
        ensure_agent_layout(self.vault, "main")

    def test_skips_when_obsidian_never_opened(self) -> None:
        # No .obsidian/graph.json exists yet.
        self.assertFalse(self.bot.sync_obsidian_graph_color_groups())

    def test_syncs_three_agents_with_colors(self) -> None:
        _write_agent_info(self.vault, "main", color="grey")
        _write_agent_info(self.vault, "crypto-bro", color="orange")
        _write_agent_info(self.vault, "parmeirense", color="green")
        graph_path = _seed_obsidian_graph_json(self.vault)

        self.assertTrue(self.bot.sync_obsidian_graph_color_groups())
        data = json.loads(graph_path.read_text(encoding="utf-8"))
        groups = data["colorGroups"]
        # Sorted alphabetically by agent id.
        self.assertEqual(len(groups), 3)
        by_query = {g["query"]: g["color"]["rgb"] for g in groups}
        self.assertEqual(by_query["path:crypto-bro/"], 0xFF9800)
        self.assertEqual(by_query["path:main/"], 0x9E9E9E)
        self.assertEqual(by_query["path:parmeirense/"], 0x4CAF50)

    def test_preserves_user_groups(self) -> None:
        _write_agent_info(self.vault, "main", color="grey")
        user_group = {"query": "tag:#important", "color": {"a": 1, "rgb": 0xFF00FF}}
        graph_path = _seed_obsidian_graph_json(self.vault, color_groups=[user_group])

        self.assertTrue(self.bot.sync_obsidian_graph_color_groups())
        data = json.loads(graph_path.read_text(encoding="utf-8"))
        queries = [g["query"] for g in data["colorGroups"]]
        self.assertIn("tag:#important", queries)
        self.assertIn("path:main/", queries)

    def test_cleans_up_legacy_marker_groups(self) -> None:
        _write_agent_info(self.vault, "main", color="grey")
        legacy = {
            "query": "path:main/ claude-bot-agent:main",
            "color": {"a": 1, "rgb": 0x9E9E9E},
        }
        graph_path = _seed_obsidian_graph_json(self.vault, color_groups=[legacy])

        self.assertTrue(self.bot.sync_obsidian_graph_color_groups())
        data = json.loads(graph_path.read_text(encoding="utf-8"))
        queries = [g["query"] for g in data["colorGroups"]]
        self.assertNotIn("path:main/ claude-bot-agent:main", queries)
        self.assertIn("path:main/", queries)

    def test_missing_color_field_falls_back_to_default(self) -> None:
        _write_agent_info(self.vault, "main", color=None)
        graph_path = _seed_obsidian_graph_json(self.vault)

        self.assertTrue(self.bot.sync_obsidian_graph_color_groups())
        data = json.loads(graph_path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["colorGroups"]), 1)
        self.assertEqual(
            data["colorGroups"][0]["color"]["rgb"],
            self.bot.AGENT_COLOR_PALETTE[self.bot.DEFAULT_AGENT_COLOR],
        )


if __name__ == "__main__":
    unittest.main()
