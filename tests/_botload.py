"""Helpers to import claude-fallback-bot.py as a module under a tmp data dir.

The bot script lives at the repo root with a hyphen in its name and touches
~/.claude-bot at import time. To make tests hermetic we:

1. Set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID env vars before import so the
   .env loader doesn't try to use the developer's real credentials.
2. Point HOME at a tmp dir so DATA_DIR (~/.claude-bot) lands in the sandbox.
3. Use importlib to load the hyphenated file as the module name `bot`.
4. Optionally re-point a few module-level Path globals to a tmp tree after
   import (the bot does some VAULT_DIR work that touches the real vault by
   default — tests that exercise routines should override these).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
BOT_FILE = REPO_ROOT / "claude-fallback-bot.py"


def load_bot_module(tmp_home: Path | None = None, vault_dir: Path | None = None) -> Any:
    """Import the bot script as a fresh module.

    Each call loads a fresh module instance so tests cannot bleed module-level
    state into each other. The caller is responsible for cleaning up any
    side effects (files written under tmp_home/vault_dir).
    """
    if tmp_home is None:
        tmp_home = Path(tempfile.mkdtemp(prefix="claude-bot-test-"))

    # Force credentials BEFORE import so .env loader skips real values
    os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
    os.environ["TELEGRAM_CHAT_ID"] = "123456789"
    os.environ["HOME"] = str(tmp_home)
    # Point CLAUDE_WORKSPACE somewhere safe so the bot doesn't pick the real vault
    if vault_dir is not None:
        os.environ["CLAUDE_WORKSPACE"] = str(vault_dir)

    spec = importlib.util.spec_from_file_location("bot_under_test", str(BOT_FILE))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load spec for {BOT_FILE}")
    module = importlib.util.module_from_spec(spec)
    # Register so dataclasses / pickle / etc. can find it if needed
    sys.modules["bot_under_test"] = module
    spec.loader.exec_module(module)

    # Each import re-creates the "claude-bot" logger handlers — silence test
    # noise by clearing them after the module sets itself up. We CLOSE the
    # file handler explicitly so the rotating-file fd doesn't leak as a
    # ResourceWarning. Tests that need to capture log output can re-add a
    # handler explicitly.
    import logging as _logging
    _bot_logger = _logging.getLogger("claude-bot")
    for _h in list(_bot_logger.handlers):
        try:
            _h.close()
        except Exception:
            pass
        _bot_logger.removeHandler(_h)
    _bot_logger.addHandler(_logging.NullHandler())
    _bot_logger.propagate = False

    # Repoint module-level paths into the tmp tree so per-test side effects
    # are confined. Mkdir to keep the bot's helpers happy.
    data_dir = tmp_home / ".claude-bot"
    module.DATA_DIR = data_dir
    module.SESSIONS_FILE = data_dir / "sessions.json"
    module.CONTEXTS_FILE = data_dir / "contexts.json"
    module.LOG_FILE = data_dir / "bot.log"
    module.ROUTINES_STATE_DIR = data_dir / "routines-state"
    module.COSTS_FILE = data_dir / "costs.json"
    module.CONTROL_TOKEN_FILE = data_dir / ".control-token"
    module.PIPELINE_ACTIVITY_FILE = data_dir / "pipeline-activity.json"
    module.REACTION_SECRETS_FILE = data_dir / "reaction-secrets.json"
    if vault_dir is not None:
        module.VAULT_DIR = vault_dir
        module.ROUTINES_DIR = vault_dir / "Routines"
        module.AGENTS_DIR = vault_dir / "Agents"
        module.REACTIONS_DIR = vault_dir / "Reactions"
        module.ACTIVITY_LOG_DIR = vault_dir / "Journal" / ".activity"
        module.CLAUDE_WORKSPACE = str(vault_dir)
        for d in (
            vault_dir,
            vault_dir / "Routines",
            vault_dir / "Agents",
            vault_dir / "Reactions",
            vault_dir / "Journal" / ".activity",
        ):
            d.mkdir(parents=True, exist_ok=True)
    for d in (data_dir, data_dir / "routines-state"):
        d.mkdir(parents=True, exist_ok=True)
    return module
