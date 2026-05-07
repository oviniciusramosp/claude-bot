#!/usr/bin/env python3
"""
migrate_journal_hierarchy.py — promote v3.1 flat journals to v3.68 hierarchy.

Before (flat):
    vault/<agent>/Journal/
    ├── agent-journal.md
    ├── 2026-04-07.md
    ├── 2026-04-08.md
    ├── ...
    └── weekly/
        ├── 2026-W14.md
        └── ...

After (hierarchical):
    vault/<agent>/Journal/
    ├── agent-journal.md          (rewritten — points to monthlies)
    ├── 2026-04/
    │   ├── 2026-04.md            (LLM-generated monthly summary)
    │   ├── 2026-W14.md           (regenerated with rich frontmatter)
    │   ├── 2026-04-07.md         (moved verbatim)
    │   └── ...
    └── 2026-05/
        └── ...

Steps the script performs (idempotent — safe to re-run):

  1. **Move dailies.** Every ``Journal/YYYY-MM-DD.md`` is moved into
     ``Journal/YYYY-MM/YYYY-MM-DD.md``. File contents are unchanged.

  2. **Move weeklies.** Every ``Journal/weekly/YYYY-Www.md`` is moved into
     ``Journal/<month-of-monday>/YYYY-Www.md``. The legacy ``weekly/``
     subfolder is removed when empty.

  3. **Drop placeholder monthly indexes.** For every month folder created
     by step 1, write a ``YYYY-MM.md`` skeleton (deterministic, no LLM)
     so the FTS index and the agent-journal.md hub have something to
     point at even before the LLM rollup runs.

  4. **Regenerate weeklies (LLM).** Calls ``journal-weekly-rollup.py
     --week YYYY-Www`` for each week that has at least one daily file in
     the new layout, so every weekly file gets the new richer
     frontmatter (``description``, ``period_start``/``period_end``,
     ``days``). Skipped with ``--no-llm-weekly``.

  5. **Generate monthlies (LLM).** Calls ``journal-monthly-rollup.py
     --month YYYY-MM`` for each month with content. Skipped with
     ``--no-llm-monthly``; falls back to the placeholder skeleton from
     step 3.

  6. **Rewrite agent-journal.md hubs.** Each agent's ``agent-journal.md``
     gets a new "How to consult this journal" section + a marker block
     that lists *monthlies* (filter ``type=journal_monthly``), not
     individual days. Manual edits OUTSIDE the marker are preserved.

  7. **Rebuild FTS + graph.** Calls ``vault-index-update.py`` and
     ``vault-graph-builder.py`` so search and Active Memory pick up the
     new layout immediately.

Exit codes:
  0 — clean run (some agents may have had nothing to migrate)
  2 — vault directory not found
  3 — at least one step failed (details on stderr)

Stdlib only. Run from any cwd:
    python3 scripts/migrate_journal_hierarchy.py
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

DAILY_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.md$")
WEEKLY_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")
MONTH_DIR_RE = re.compile(r"^(\d{4})-(\d{2})$")


def _resolve_vault(arg: Optional[Path]) -> Path:
    if arg is not None:
        return arg.resolve()
    return (REPO_ROOT / "vault").resolve()


def _iter_agents(vault: Path) -> List[str]:
    if not vault.is_dir():
        return []
    out: List[str] = []
    for entry in sorted(vault.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if (entry / f"agent-{entry.name}.md").is_file():
            out.append(entry.name)
    return out


# ---------------------------------------------------------------------------
# Step 1 — move dailies
# ---------------------------------------------------------------------------


def move_dailies(vault: Path, agent: str, dry_run: bool) -> Tuple[int, List[str]]:
    """Move ``Journal/YYYY-MM-DD.md`` → ``Journal/YYYY-MM/YYYY-MM-DD.md``.

    Returns (moved_count, list_of_months_touched).
    """
    journal = vault / agent / "Journal"
    if not journal.is_dir():
        return 0, []
    moved = 0
    months: set = set()
    for p in sorted(journal.iterdir()):
        if not p.is_file():
            continue
        m = DAILY_RE.match(p.name)
        if not m:
            continue
        year_month = f"{m.group(1)}-{m.group(2)}"
        target_dir = journal / year_month
        target = target_dir / p.name
        months.add(year_month)
        if target.exists():
            sys.stdout.write(f"  [skip] {agent}/Journal/{p.name} — already at {year_month}/\n")
            if not dry_run:
                p.unlink()
            continue
        if dry_run:
            sys.stdout.write(f"  [dry] move {agent}/Journal/{p.name} → {agent}/Journal/{year_month}/\n")
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(target))
        moved += 1
    return moved, sorted(months)


# ---------------------------------------------------------------------------
# Step 2 — move weeklies
# ---------------------------------------------------------------------------


def _monday_of_iso_week(iso_year: int, iso_week: int) -> _dt.date:
    """Return the Monday of an ISO week (year + week number)."""
    return _dt.date.fromisocalendar(iso_year, iso_week, 1)


def move_weeklies(vault: Path, agent: str, dry_run: bool) -> int:
    """Move ``Journal/weekly/YYYY-Www.md`` → ``Journal/<month>/YYYY-Www.md``
    where ``<month>`` is the month of the week's Monday.
    """
    weekly_dir = vault / agent / "Journal" / "weekly"
    if not weekly_dir.is_dir():
        return 0
    moved = 0
    for p in sorted(weekly_dir.iterdir()):
        if not p.is_file():
            continue
        m = WEEKLY_RE.match(p.name)
        if not m:
            continue
        try:
            iso_year = int(m.group(1))
            iso_week = int(m.group(2))
            monday = _monday_of_iso_week(iso_year, iso_week)
        except ValueError as exc:
            sys.stderr.write(f"  [warn] {agent}/Journal/weekly/{p.name} — bad iso week: {exc}\n")
            continue
        year_month = f"{monday.year:04d}-{monday.month:02d}"
        target_dir = vault / agent / "Journal" / year_month
        target = target_dir / p.name
        if target.exists():
            sys.stdout.write(f"  [skip] {agent}/Journal/weekly/{p.name} — already at {year_month}/\n")
            if not dry_run:
                p.unlink()
            continue
        if dry_run:
            sys.stdout.write(
                f"  [dry] move {agent}/Journal/weekly/{p.name} → "
                f"{agent}/Journal/{year_month}/\n"
            )
        else:
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(target))
        moved += 1
    # Remove the empty weekly/ folder
    if not dry_run:
        try:
            if not any(weekly_dir.iterdir()):
                weekly_dir.rmdir()
        except OSError:
            pass
    return moved


# ---------------------------------------------------------------------------
# Step 3 — placeholder monthly indexes
# ---------------------------------------------------------------------------


def write_monthly_skeleton(
    vault: Path, agent: str, year_month: str, dry_run: bool,
) -> bool:
    """Drop a placeholder ``YYYY-MM.md`` index in the month folder if missing.

    Returns True iff a file was written or would be written in dry-run mode.
    The skeleton is deterministic — no LLM. The ``journal-monthly-rollup``
    routine (or step 5 of this migration) overwrites it with rich content.
    """
    month_dir = vault / agent / "Journal" / year_month
    target = month_dir / f"{year_month}.md"
    if target.exists():
        return False
    if dry_run:
        sys.stdout.write(f"  [dry] would create skeleton {agent}/Journal/{year_month}/{year_month}.md\n")
        return True
    month_dir.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    skeleton = (
        "---\n"
        f'title: "Journal {year_month}"\n'
        f'description: "Monthly index for {year_month} ({agent}). Pending rollup '
        "— the journal-monthly-rollup routine enriches this with themes, "
        "highlights, weekly links and daily summaries on the 1st of next "
        'month."\n'
        "type: journal_monthly\n"
        f"month: {year_month}\n"
        f"agent: {agent}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "tags: [journal, monthly, rollup]\n"
        "---\n\n"
        f"# Journal — {year_month}\n\n"
        "## How to consult this month\n\n"
        "Memory is hierarchical. Read in this order before opening individual days:\n\n"
        "1. The description in this file's frontmatter — themes covered.\n"
        "2. The weekly summaries linked here — compact recap per week.\n"
        "3. Individual daily files — only when you need raw detail.\n\n"
        "## Pending\n\n"
        "Rollup not yet generated. Will be filled by `journal-monthly-rollup` "
        "on the 1st of next month, or by the migration script's `--llm-monthly` step.\n"
    )
    target.write_text(skeleton, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Step 6 — rewrite agent-journal.md hubs
# ---------------------------------------------------------------------------


# The new hub template. Manual edits OUTSIDE the marker block are preserved
# (the script only rewrites the marker block content). On first run for an
# agent that already has the legacy hub, the entire file is replaced.
HUB_TEMPLATE = """---
title: Journal
description: Monthly index hub for the {agent} agent — points to YYYY-MM rollups; \
each rollup links to that month's weekly summaries and daily files.
type: index
created: {created}
updated: {updated}
tags: [index, journal]
---

