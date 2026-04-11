"""
Tests for scripts/migrate_vault_per_agent.py (v3.1 target layout).

Covers three migration paths:
  1. Legacy (pre-v3) → v3.1 — top-level `Skills/Routines/…` + optional
     `Agents/<id>/` is moved into `<id>/` + merged into `agent-info.md`.
  2. v3.0 intermediate → v3.1 — `Agents/<id>/` gets unwrapped to `<id>/`
     and the hub + metadata files are merged into `agent-info.md`.
  3. Fresh install → v3.1 — no legacy content; `main/` is seeded from
     `templates/main/`.
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

_spec = importlib.util.spec_from_file_location(
    "migrate_vault_per_agent",
    SCRIPTS_DIR / "migrate_vault_per_agent.py",
)
assert _spec and _spec.loader
migrate = importlib.util.module_from_spec(_spec)
sys.path.insert(0, str(SCRIPTS_DIR))
_spec.loader.exec_module(migrate)  # type: ignore[union-attr]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_legacy_vault(vault: Path) -> None:
    """Pre-v3 layout — top-level Skills/Routines/Journal/ plus Agents/<id>/."""
    vault.mkdir(parents=True, exist_ok=True)
    _write(vault / "CLAUDE.md", "# Vault rules\n")
    _write(vault / "README.md", "# Vault README\n")
    _write(vault / "Tooling.md", "# Tooling\n")

    _write(
        vault / "Skills" / "Skills.md",
        "---\ntitle: Skills\ndescription: Index\ntype: index\n---\n\n- [[example]]\n",
    )
    _write(
        vault / "Skills" / "example.md",
        "---\ntitle: Example\ndescription: Example skill\ntype: skill\n---\n\n## Steps\n1. do a thing\n",
    )

    _write(
        vault / "Routines" / "Routines.md",
        "---\ntitle: Routines\ndescription: Index\ntype: index\n---\n",
    )
    _write(
        vault / "Routines" / "daily-check.md",
        "---\ntitle: Daily Check\ndescription: Run every day\ntype: routine\n"
        "schedule:\n  times: [\"09:00\"]\n  days: [\"*\"]\nmodel: sonnet\nenabled: true\n---\n\n"
        "[[Routines]]\n\nCheck stuff.\n",
    )
    _write(
        vault / "Routines" / "crypto-news.md",
        "---\ntitle: Crypto News\ndescription: Pipeline\ntype: pipeline\n"
        "schedule:\n  times: [\"09:00\"]\n  days: [\"*\"]\nmodel: sonnet\n"
        "agent: crypto-bro\nenabled: true\n---\n\n[[Routines]]\n\n"
        "```pipeline\nsteps:\n  - id: scout\n    prompt_file: steps/scout.md\n```\n",
    )
    _write(vault / "Routines" / "crypto-news" / "steps" / "scout.md", "Collect news.\n")

    _write(
        vault / "Journal" / "Journal.md",
        "---\ntitle: Journal\ndescription: Index\ntype: index\n---\n",
    )
    _write(
        vault / "Journal" / "2026-04-10.md",
        "---\ntitle: \"Journal 2026-04-10\"\ndescription: Daily log\ntype: journal\n---\n\n## 10:00 — ok\n",
    )
    _write(vault / "Journal" / ".activity" / "2026-04-10.jsonl", '{"ts":"...","event":"x"}\n')

    _write(
        vault / "Reactions" / "test-webhook.md",
        "---\ntitle: Test Webhook\ndescription: A test\ntype: reaction\n---\n\nBody\n",
    )
    _write(
        vault / "Lessons" / "Lessons.md",
        "---\ntitle: Lessons\ndescription: Index\ntype: index\n---\n",
    )
    _write(
        vault / "Notes" / "Notes.md",
        "---\ntitle: Notes\ndescription: Index\ntype: index\n---\n",
    )

    # Pre-v3 agents live under Agents/ with agent.md + <id>.md
    _write(vault / "Agents" / "Agents.md", "---\ntitle: Agents\ndescription: Index\ntype: index\n---\n")
    _write(
        vault / "Agents" / "crypto-bro" / "agent.md",
        "---\ntitle: Crypto Bro\ndescription: Crypto specialist\ntype: agent\nname: crypto-bro\nmodel: sonnet\nicon: \"🟠\"\n---\n",
    )
    _write(
        vault / "Agents" / "crypto-bro" / "CLAUDE.md",
        "# Crypto Bro 🟠\n\n## Personality\nSharp.\n",
    )
    _write(vault / "Agents" / "crypto-bro" / "crypto-bro.md", "\n")
    _write(
        vault / "Agents" / "crypto-bro" / "Journal" / "2026-04-10.md",
        "---\ntitle: \"Journal 2026-04-10\"\ndescription: Daily\ntype: journal\n---\n\n## 12:00 — ok\n",
    )


def _build_fresh_vault(vault: Path) -> None:
    """Empty vault — just the three shared files, no agents, no legacy content."""
    vault.mkdir(parents=True, exist_ok=True)
    _write(vault / "CLAUDE.md", "# Vault rules\n")
    _write(vault / "README.md", "# Vault README\n")
    _write(vault / "Tooling.md", "# Tooling\n")


def _build_v30_vault(vault: Path) -> None:
    """v3.0 intermediate layout — everything under Agents/<id>/."""
    vault.mkdir(parents=True, exist_ok=True)
    _write(vault / "CLAUDE.md", "# Vault rules\n")
    _write(vault / "README.md", "# Vault README\n")
    _write(vault / "Tooling.md", "# Tooling\n")

    for agent in ("main", "crypto-bro"):
        base = vault / "Agents" / agent
        _write(
            base / "agent.md",
            f"---\ntitle: {agent}\ndescription: {agent}\ntype: agent\nname: {agent}\nmodel: sonnet\nicon: \"🤖\"\n---\n",
        )
        _write(base / "CLAUDE.md", f"# {agent}\n")
        _write(base / f"{agent}.md", "---\ntitle: hub\ndescription: hub\ntype: note\n---\n\n[[Skills]]\n")
        _write(
            base / "Skills" / "Skills.md",
            "---\ntitle: Skills\ndescription: Index\ntype: index\n---\n",
        )
        _write(
            base / "Routines" / "Routines.md",
            "---\ntitle: Routines\ndescription: Index\ntype: index\n---\n",
        )
        _write(
            base / "Journal" / "Journal.md",
            "---\ntitle: Journal\ndescription: Index\ntype: index\n---\n",
        )
    _write(
        vault / "Agents" / "main" / "Skills" / "shared-skill.md",
        "---\ntitle: Shared\ndescription: main skill\ntype: skill\n---\n\n## Steps\n",
    )


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vault-migrate-legacy-")
        self.vault = Path(self.tmp) / "vault"
        _build_legacy_vault(self.vault)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_main_agent_lives_at_root(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        main = self.vault / "main"
        self.assertTrue(main.is_dir())
        self.assertTrue((main / "agent-main.md").is_file())
        self.assertTrue((main / "CLAUDE.md").is_file())
        for sub in ("Skills", "Routines", "Journal", "Reactions", "Lessons", "Notes", ".workspace"):
            self.assertTrue((main / sub).is_dir(), f"{sub} missing under main")
        # v3.5: plain-name ``workspace/`` must NOT exist — the dot-prefix is now
        # the canonical name so Obsidian's dotfile filter hides pipeline runtime
        # data from the graph view automatically.
        self.assertFalse((main / "workspace").exists())
        self.assertTrue((main / "Journal" / ".activity").is_dir())
        # The wrapper dir is gone.
        self.assertFalse((self.vault / "Agents").exists())

    def test_agent_info_has_frontmatter_and_hub_links(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        info = (self.vault / 'main' / 'agent-main.md').read_text(encoding="utf-8")
        self.assertIn("type: agent", info)
        # v3.3: agent-info points DOWN to its sub-indexes via path-qualified
        # wikilinks (`<agent>/<Sub>/agent-<sub>`).
        self.assertIn("main/Skills/agent-skills", info)
        self.assertIn("main/Routines/agent-routines", info)
        self.assertIn("main/Journal/agent-journal", info)
        self.assertIn("main/Reactions/agent-reactions", info)
        self.assertIn("main/Lessons/agent-lessons", info)
        self.assertIn("main/Notes/agent-notes", info)

    def test_skills_moved_from_legacy_location(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        self.assertTrue((self.vault / "main" / "Skills" / "example.md").is_file())
        self.assertFalse((self.vault / "Skills").exists())

    def test_routines_routed_by_frontmatter(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        self.assertTrue((self.vault / "main" / "Routines" / "daily-check.md").is_file())
        self.assertTrue((self.vault / "crypto-bro" / "Routines" / "crypto-news.md").is_file())
        self.assertTrue((self.vault / "crypto-bro" / "Routines" / "crypto-news" / "steps" / "scout.md").is_file())
        self.assertFalse((self.vault / "Routines").exists())

    def test_named_agents_get_new_scaffolding(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        crypto = self.vault / "crypto-bro"
        self.assertTrue(crypto.is_dir())
        self.assertTrue((crypto / "agent-crypto-bro.md").is_file())
        self.assertTrue((crypto / "CLAUDE.md").is_file())
        # Metadata from old agent.md should have been carried into the new hub.
        self.assertIn("name: crypto-bro", (crypto / "agent-crypto-bro.md").read_text(encoding="utf-8"))
        # Existing Journal entries are preserved.
        self.assertTrue((crypto / "Journal" / "2026-04-10.md").is_file())

    def test_journal_activity_moved(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        self.assertTrue((self.vault / "main" / "Journal" / ".activity" / "2026-04-10.jsonl").is_file())

    def test_backup_is_created(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        backups = [p for p in self.vault.parent.iterdir() if p.name.startswith("vault.backup-")]
        self.assertEqual(len(backups), 1)
        self.assertTrue((backups[0] / "Skills" / "example.md").is_file())


class FreshInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vault-migrate-fresh-")
        self.vault = Path(self.tmp) / "vault"
        _build_fresh_vault(self.vault)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_main_seeded_from_templates(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        main = self.vault / "main"
        self.assertTrue(main.is_dir())
        self.assertTrue((main / "agent-main.md").is_file())
        self.assertTrue((main / "CLAUDE.md").is_file())
        # At least one starter skill from templates should land.
        skills = list((main / "Skills").glob("*.md"))
        self.assertGreater(len(skills), 1, "fresh install should seed starter skills")


class V30UpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vault-migrate-v30-")
        self.vault = Path(self.tmp) / "vault"
        _build_v30_vault(self.vault)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_agents_unwrapped_and_merged(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        self.assertFalse((self.vault / "Agents").exists())
        self.assertTrue((self.vault / 'main' / 'agent-main.md').is_file())
        self.assertTrue((self.vault / 'crypto-bro' / 'agent-crypto-bro.md').is_file())
        # Old files are gone
        self.assertFalse((self.vault / "main" / "agent.md").exists())
        self.assertFalse((self.vault / "main" / "main.md").exists())
        self.assertFalse((self.vault / "crypto-bro" / "crypto-bro.md").exists())
        # Content preserved
        self.assertTrue((self.vault / "main" / "Skills" / "shared-skill.md").is_file())

    def test_agent_info_has_metadata_from_old_agent_md(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        info = (self.vault / 'crypto-bro' / 'agent-crypto-bro.md').read_text(encoding="utf-8")
        self.assertIn("name: crypto-bro", info)
        self.assertIn("🤖", info)


class GuardRailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vault-migrate-guard-")
        self.vault = Path(self.tmp) / "vault"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_aborts_if_already_v31(self) -> None:
        (self.vault / "main").mkdir(parents=True)
        _write(
            self.vault / 'main' / 'agent-main.md',
            "---\ntitle: main\ndescription: x\ntype: agent\n---\n\n[[Skills]]\n",
        )
        with self.assertRaises(SystemExit):
            migrate.migrate_vault(self.vault, dry_run=False)

    def test_aborts_if_vault_missing(self) -> None:
        with self.assertRaises(SystemExit):
            migrate.migrate_vault(self.vault.parent / "does-not-exist", dry_run=False)

    def test_dry_run_changes_nothing(self) -> None:
        _build_legacy_vault(self.vault)
        before = sorted(str(p.relative_to(self.vault)) for p in self.vault.rglob("*"))
        migrate.migrate_vault(self.vault, dry_run=True)
        after = sorted(str(p.relative_to(self.vault)) for p in self.vault.rglob("*"))
        self.assertEqual(before, after)
        backups = [p for p in self.vault.parent.iterdir() if p.name.startswith("vault.backup-")]
        self.assertEqual(backups, [])


class V35WorkspaceRenameTests(unittest.TestCase):
    """v3.5 cleanup path — already in v3.1 but has legacy `workspace/` dirs."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="vault-migrate-v35-")
        self.vault = Path(self.tmp) / "vault"
        self.vault.mkdir(parents=True)
        _write(self.vault / "CLAUDE.md", "# Vault rules\n")
        _write(self.vault / "README.md", "# Vault README\n")
        # Two v3.1 agents with legacy workspace dirs.
        for agent_id in ("main", "crypto-bro"):
            base = self.vault / agent_id
            _write(
                base / f"agent-{agent_id}.md",
                f"---\ntitle: {agent_id}\ndescription: test\ntype: agent\nname: {agent_id}\nmodel: sonnet\n---\n",
            )
            _write(base / "CLAUDE.md", f"# {agent_id}\n")
            for sub in ("Skills", "Routines", "Journal", "Reactions", "Lessons", "Notes"):
                (base / sub).mkdir(parents=True, exist_ok=True)
            # Legacy plain-name workspace with a data file
            _write(base / "workspace" / "data" / "example" / "step.md", "step output\n")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detects_v35_pending(self) -> None:
        self.assertEqual(migrate._detect_layout(self.vault), "v35_pending")

    def test_renames_workspace_to_dotprefixed(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        for agent_id in ("main", "crypto-bro"):
            base = self.vault / agent_id
            self.assertFalse((base / "workspace").exists(),
                             f"{agent_id}: legacy workspace/ still present")
            self.assertTrue((base / ".workspace").is_dir(),
                            f"{agent_id}: .workspace/ missing")
            self.assertTrue((base / ".workspace" / "data" / "example" / "step.md").is_file(),
                            f"{agent_id}: pipeline data lost during rename")

    def test_dry_run_does_not_rename(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=True)
        for agent_id in ("main", "crypto-bro"):
            self.assertTrue((self.vault / agent_id / "workspace").is_dir())
            self.assertFalse((self.vault / agent_id / ".workspace").exists())

    def test_idempotent_after_rename(self) -> None:
        migrate.migrate_vault(self.vault, dry_run=False)
        # Second run should now see v31 layout — no legacy workspace/ remains.
        self.assertEqual(migrate._detect_layout(self.vault), "v31")

    def test_merges_when_both_exist(self) -> None:
        # Pre-create both legacy and new dirs with different files.
        base = self.vault / "main"
        _write(base / ".workspace" / "data" / "example" / "existing.md", "existing\n")
        migrate.migrate_vault(self.vault, dry_run=False)
        self.assertTrue((base / ".workspace" / "data" / "example" / "existing.md").is_file())
        self.assertTrue((base / ".workspace" / "data" / "example" / "step.md").is_file())
        self.assertFalse((base / "workspace").exists())


if __name__ == "__main__":
    unittest.main()
