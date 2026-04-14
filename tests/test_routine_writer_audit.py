"""Static audit — every source file that mentions ``Routines`` and has a
file-write operation must be reviewed.

Why this exists: the user deleted a ``Test`` routine multiple times and it
kept coming back because a test fixture was silently recreating it after
each run. The test-level fix and ``test_vault_isolation`` cover the test
side. This audit is the **runtime-code side** — it fails if anyone adds new
code (Python bot, macOS app, scripts, MCP server) that could write into a
Routines path without a conscious review. Routines must only be created by
deliberate user actions (Swift `saveRoutine`, the Telegram `/routine new`
flow, scheduled index regeneration, one-time migrations). Anything silent
that fires at startup is the bug class we want to block at PR time.

How it works: scan every ``.py`` and ``.swift`` file outside test directories.
Flag a file if it (1) mentions the string ``Routines`` *and* (2) contains
file-write operations. This is a coarse file-level check — it over-fires on
files that touch Routines for read/query purposes while writing something
else entirely (Journal, Notes, `.env`, stderr). That's OK: every flagged
file goes into ``REVIEWED_FILES`` below with a one-line reason. Two
categories live in the same set with different notes:

  - ``writes:``    file really does write ``<agent>/Routines/*.md`` files.
                  Must be either user-initiated, scheduled, or a one-off.
  - ``no-write:``  file mentions Routines but writes something else; the
                  audit over-fires but the file is safe.

If a file not in ``REVIEWED_FILES`` shows up in the audit output, review it:
add it to the set with the right tag, or fix the code if it silently
creates routine files at startup.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from tests._botload import REPO_ROOT

# Every source file that could trip this audit has been reviewed and recorded
# below. Tag prefix is mandatory:
#
#   "writes: ..."    — file really writes <agent>/Routines/*.md. The reason
#                       must explain WHY the write is safe (user action,
#                       scheduled job, one-off migration).
#   "no-write: ..."  — file mentions Routines for read/query purposes but
#                       writes only non-routine files (journal, notes, env,
#                       stderr). The audit over-fires; keeping the entry
#                       documents the review.
#
# If you add a new entry, first ask: can this writer fire unprompted at
# bot/app startup? If yes, it's the bug this guard exists to prevent — fix
# the code, don't add it here.
REVIEWED_FILES: dict[str, str] = {
    # --- Real routine writers -------------------------------------------
    "claude-fallback-bot.py":
        "writes: Routines/.history/YYYY-MM.md execution rollup "
        "(fires only after a routine actually runs, never at startup)",

    "ClaudeBotManager/Sources/Services/VaultService.swift":
        "writes: saveRoutine() user action (Save button in RoutineFormSheet "
        "/ RoutineDetailView) + agent-routines.md index updates",

    # Note: scripts/vault_indexes.py is NOT listed because it does not
    # mention the string "Routines" anywhere — it regenerates marker blocks
    # generically across every index file. The audit scanner correctly skips
    # it; if that file ever grows Routines-specific code, it will land here
    # automatically for review.

    "scripts/migrate_vault_per_agent.py":
        "writes: v3.1 flat-layout migration, one-shot manual invocation",

    # --- Over-fire false positives --------------------------------------
    "claude-bot-menubar.py":
        "no-write: writes only the launchd plist with HOME substitutions; "
        "mentions Routines in the 'Routines today:' UI label",

    "mcp-server/vault_mcp_server.py":
        "no-write: vault_upsert_note writes Notes/*.md and "
        "vault_append_journal writes Journal/*.md; mentions Routines in "
        "tool docstrings and graph queries but never touches Routines/",

    "scripts/vault_graph_query.py":
        "no-write: writes only to stderr for CLI help text; the help text "
        "mentions 'Routines/crypto-news.md' as an example path",

    "scripts/vault-graph-builder.py":
        "no-write: writes only .graphs/graph.json; walks Routines/ for reads "
        "to populate graph nodes/edges",

    "ClaudeBotManager/Sources/App/AppState.swift":
        "no-write: writes ~/claude-bot/.env and vault/.env (botConfig and "
        "vaultEnv save flows); mentions Routines in saveRoutine/loadRoutines "
        "delegates that forward to VaultService",
}

# Directory path-parts to skip entirely when walking the repo. Both lower
# and capital forms are listed because Python uses lower-case ``tests/`` and
# Swift uses capital ``Tests/`` by convention.
IGNORED_PARTS = {
    ".build",      # Swift build artifacts
    ".git",
    ".venv",
    ".claude",     # skill/plan metadata, no source code
    "tests",       # Python tests — covered by test_vault_isolation
    "Tests",       # Swift tests (ClaudeBotManager/Tests/...)
    "vault",       # the data itself, not code
    "node_modules",
    "__pycache__",
    ".pytest_cache",
}

# Tokens that identify a file-write operation in Python or Swift source.
WRITE_TOKENS = (
    "write_text",   # Python: Path.write_text(...)
    ".write(",      # Python: fd.write(...) OR Swift: String.write(to: ...)
    "write(to:",    # Swift: Data.write(to: ...)
)


def _looks_like_comment(stripped: str) -> bool:
    return stripped.startswith("#") or stripped.startswith("//") or stripped.startswith("*")


def _scan_source_file(path: Path) -> list[int]:
    """Return line numbers where this file writes something AND also mentions
    ``Routines`` somewhere (file-level check).

    We return the write-operation line numbers so the failure message can
    point at them, but the gate is file-level: a file is flagged only if it
    has BOTH write ops AND a Routines mention. False positives land in the
    allow-list; there is no attempt to disambiguate at line level.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    if "Routines" not in text:
        return []

    write_lines: list[int] = []
    for i, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or _looks_like_comment(stripped):
            continue
        if any(tok in raw for tok in WRITE_TOKENS):
            write_lines.append(i)
    return write_lines


