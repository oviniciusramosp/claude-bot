"""Tests for scripts/journal-weekly-rollup.py.

Locks contract C7 — the rollup routine MUST iterate every agent that
discover_agents() returns (so future agents are covered automatically).
Uses --skip-llm to avoid spawning the real Claude subprocess; we only
verify the end-to-end orchestration: discovery, journal collection by
date window, file writing, and FTS write-through.
"""
from __future__ import annotations

import datetime as _dt
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "journal-weekly-rollup.py"
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import vault_index  # noqa: E402


def _seed_agent(vault: Path, agent_id: str) -> Path:
    base = vault / agent_id
    for sub in ("Journal", "Lessons", "Notes", "Skills", "Routines"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    (base / "Journal" / "weekly").mkdir(exist_ok=True)
    (base / f"agent-{agent_id}.md").write_text(
        "---\n"
        f"title: {agent_id}\n"
        f"description: test agent {agent_id}\n"
        "type: agent\n"
        "---\nhub\n",
        encoding="utf-8",
    )
    return base


def _seed_journal_day(agent_dir: Path, date: str, sections: list[tuple[str, str]]) -> Path:
    path = agent_dir / "Journal" / f"{date}.md"
    header = (
        "---\n"
        f'title: "Journal {date}"\n'
        "type: journal\n"
        "tags: [journal]\n"
        "---\n\n"
    )
    body = header
    for ts, text in sections:
        body += f"## {ts}\n\n{text}\n\n---\n\n"
    path.write_text(body, encoding="utf-8")
    return path


class WeeklyRollupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="cb-weekly-"))
        self.vault = self.tmp / "vault"
        self.db = self.tmp / "idx.sqlite"
        self.vault.mkdir()

    def _run_script(self, today: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable, str(SCRIPT),
                "--vault", str(self.vault),
                "--db", str(self.db),
                "--today", today,
                "--skip-llm",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_covers_all_agents_including_newly_added(self) -> None:
        """Contract C7: adding a new agent requires zero edits to the
        routine or the driver — it gets picked up automatically."""
        # Day: Monday 2026-04-20 → rollup covers 2026-04-13..2026-04-19
        today = "2026-04-20"
        _seed_agent(self.vault, "main")
        _seed_agent(self.vault, "crypto-bro")
        _seed_journal_day(self.vault / "main", "2026-04-15",
                          [("09:00", "main entry about apples")])
        _seed_journal_day(self.vault / "crypto-bro", "2026-04-16",
                          [("10:00", "crypto entry about bitcoin")])
        vault_index.rebuild(self.vault, self.db)

        result = self._run_script(today)
        self.assertEqual(
            result.returncode, 0,
            f"rc={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}",
        )
        self.assertIn("main -> main/Journal/weekly/2026-W16.md", result.stdout)
        self.assertIn("crypto-bro -> crypto-bro/Journal/weekly/2026-W16.md", result.stdout)

        # Both files exist with the expected frontmatter
        main_weekly = self.vault / "main" / "Journal" / "weekly" / "2026-W16.md"
        crypto_weekly = self.vault / "crypto-bro" / "Journal" / "weekly" / "2026-W16.md"
        self.assertTrue(main_weekly.is_file())
        self.assertTrue(crypto_weekly.is_file())
        main_content = main_weekly.read_text(encoding="utf-8")
        self.assertIn("type: journal_weekly", main_content)
        self.assertIn("week: 2026-W16", main_content)

        # Now add a THIRD agent with content and rerun — it must be
        # covered with zero code/config changes.
        _seed_agent(self.vault, "late-comer")
        _seed_journal_day(
            self.vault / "late-comer", "2026-04-17",
            [("11:00", "late arrival entry about coconuts")],
        )
        vault_index.rebuild(self.vault, self.db)
        result2 = self._run_script(today)
        self.assertEqual(result2.returncode, 0)
        self.assertIn("late-comer -> late-comer/Journal/weekly/2026-W16.md", result2.stdout)

    def test_agent_with_no_journal_entries_is_skipped(self) -> None:
        today = "2026-04-20"
        _seed_agent(self.vault, "main")
        _seed_agent(self.vault, "ghost")
        _seed_journal_day(self.vault / "main", "2026-04-15",
                          [("09:00", "content")])
        # ghost has no journal
        vault_index.rebuild(self.vault, self.db)
        result = self._run_script(today)
        self.assertEqual(result.returncode, 0)
        self.assertIn("ghost — no journal content", result.stdout)
        self.assertFalse(
            (self.vault / "ghost" / "Journal" / "weekly" / "2026-W16.md").exists()
        )

    def test_rollup_indexed_for_immediate_search(self) -> None:
        """After the driver runs, the new weekly file is already in the FTS
        index — searching for the placeholder marker finds it."""
        today = "2026-04-20"
        _seed_agent(self.vault, "main")
        _seed_journal_day(self.vault / "main", "2026-04-15",
                          [("09:00", "some real content")])
        vault_index.rebuild(self.vault, self.db)
        result = self._run_script(today)
        self.assertEqual(result.returncode, 0)

        conn = vault_index.connect(self.db)
        try:
            # The test placeholder contains "test-mode" — should be findable
            hits = vault_index.search(conn, "main", "test-mode")
            self.assertGreaterEqual(len(hits), 1)
            weekly_hits = [h for h in hits if h.kind == vault_index.KIND_JOURNAL_WEEKLY]
            self.assertEqual(len(weekly_hits), 1)
            self.assertEqual(weekly_hits[0].rel_path, "main/Journal/weekly/2026-W16.md")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