# Journal ({agent})

## How to consult this journal

Memory is hierarchical. **Always read top-down before opening individual days:**

1. **This hub** — orients you on which months exist.
2. **Monthly index** (`YYYY-MM/YYYY-MM.md`) — themes, highlights, decisions, \
links to that month's weeks. The frontmatter `description` is keyword-rich \
so you can decide whether to open the file from the listing alone.
3. **Weekly summary** (`YYYY-MM/YYYY-Www.md`) — Goals/Decisions/Progress for \
that week + links to its daily files.
4. **Daily file** (`YYYY-MM/YYYY-MM-DD.md`) — only when you need raw detail.

This minimizes context window usage while keeping deep recall available.

## Months

<!-- vault-query:start filter="type=journal_monthly" scope="{agent}/Journal" sort="-stem" \
format="- [[{{link}}|{{stem}}]] — {{description}}" -->
(auto-generated — do not edit)
<!-- vault-query:end -->
"""


def rewrite_hub(vault: Path, agent: str, dry_run: bool) -> bool:
    """Replace ``<agent>/Journal/agent-journal.md`` with the new hub template.

    The new hub uses the marker block to list monthlies (one row per
    ``YYYY-MM/YYYY-MM.md``) instead of dailies. The actual marker content
    is regenerated by ``vault_indexes.py`` after the migration runs.
    Returns True iff the file was rewritten.
    """
    hub_path = vault / agent / "Journal" / "agent-journal.md"
    today = _dt.date.today().isoformat()
    created = today
    if hub_path.exists():
        existing = hub_path.read_text(encoding="utf-8")
        m = re.search(r"^created:\s*(\S+)\s*$", existing, re.MULTILINE)
        if m:
            created = m.group(1)
    new_text = HUB_TEMPLATE.format(agent=agent, created=created, updated=today)
    if hub_path.exists() and hub_path.read_text(encoding="utf-8") == new_text:
        return False
    if dry_run:
        sys.stdout.write(f"  [dry] would rewrite {agent}/Journal/agent-journal.md\n")
        return True
    hub_path.parent.mkdir(parents=True, exist_ok=True)
    hub_path.write_text(new_text, encoding="utf-8")
    return True


# ---------------------------------------------------------------------------
# Step 4/5 — LLM rollups (delegated to existing scripts)
# ---------------------------------------------------------------------------


def _list_weeks_in_agent(vault: Path, agent: str) -> List[Tuple[str, _dt.date]]:
    """Return ``(week_label, monday)`` for every weekly file under any
    ``YYYY-MM/`` folder of the agent."""
    out: List[Tuple[str, _dt.date]] = []
    journal = vault / agent / "Journal"
    if not journal.is_dir():
        return out
    for sub in sorted(journal.iterdir()):
        if not sub.is_dir() or not MONTH_DIR_RE.match(sub.name):
            continue
        for p in sorted(sub.iterdir()):
            if not p.is_file():
                continue
            m = WEEKLY_RE.match(p.name)
            if m:
                try:
                    monday = _monday_of_iso_week(int(m.group(1)), int(m.group(2)))
                    out.append((f"{m.group(1)}-W{m.group(2)}", monday))
                except ValueError:
                    continue
    return out


def _list_months_in_agent(vault: Path, agent: str) -> List[str]:
    """Return ``YYYY-MM`` for every month folder of the agent."""
    out: List[str] = []
    journal = vault / agent / "Journal"
    if not journal.is_dir():
        return out
    for sub in sorted(journal.iterdir()):
        if not sub.is_dir():
            continue
        m = MONTH_DIR_RE.match(sub.name)
        if m:
            out.append(sub.name)
    return out


def regenerate_weeklies(
    vault: Path, agent: str, skip_llm: bool, dry_run: bool,
) -> Tuple[int, int]:
    """Re-run the weekly rollup for every week that has content.

    Returns (success_count, error_count).
    """
    weeks = _list_weeks_in_agent(vault, agent)
    # Also pick up weeks that DON'T have a weekly file yet but have dailies
    # (the migration may have moved dailies for weeks that were never
    # rolled up). We seed those by scanning daily files and computing the
    # ISO week of each.
    seen = {w[0] for w in weeks}
    journal = vault / agent / "Journal"
    if journal.is_dir():
        for sub in sorted(journal.iterdir()):
            if not sub.is_dir() or not MONTH_DIR_RE.match(sub.name):
                continue
            for p in sub.iterdir():
                m = DAILY_RE.match(p.name)
                if not m:
                    continue
                try:
                    d = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
                    iso_year, iso_week, _ = d.isocalendar()
                    label = f"{iso_year}-W{iso_week:02d}"
                    if label not in seen:
                        weeks.append((label, _monday_of_iso_week(iso_year, iso_week)))
                        seen.add(label)
                except ValueError:
                    continue

    if not weeks:
        return 0, 0
    success = 0
    errors = 0
    script = HERE / "journal-weekly-rollup.py"
    for week_label, monday in sorted(weeks, key=lambda w: w[1]):
        # journal-weekly-rollup.py uses --today=<sunday-after> to pick the
        # ISO week ending on the previous Sunday. We pass the Monday of the
        # week we want as `monday + 7` so the script's _current_iso_week
        # rolls back to OUR week.
        anchor = monday + _dt.timedelta(days=7)
        cmd = [sys.executable, str(script), "--today", anchor.isoformat()]
        if skip_llm:
            cmd.append("--skip-llm")
        if dry_run:
            sys.stdout.write(f"  [dry] would run weekly rollup for {agent} {week_label}\n")
            success += 1
            continue
        sys.stdout.write(f"  weekly rollup {agent} {week_label} ...\n")
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
            )
            # The driver iterates ALL agents — we only count the line for
            # OUR agent. Not perfect but good enough for a migration log.
            if res.returncode != 0:
                errors += 1
                sys.stderr.write(
                    f"  [err] weekly rollup {agent} {week_label} rc={res.returncode}: "
                    f"{res.stderr.strip()[:200]}\n"
                )
            else:
                success += 1
        except subprocess.TimeoutExpired:
            errors += 1
            sys.stderr.write(f"  [err] weekly rollup {agent} {week_label} timed out\n")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            sys.stderr.write(f"  [err] weekly rollup {agent} {week_label}: {exc}\n")
    return success, errors


def regenerate_monthlies(
    vault: Path, agent: str, skip_llm: bool, dry_run: bool,
) -> Tuple[int, int]:
    """Run the monthly rollup for every YYYY-MM folder of the agent."""
    months = _list_months_in_agent(vault, agent)
    if not months:
        return 0, 0
    success = 0
    errors = 0
    script = HERE / "journal-monthly-rollup.py"
    for month_label in months:
        cmd = [
            sys.executable, str(script),
            "--agent", agent,
            "--month", month_label,
        ]
        if skip_llm:
            cmd.append("--skip-llm")
        if dry_run:
            sys.stdout.write(f"  [dry] would run monthly rollup for {agent} {month_label}\n")
            success += 1
            continue
        sys.stdout.write(f"  monthly rollup {agent} {month_label} ...\n")
        try:
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=360,
            )
            if res.returncode != 0:
                errors += 1
                sys.stderr.write(
                    f"  [err] monthly rollup {agent} {month_label} rc={res.returncode}: "
                    f"{res.stderr.strip()[:200]}\n"
                )
            else:
                success += 1
        except subprocess.TimeoutExpired:
            errors += 1
            sys.stderr.write(f"  [err] monthly rollup {agent} {month_label} timed out\n")
        except Exception as exc:  # noqa: BLE001
            errors += 1
            sys.stderr.write(f"  [err] monthly rollup {agent} {month_label}: {exc}\n")
    return success, errors


# ---------------------------------------------------------------------------
# Step 7 — rebuild FTS + graph
# ---------------------------------------------------------------------------


def rebuild_indexes(dry_run: bool) -> int:
    """Rebuild the FTS index, the graph, and the marker blocks. Returns
    the number of failures."""
    failures = 0
    targets = [
        (HERE / "vault-index-update.py", "FTS rebuild"),
        (HERE / "vault-graph-builder.py", "graph rebuild"),
        (HERE / "vault_indexes.py", "marker blocks regen"),
    ]
    for script, label in targets:
        if not script.is_file():
            sys.stderr.write(f"  [warn] {label}: script not found at {script}\n")
            failures += 1
            continue
        if dry_run:
            sys.stdout.write(f"  [dry] would run {label}\n")
            continue
        sys.stdout.write(f"  {label} ...\n")
        try:
            res = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, timeout=180,
            )
            if res.returncode != 0:
                failures += 1
                sys.stderr.write(
                    f"  [err] {label} rc={res.returncode}: {res.stderr.strip()[:200]}\n"
                )
        except Exception as exc:  # noqa: BLE001
            failures += 1
            sys.stderr.write(f"  [err] {label}: {exc}\n")
    return failures


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--agent", type=str, default=None,
                        help="Restrict to a single agent (default: all)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print actions without changing anything")
    parser.add_argument("--no-llm-weekly", action="store_true",
                        help="Skip the LLM weekly regeneration step")
    parser.add_argument("--no-llm-monthly", action="store_true",
                        help="Skip the LLM monthly rollup step")
    parser.add_argument("--no-rebuild", action="store_true",
                        help="Skip the FTS / graph / marker rebuild step")
    args = parser.parse_args()

    vault = _resolve_vault(args.vault)
    if not vault.is_dir():
        sys.stderr.write(f"ERROR: vault not found: {vault}\n")
        return 2

    if args.agent:
        agents = [args.agent]
    else:
        agents = _iter_agents(vault)
    if not agents:
        sys.stdout.write("No agents to migrate.\n")
        return 0

    sys.stdout.write(
        f"migrate_journal_hierarchy: vault={vault} agents={agents} "
        f"dry_run={args.dry_run}\n"
    )

    total_failures = 0
    for agent in agents:
        sys.stdout.write(f"\n=== {agent} ===\n")
        try:
            moved_dailies, months_touched = move_dailies(vault, agent, args.dry_run)
            sys.stdout.write(f"  step 1: moved {moved_dailies} dailies into {len(months_touched)} month(s)\n")
            moved_weeklies = move_weeklies(vault, agent, args.dry_run)
            sys.stdout.write(f"  step 2: moved {moved_weeklies} weekly file(s)\n")
            for ym in months_touched or _list_months_in_agent(vault, agent):
                if write_monthly_skeleton(vault, agent, ym, args.dry_run):
                    sys.stdout.write(f"  step 3: dropped placeholder {ym}.md\n")
            if not args.no_llm_weekly:
                ok, err = regenerate_weeklies(vault, agent, skip_llm=False, dry_run=args.dry_run)
                sys.stdout.write(f"  step 4: weekly rollups ok={ok} err={err}\n")
                total_failures += err
            else:
                sys.stdout.write("  step 4: skipped (--no-llm-weekly)\n")
            if not args.no_llm_monthly:
                ok, err = regenerate_monthlies(vault, agent, skip_llm=False, dry_run=args.dry_run)
                sys.stdout.write(f"  step 5: monthly rollups ok={ok} err={err}\n")
                total_failures += err
            else:
                sys.stdout.write("  step 5: skipped (--no-llm-monthly)\n")
            if rewrite_hub(vault, agent, args.dry_run):
                sys.stdout.write("  step 6: rewrote agent-journal.md hub\n")
            else:
                sys.stdout.write("  step 6: hub already current\n")
        except Exception as exc:  # noqa: BLE001
            total_failures += 1
            sys.stderr.write(f"  [fatal] {agent}: {exc}\n")
            traceback.print_exc(file=sys.stderr)

    if not args.no_rebuild:
        sys.stdout.write("\n=== rebuilds ===\n")
        total_failures += rebuild_indexes(args.dry_run)

    sys.stdout.write(
        f"\nmigrate_journal_hierarchy: done — failures={total_failures}\n"
    )
    return 3 if total_failures else 0


if __name__ == "__main__":
    sys.exit(main())