def _iter_source_files(repo: Path):
    for ext in ("*.py", "*.swift"):
        for path in repo.rglob(ext):
            rel_parts = path.relative_to(repo).parts
            if any(part in IGNORED_PARTS for part in rel_parts):
                continue
            yield path


class RoutineWriterAuditTest(unittest.TestCase):
    """Fails if any source file that touches Routines + writes is not reviewed."""

    def test_every_touching_file_is_reviewed(self) -> None:
        repo = REPO_ROOT.resolve()
        unreviewed: list[str] = []
        for src in _iter_source_files(repo):
            rel_str = str(src.relative_to(repo))
            write_lines = _scan_source_file(src)
            if not write_lines:
                continue
            if rel_str in REVIEWED_FILES:
                continue
            shown = ", ".join(str(n) for n in write_lines[:5])
            more = f" (+{len(write_lines) - 5} more)" if len(write_lines) > 5 else ""
            unreviewed.append(f"  {rel_str}: write ops at lines {shown}{more}")

        if unreviewed:
            self.fail(
                "New source file touching Routines + file writes detected.\n"
                "\n"
                "This audit guards against silent routine creation at bot/app\n"
                "startup (the class of bug that made `Test` routine keep\n"
                "reappearing after the user deleted it). Any source file that\n"
                "mentions `Routines` AND contains file-write operations must\n"
                "be explicitly reviewed and listed in REVIEWED_FILES inside\n"
                "tests/test_routine_writer_audit.py.\n"
                "\n"
                "For each file below, review and then either:\n"
                "  (a) Add it with `writes: ...` if it legitimately writes\n"
                "      <agent>/Routines/*.md (explain WHY it is safe: user\n"
                "      action, scheduled job, or one-off migration).\n"
                "  (b) Add it with `no-write: ...` if it only mentions\n"
                "      Routines for read/query purposes and writes something\n"
                "      else entirely (journal, env, stderr, graph).\n"
                "  (c) FIX THE CODE if the write can fire unprompted at\n"
                "      startup — do NOT add it to REVIEWED_FILES.\n"
                "\n"
                "Files:\n" + "\n".join(unreviewed)
            )

    def test_reviewed_entries_still_match(self) -> None:
        """Keeps REVIEWED_FILES from accumulating dead entries.

        If a file is listed but no longer matches the audit scanner (file
        deleted, Routines mention removed, writes removed), the entry is
        stale and should be pruned.
        """
        repo = REPO_ROOT.resolve()
        stale: list[str] = []
        for rel_str in REVIEWED_FILES:
            src = repo / rel_str
            if not src.is_file():
                stale.append(f"  {rel_str} (file does not exist)")
                continue
            if not _scan_source_file(src):
                stale.append(f"  {rel_str} (no matching write — audit would skip it anyway)")
        if stale:
            self.fail(
                "Stale REVIEWED_FILES entries in test_routine_writer_audit.py:\n"
                + "\n".join(stale)
                + "\nRemove them so the review surface stays minimal."
            )

    def test_reviewed_entry_tags_are_valid(self) -> None:
        """Every REVIEWED_FILES reason must start with a known tag."""
        bad: list[str] = []
        for rel_str, reason in REVIEWED_FILES.items():
            if not (reason.startswith("writes:") or reason.startswith("no-write:")):
                bad.append(f"  {rel_str}: {reason!r}")
        if bad:
            self.fail(
                "REVIEWED_FILES entries must start with 'writes:' or "
                "'no-write:' so the intent is obvious at review time.\n"
                + "\n".join(bad)
            )


if __name__ == "__main__":
    unittest.main()
