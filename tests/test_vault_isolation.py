"""Regression guard — the test suite must not create new files in the real vault.

Background: two ``test_restart_recovery`` classes used to call
``load_bot_module(tmp_home=...)`` without passing ``vault_dir=``. The harness
would leave ``module.VAULT_DIR`` pointing at the real repo vault
(``claude-bot/vault/``), and their setUp would write fixtures
(``test-routine.md``, ``agent-info.md``) straight into it. The files survived
tearDown and kept reappearing for the user, who mistook it for a startup bug
in the bot or the macOS app.

Strategy: ``unittest.TestLoader.discover()`` imports every test module before
running any test. We capture the set of vault file paths at **module import
time** (the ``_BASELINE_PATHS`` assignment below), then compare at test time.
Because the snapshot is taken during import — before any other test's body
has run — it captures the true pre-suite state regardless of alphabetical
test order.

We deliberately only flag **new** or **removed** paths, NOT mtime changes on
existing files. Rationale: the user normally runs ``./test.sh`` with the bot
running in the background, and that bot rewrites several vault files on a
schedule (``agent-journal.md`` indexes, ``.graphs/graph.json``, etc.). Mtime
changes on existing files would false-positive all the time. The bug class
we care about — tests creating fresh fixture files — always shows up as a
**new** path, so the set-based check is both sufficient and stable.

If a future test forgets ``vault_dir=`` and writes into the real vault, this
fails loudly with the exact path that leaked.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tests._botload import REPO_ROOT

VAULT_ROOT = (REPO_ROOT / "vault").resolve()


def _snapshot_vault_paths() -> set[str]:
    """Return the set of relative file paths under vault/ (excluding cache dirs)."""
    paths: set[str] = set()
    if not VAULT_ROOT.is_dir():
        return paths
    for p in VAULT_ROOT.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(VAULT_ROOT)
        parts = rel.parts
        # Skip scratch/cache directories the bot or Obsidian touches on its
        # own schedule — we care about files under agent folders.
        if parts and parts[0] in {".obsidian", ".graphs", ".DS_Store"}:
            continue
        # Skip activity logs written by the bot's interactive session loop.
        if len(parts) >= 3 and parts[1] == "Journal" and parts[2] == ".activity":
            continue
        # Skip pipeline workspace scratch (routine outputs).
        if len(parts) >= 2 and parts[1] == ".workspace":
            continue
        paths.add(str(rel))
    return paths


# Captured at import time, before unittest runs ANY test body. unittest
# discover imports all test modules up-front, so this is a faithful snapshot
# of the pre-suite vault state.
_BASELINE_PATHS: set[str] = _snapshot_vault_paths()


class VaultIsolationTests(unittest.TestCase):
    """Fails if new files appeared or disappeared under the real repo vault."""

    def test_no_new_files_under_real_vault(self) -> None:
        current = _snapshot_vault_paths()
        added = sorted(current - _BASELINE_PATHS)
        removed = sorted(_BASELINE_PATHS - current)

        if added or removed:
            lines = [
                "Test suite mutated the real repo vault — likely a test called",
                "load_bot_module() without vault_dir=... See _botload.py.",
                f"  vault root: {VAULT_ROOT}",
            ]
            if added:
                lines.append("  new files:")
                lines.extend(f"    + {p}" for p in added)
            if removed:
                lines.append("  removed files:")
                lines.extend(f"    - {p}" for p in removed)
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
