"""Tests for v3.0 agent isolation.

Guarantees that once the bot is on a named agent, skill / active-memory /
routine discovery never leaks content from other agents (isolamento total —
see vault restructuring plan approved 2026-04-11).
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests._botload import ensure_agent_layout, load_bot_module


def _write_graph(vault_dir: Path, nodes: list) -> Path:
    gdir = vault_dir / ".graphs"
    gdir.mkdir(parents=True, exist_ok=True)
    gfile = gdir / "graph.json"
    gfile.write_text(
        json.dumps({"nodes": nodes, "edges": []}),
        encoding="utf-8",
    )
    return gfile


def _write_note(vault_dir: Path, relative: str, body: str) -> Path:
    path = vault_dir / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


class SkillHintIsolation(unittest.TestCase):
    """`_select_relevant_skills(agent_id=X)` must only surface X's skills."""

    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-iso-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-iso-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)
        self.bot.SKILL_HINTS_ENABLED = True
        ensure_agent_layout(self.vault, "main")
        ensure_agent_layout(self.vault, "crypto-bro")
        _write_graph(self.vault, [
            {
                "id": "skill_main_pipeline",
                "label": "Create Pipeline",
                "type": "skill",
                "source_file": "main/Skills/create-pipeline.md",
                "description": "Build multi-step pipelines automation workflow.",
                "tags": ["pipeline", "automation"],
            },
            {
                "id": "skill_crypto_pipeline",
                "label": "Pump Pipeline",
                "type": "skill",
                "source_file": "crypto-bro/Skills/pump-pipeline.md",
                "description": "Build multi-step pipelines automation workflow.",
                "tags": ["pipeline", "crypto"],
            },
        ])

    def test_main_session_sees_only_main_skills(self) -> None:
        result = self.bot._select_relevant_skills(
            "I want to build a pipeline automation workflow",
            agent_id="main",
        )
        self.assertIn("create-pipeline", result)
        self.assertNotIn("pump-pipeline", result)

    def test_named_agent_sees_only_own_skills(self) -> None:
        result = self.bot._select_relevant_skills(
            "I want to build a pipeline automation workflow",
            agent_id="crypto-bro",
        )
        self.assertIn("pump-pipeline", result)
        self.assertNotIn("create-pipeline", result)

    def test_unknown_agent_sees_nothing(self) -> None:
        result = self.bot._select_relevant_skills(
            "pipeline automation workflow",
            agent_id="nonexistent",
        )
        self.assertEqual(result, [])


class ActiveMemoryIsolation(unittest.TestCase):
    """`_active_memory_lookup(agent_id=X)` must only surface X's notes."""

    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-iso-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-iso-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)
        self.bot._active_memory_graph_cache.clear()
        ensure_agent_layout(self.vault, "main")
        ensure_agent_layout(self.vault, "crypto-bro")
        _write_graph(self.vault, [
            {
                "id": "notes_main_crypto",
                "label": "Main Crypto",
                "source_file": "main/Notes/crypto-overview.md",
                "type": "note",
                "description": "Durable crypto strategy overview for main.",
                "tags": ["crypto"],
            },
            {
                "id": "notes_crypto_bro_strategy",
                "label": "Crypto Strategy",
                "source_file": "crypto-bro/Notes/trading-strategy.md",
                "type": "note",
                "description": "Durable trading strategy for crypto-bro.",
                "tags": ["crypto"],
            },
        ])
        _write_note(
            self.vault, "main/Notes/crypto-overview.md",
            "Main body about crypto markets.",
        )
        _write_note(
            self.vault, "crypto-bro/Notes/trading-strategy.md",
            "Crypto-bro body about trading strategies.",
        )

    def test_main_only_sees_main_content(self) -> None:
        block = self.bot._active_memory_lookup("crypto trading strategy", agent_id="main")
        self.assertIsNotNone(block)
        self.assertIn("main/Notes/crypto-overview.md", block)
        self.assertNotIn("crypto-bro/", block)

    def test_named_agent_only_sees_own_content(self) -> None:
        block = self.bot._active_memory_lookup("crypto trading strategy", agent_id="crypto-bro")
        self.assertIsNotNone(block)
        self.assertIn("crypto-bro/Notes/trading-strategy.md", block)
        self.assertNotIn("main/", block)


