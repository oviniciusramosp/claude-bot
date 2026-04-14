#!/usr/bin/env python3
"""
vault-index-update.py — daily rebuild of the FTS5 vault index.

Invoked by the ``vault-index-update`` routine (04:05 daily, staggered
after ``vault-graph-update`` at 04:00 so the two never race). Can also
be run by hand from the repo root::

    python3 scripts/vault-index-update.py

Exit codes (for the routine's failure reporting):
  0 — rebuild succeeded
  2 — vault directory not found (install/config issue)
  3 — rebuild raised an exception

Per ``.claude/rules/bot-code-conventions.md`` (zero silent errors), any
failure surfaces on stderr with full context so the routine writes it
to Telegram.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import vault_index  # noqa: E402


def _resolve_vault_dir() -> Path:
    """Match the bot's VAULT_DIR resolution: env override, else <repo>/vault."""
    env = os.environ.get("CLAUDE_BOT_VAULT")
    if env:
        return Path(env).resolve()
    return (REPO_ROOT / "vault").resolve()


def _resolve_db_path() -> Path:
    env = os.environ.get("CLAUDE_BOT_INDEX_DB")
    if env:
        return Path(env).resolve()
    return Path.home() / ".claude-bot" / "vault-index.sqlite"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=None,
                        help="Vault root (default: env CLAUDE_BOT_VAULT or <repo>/vault)")
    parser.add_argument("--db", type=Path, default=None,
                        help="Index DB path (default: ~/.claude-bot/vault-index.sqlite)")
    parser.add_argument("--quiet", action="store_true",
                        help="Only print the stats line; suppress the INFO header")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    vault_dir = (args.vault or _resolve_vault_dir()).resolve()
    db_path = (args.db or _resolve_db_path()).resolve()

    if not vault_dir.is_dir():
        sys.stderr.write(
            f"ERROR: vault directory not found: {vault_dir}\n"
            f"Set CLAUDE_BOT_VAULT or pass --vault <path>.\n"
        )
        return 2

    if not args.quiet:
        sys.stdout.write(f"vault-index-update: vault={vault_dir} db={db_path}\n")
        sys.stdout.flush()

    try:
        stats = vault_index.rebuild(vault_dir, db_path)
    except Exception as exc:  # Any error surfaces to Telegram via routine
        sys.stderr.write(f"ERROR: rebuild failed: {exc}\n")
        traceback.print_exc(file=sys.stderr)
        return 3

    sys.stdout.write(
        f"vault-index-update: {stats.rows_inserted} rows, "
        f"{len(stats.agents)} agents ({', '.join(stats.agents)}), "
        f"{stats.duration_ms:.0f}ms\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
