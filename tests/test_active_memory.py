"""Tests for Active Memory — proactive vault context injection.

Active Memory scores non-skill nodes from vault/.graphs/graph.json against
the user's prompt and returns a compact "## Active Memory" block with short
excerpts. It is deterministic (no LLM call) and fail-open (any error returns
None so the main Claude turn proceeds normally).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests._botload import load_bot_module


def _write_graph(vault_dir: Path, nodes: list, edges: list | None = None) -> Path:
    graph_dir = vault_dir / ".graphs"
    graph_dir.mkdir(parents=True, exist_ok=True)
    path = graph_dir / "graph.json"
    path.write_text(json.dumps({"nodes": nodes, "edges": edges or []}), encoding="utf-8")
    return path


def _write_note(vault_dir: Path, relative: str, body: str, frontmatter: dict | None = None) -> Path:
    path = vault_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = []
    if frontmatter is not None:
        parts.append("---")
        for k, v in frontmatter.items():
            parts.append(f"{k}: {v}")
        parts.append("---")
        parts.append("")
    parts.append(body)
    path.write_text("\n".join(parts), encoding="utf-8")
    return path


class ActiveMemoryLookupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-am-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-am-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)
        # Clear the module-level graph cache so each test gets a fresh read
        self.bot._active_memory_graph_cache.clear()

    def _nodes(self) -> list:
        return [
            {
                "id": "notes_crypto",
                "label": "Crypto Strategy",
                "source_file": "main/Notes/crypto-strategy.md",
                "type": "note",
                "description": "Durable notes about crypto trading strategies.",
                "tags": ["crypto", "trading"],
            },
            {
                "id": "routines_update_check",
                "label": "Update Check",
                "source_file": "main/Routines/update-check.md",
                "type": "routine",
                "description": "Daily brew and git update check for the bot.",
                "tags": [],
            },
            {
                "id": "skills_example",
                "label": "Example Skill",
                "source_file": "Skills/example-skill.md",
                "type": "skill",
                "description": "A skill that should be EXCLUDED from Active Memory.",
                "tags": ["crypto"],
            },
            {
                "id": "history_log",
                "label": "History Log",
                "source_file": "main/Routines/.history/2026-04.md",
                "type": "history",
                "description": "Churn-y log — should be EXCLUDED.",
                "tags": [],
            },
        ]

    def test_matches_note_by_keyword(self) -> None:
        _write_graph(self.vault, self._nodes())
        _write_note(
            self.vault, "main/Notes/crypto-strategy.md",
            "Este é o corpo detalhado da estratégia de crypto — aqui estão as regras e observações.",
            frontmatter={"title": "Crypto Strategy", "type": "note"},
        )
        block = self.bot._active_memory_lookup("Me fale sobre a estratégia de crypto")
        self.assertIsNotNone(block)
        self.assertIn("## Active Memory", block)
        self.assertIn("main/Notes/crypto-strategy.md", block)
        # Skill node must NOT appear — it's covered by _select_relevant_skills
        self.assertNotIn("Skills/example-skill.md", block)
        # History node must NOT appear
        self.assertNotIn("main/Routines/.history", block)

    def test_no_match_returns_none(self) -> None:
        _write_graph(self.vault, self._nodes())
        block = self.bot._active_memory_lookup("xyzzynothinghere")
        self.assertIsNone(block)

    def test_empty_prompt_returns_none(self) -> None:
        _write_graph(self.vault, self._nodes())
        self.assertIsNone(self.bot._active_memory_lookup(""))
        self.assertIsNone(self.bot._active_memory_lookup("   "))

    def test_missing_graph_file_returns_none(self) -> None:
        # No graph.json at all
        block = self.bot._active_memory_lookup("crypto strategy")
        self.assertIsNone(block)

    def test_global_flag_off_returns_none(self) -> None:
        _write_graph(self.vault, self._nodes())
        original = self.bot.ACTIVE_MEMORY_ENABLED
        self.bot.ACTIVE_MEMORY_ENABLED = False
        try:
            block = self.bot._active_memory_lookup("crypto strategy")
            self.assertIsNone(block)
        finally:
            self.bot.ACTIVE_MEMORY_ENABLED = original

    def test_max_nodes_cap(self) -> None:
        # Five matching note files; cap must limit to ACTIVE_MEMORY_MAX_NODES (3)
        nodes = []
        for i in range(5):
            rel = f"main/Notes/note-{i}.md"
            nodes.append({
                "id": f"notes_note_{i}",
                "label": f"Crypto Note {i}",
                "source_file": rel,
                "type": "note",
                "description": "crypto trading notes",
                "tags": ["crypto"],
            })
            _write_note(self.vault, rel, f"Body of note {i}")
        _write_graph(self.vault, nodes)
        block = self.bot._active_memory_lookup("crypto trading notes")
        self.assertIsNotNone(block)
        hit_count = sum(1 for line in block.splitlines() if line.startswith("- [["))
        self.assertEqual(hit_count, self.bot.ACTIVE_MEMORY_MAX_NODES)

    def test_excerpt_is_capped(self) -> None:
        nodes = [{
            "id": "notes_long",
            "label": "Long Note",
            "source_file": "main/Notes/long.md",
            "type": "note",
            "description": "crypto durable note",
            "tags": ["crypto"],
        }]
        _write_graph(self.vault, nodes)
        long_body = "crypto " * 2000  # way over the 400 char cap
        _write_note(
            self.vault, "main/Notes/long.md", long_body,
            frontmatter={"title": "Long Note"},
        )
        block = self.bot._active_memory_lookup("crypto note")
        self.assertIsNotNone(block)
        # The excerpt line contains 'excerpt: "..."' — check that total block
        # is not absurdly long (cap is 400 per node + small formatting overhead)
        self.assertLess(len(block), 1200)
        self.assertIn("…", block)  # ellipsis marker

    def test_excerpt_strips_frontmatter(self) -> None:
        nodes = [{
            "id": "notes_frontmatter",
            "label": "FM Note",
            "source_file": "main/Notes/fm.md",
            "type": "note",
            "description": "crypto note with frontmatter",
            "tags": ["crypto"],
        }]
        _write_graph(self.vault, nodes)
        _write_note(
            self.vault, "main/Notes/fm.md",
            "This is the actual body content about crypto markets.",
            frontmatter={"title": "FM Note", "secret_field": "should-not-leak"},
        )
        block = self.bot._active_memory_lookup("crypto markets note")
        self.assertIsNotNone(block)
        self.assertIn("actual body content", block)
        self.assertNotIn("secret_field", block)
        self.assertNotIn("should-not-leak", block)

    def test_graph_cache_uses_mtime(self) -> None:
        nodes_v1 = [{
            "id": "notes_v1",
            "label": "V1 Note",
            "source_file": "main/Notes/v1.md",
            "type": "note",
            "description": "crypto v1",
            "tags": [],
        }]
        _write_note(self.vault, "main/Notes/v1.md", "body v1")
        graph_path = _write_graph(self.vault, nodes_v1)
        block1 = self.bot._active_memory_lookup("crypto v1")
        self.assertIsNotNone(block1)
        self.assertIn("main/Notes/v1.md", block1)
        # Second call with same prompt should hit the cache (no crash, same result)
        block2 = self.bot._active_memory_lookup("crypto v1")
        self.assertEqual(block1, block2)
        # Rewrite graph with a different node and bump mtime
        import os
        nodes_v2 = [{
            "id": "notes_v2",
            "label": "V2 Note",
            "source_file": "main/Notes/v2.md",
            "type": "note",
            "description": "crypto v2",
            "tags": [],
        }]
        _write_note(self.vault, "main/Notes/v2.md", "body v2")
        _write_graph(self.vault, nodes_v2)
        # Force mtime to advance so cache invalidates even on fast filesystems
        os.utime(graph_path, (graph_path.stat().st_atime, graph_path.stat().st_mtime + 10))
        block3 = self.bot._active_memory_lookup("crypto v2")
        self.assertIsNotNone(block3)
        self.assertIn("main/Notes/v2.md", block3)
        self.assertNotIn("main/Notes/v1.md", block3)


class ActiveMemoryCommandTests(unittest.TestCase):
    """cmd_active_memory toggles the per-session flag and persists."""

    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-am-cmd-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-am-cmd-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)

    def test_session_has_active_memory_field_default_true(self) -> None:
        s = self.bot.Session(name="test")
        self.assertTrue(s.active_memory)

    def test_session_active_memory_persists_through_save_load(self) -> None:
        sm = self.bot.SessionManager()
        s = sm.create("am-test")
        s.active_memory = False
        sm.save()
        # Reload from disk
        sm2 = self.bot.SessionManager()
        self.assertIn("am-test", sm2.sessions)
        self.assertFalse(sm2.sessions["am-test"].active_memory)

    def test_handler_map_registers_active_memory(self) -> None:
        import inspect
        src = inspect.getsource(self.bot.ClaudeTelegramBot._handle_text)
        self.assertIn('"/active-memory"', src)

    def test_help_text_mentions_active_memory(self) -> None:
        self.assertIn("/active-memory", self.bot.HELP_TEXT)


if __name__ == "__main__":
    unittest.main()