class RoutineSchedulerIsolation(unittest.TestCase):
    """The routine scheduler walks every Agents/*/Routines/ folder and the
    owning agent is read from the path, never from the frontmatter."""

    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-iso-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-iso-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)
        # ensure_agent_layout already writes agent-info.md so iter_agent_ids
        # picks up the fixture agents.
        ensure_agent_layout(self.vault, "main")
        ensure_agent_layout(self.vault, "crypto-bro")

    def _write_routine(self, agent: str, name: str, agent_fm: str = "") -> Path:
        p = self.vault / agent / "Routines" / f"{name}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        agent_line = f"agent: {agent_fm}\n" if agent_fm else ""
        p.write_text(
            "---\n"
            f"title: {name}\n"
            "description: test\n"
            "type: routine\n"
            "created: 2026-04-11\n"
            "updated: 2026-04-11\n"
            "tags: [routine]\n"
            "schedule:\n"
            "  times: [\"08:00\"]\n"
            "  days: [\"*\"]\n"
            "model: sonnet\n"
            f"{agent_line}"
            "enabled: true\n"
            "---\n\n"
            "Body.\n",
            encoding="utf-8",
        )
        return p

    def test_iter_routine_files_finds_each_agent(self) -> None:
        self._write_routine("main", "alpha")
        self._write_routine("crypto-bro", "beta")
        found = {p.name for p in self.bot._iter_routine_files()}
        self.assertEqual(found, {"alpha.md", "beta.md"})

    def test_folder_wins_over_frontmatter_agent(self) -> None:
        # Disagreement: file is under crypto-bro/, frontmatter claims `main`.
        self._write_routine("crypto-bro", "rogue", agent_fm="main")

        # Stub out the time so the scheduler thinks it's 08:00 on a Monday.
        import time as real_time

        class _FakeTime:
            def strftime(self, fmt):
                if fmt == "%H:%M":
                    return "08:00"
                if fmt == "%Y-%m-%d":
                    return "2026-04-13"
                if fmt == "%Y-%m-%dT%H:%M:%S":
                    return "2026-04-13T08:00:00"
                return real_time.strftime(fmt)

            def localtime(self, *_):
                return type("tm", (), {"tm_wday": 0, "tm_mday": 13})()

            def time(self):
                return real_time.time()

        original = self.bot.time
        self.bot.time = _FakeTime()
        enqueued: list = []
        try:
            state = self.bot.RoutineStateManager()
            sched = self.bot.RoutineScheduler(
                state,
                enqueue_fn=lambda task: enqueued.append(task),
            )
            sched._check_routines()
        finally:
            self.bot.time = original

        self.assertEqual(len(enqueued), 1)
        self.assertEqual(enqueued[0].agent, "crypto-bro")


class ReactionDispatchOwnership(unittest.TestCase):
    """`load_reaction` resolves across every Agents/*/Reactions/ and carries
    the owning agent through the return dict."""

    def setUp(self) -> None:
        self.tmp_home = Path(tempfile.mkdtemp(prefix="cb-iso-home-"))
        self.vault = Path(tempfile.mkdtemp(prefix="cb-iso-vault-"))
        self.bot = load_bot_module(tmp_home=self.tmp_home, vault_dir=self.vault)
        for agent in ("main", "crypto-bro"):
            ensure_agent_layout(self.vault, agent)
        (self.vault / "crypto-bro" / "Reactions" / "pump-webhook.md").write_text(
            "---\n"
            "title: Pump Webhook\n"
            "description: crypto webhook\n"
            "type: reaction\n"
            "created: 2026-04-11\n"
            "updated: 2026-04-11\n"
            "tags: [reaction]\n"
            "enabled: true\n"
            "auth:\n"
            "  mode: token\n"
            "action:\n"
            "  routine: pump-alert\n"
            "---\n\nBody\n",
            encoding="utf-8",
        )

    def test_reaction_found_under_named_agent(self) -> None:
        result = self.bot.load_reaction("pump-webhook")
        self.assertIsNotNone(result)
        self.assertEqual(result["owner_agent"], "crypto-bro")
        self.assertEqual(result["action"]["agent"], "crypto-bro")


if __name__ == "__main__":
    unittest.main()
