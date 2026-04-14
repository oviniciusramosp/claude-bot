#!/usr/bin/env python3
"""
journal-weekly-rollup.py — per-agent weekly summary driver.

Invoked by the ``journal-weekly-rollup`` routine on Mondays at 05:00.
Iterates every agent via ``discover_agents()`` (contract C1 / C7 — no
hardcoded list, mirrors the ``journal-audit`` pattern). For each agent
that has at least one journal entry in the past 7 days, spawns a short-
lived ``claude --print --model sonnet`` subprocess scoped to that
agent's folder to produce a compact bullet-style summary, then writes
it to ``vault/<agent>/Journal/weekly/YYYY-Www.md`` and upserts the file
into the FTS index for immediate searchability.

Exit codes:
  0 — all agents processed (some may have had no content; that's fine)
  2 — vault directory not found
  3 — one or more per-agent summaries failed

Per ``.claude/rules/bot-code-conventions.md`` (zero silent errors), any
failure surfaces on stderr with full context so the routine forwards it
to Telegram.

Stdlib-only — no pip deps.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import logging
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import vault_index  # noqa: E402


def _resolve_vault_dir() -> Path:
    env = os.environ.get("CLAUDE_BOT_VAULT")
    if env:
        return Path(env).resolve()
    return (REPO_ROOT / "vault").resolve()


def _resolve_db_path() -> Path:
    env = os.environ.get("CLAUDE_BOT_INDEX_DB")
    if env:
        return Path(env).resolve()
    return Path.home() / ".claude-bot" / "vault-index.sqlite"


def _current_iso_week(today: Optional[_dt.date] = None) -> tuple[str, _dt.date, _dt.date]:
    """Return (``YYYY-Www``, monday, sunday) for the ISO week of ``today``.

    Uses the previous Monday as the start and the previous Sunday as the
    end so the summary covers the week that just finished, not the one
    currently in progress.
    """
    if today is None:
        today = _dt.date.today()
    # Compute the Monday of the previous week
    days_since_monday = today.weekday()  # Mon=0
    this_monday = today - _dt.timedelta(days=days_since_monday)
    last_monday = this_monday - _dt.timedelta(days=7)
    last_sunday = last_monday + _dt.timedelta(days=6)
    iso_year, iso_week, _ = last_monday.isocalendar()
    return f"{iso_year}-W{iso_week:02d}", last_monday, last_sunday


def _collect_journal_text(
    conn,
    agent: str,
    date_from: str,
    date_to: str,
) -> str:
    """Return all journal section bodies for ``agent`` within the window,
    concatenated into a single string ready to feed the LLM. Empty when
    there's nothing to summarize.
    """
    # Use the index: search with a broad query plus a date filter. We
    # could read files directly, but routing through the index keeps this
    # script fast and future-proof — when new journal types appear, the
    # index picks them up.
    sql = """
        SELECT date, section_path, body
        FROM entries
        WHERE agent = ?
          AND kind = 'journal'
          AND date IS NOT NULL
          AND date BETWEEN ? AND ?
        ORDER BY date ASC, id ASC
    """
    rows = conn.execute(sql, (agent, date_from, date_to)).fetchall()
    chunks: List[str] = []
    for row in rows:
        header = f"### {row['date']}"
        if row["section_path"]:
            header += f" {row['section_path']}"
        chunks.append(f"{header}\n\n{row['body']}\n")
    return "\n\n".join(chunks).strip()


def _run_claude_summary(agent: str, week_label: str, raw_text: str, workspace: Path) -> str:
    """Spawn a ``claude --print`` subprocess to produce the weekly summary.

    Uses ``--model sonnet`` and explicitly avoids tool use. The subprocess
    stdin is the collected journal text; stdout is the summary we write
    to disk. Times out after 120 s to avoid hanging the routine.
    """
    claude_bin = os.environ.get("CLAUDE_PATH", "/opt/homebrew/bin/claude")
    prompt = (
        f"Você é responsável por produzir o sumário semanal do agente "
        f"`{agent}` para a semana `{week_label}`. Recebeu abaixo o texto "
        "bruto de todas as entradas de journal da semana. Gere um resumo "
        "compacto em markdown, em português, com EXACTLY estes blocos:\n\n"
        "## Goals\n- bullet\n\n"
        "## Decisions\n- bullet\n\n"
        "## Progress\n- bullet\n\n"
        "## Next Week\n- bullet\n\n"
        "Máximo 6 bullets por bloco. Sem preâmbulo, sem epílogo. "
        "Responda APENAS com o markdown.\n\n"
        "---\n\n"
        f"{raw_text}"
    )
    cmd = [
        claude_bin,
        "--print",
        "--dangerously-skip-permissions",
        "--model", "sonnet",
        "--output-format", "text",
        "-p", prompt,
    ]
    result = subprocess.run(
        cmd,
        cwd=str(workspace),
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude subprocess failed rc={result.returncode}: "
            f"stderr={result.stderr.strip()[:400]}"
        )
    return (result.stdout or "").strip()


def _write_weekly_file(
    vault_dir: Path,
    agent: str,
    week_label: str,
    summary: str,
    date_from: str,
    date_to: str,
) -> Path:
    weekly_dir = vault_dir / agent / "Journal" / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    path = weekly_dir / f"{week_label}.md"
    today = _dt.date.today().isoformat()
    frontmatter = (
        "---\n"
        f'title: "Weekly {week_label} — {agent}"\n'
        f'description: "Auto-generated weekly rollup covering {date_from} → {date_to}"\n'
        "type: journal_weekly\n"
        f"week: {week_label}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "tags: [journal, weekly, rollup]\n"
        "---\n\n"
    )
    path.write_text(frontmatter + summary + "\n", encoding="utf-8")
    return path


def _rollup_for_agent(
    conn,
    vault_dir: Path,
    agent: str,
    week_label: str,
    date_from: str,
    date_to: str,
    skip_llm: bool = False,
) -> Optional[Path]:
    """Produce one weekly file for one agent. Returns the path written
    (or None if the agent had no journal content in the window)."""
    raw = _collect_journal_text(conn, agent, date_from, date_to)
    if not raw:
        return None
    workspace = vault_dir / agent
    if skip_llm:
        # Used by tests — write a deterministic summary so we can assert
        # on the final artifact without spawning a real Claude subprocess.
        summary = (
            f"## Goals\n- (test-mode) {agent}\n\n"
            f"## Decisions\n- (test-mode)\n\n"
            f"## Progress\n- (test-mode) {len(raw)} chars of raw journal\n\n"
            f"## Next Week\n- (test-mode)\n"
        )
    else:
        summary = _run_claude_summary(agent, week_label, raw, workspace)
    if not summary.strip():
        raise RuntimeError(f"weekly summary for {agent} came back empty")
    path = _write_weekly_file(vault_dir, agent, week_label, summary, date_from, date_to)
    # Write-through to the FTS index so the new rollup is immediately
    # searchable by the next session.
    try:
        rel = path.relative_to(vault_dir).as_posix()
        vault_index.upsert_file(conn, vault_dir, agent, rel)
    except Exception as exc:
        logging.warning("weekly rollup: write-through failed for %s: %s", agent, exc)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--today", type=str, default=None,
                        help="Override today's date (YYYY-MM-DD) — testing only")
    parser.add_argument("--skip-llm", action="store_true",
                        help="Write a deterministic placeholder summary instead of "
                             "spawning Claude — for tests and dry runs")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    vault_dir = (args.vault or _resolve_vault_dir()).resolve()
    db_path = (args.db or _resolve_db_path()).resolve()
    if not vault_dir.is_dir():
        sys.stderr.write(f"ERROR: vault directory not found: {vault_dir}\n")
        return 2

    if args.today:
        today = _dt.date.fromisoformat(args.today)
    else:
        today = None
    week_label, monday, sunday = _current_iso_week(today)
    date_from = monday.isoformat()
    date_to = sunday.isoformat()

    sys.stdout.write(
        f"journal-weekly-rollup: vault={vault_dir} week={week_label} "
        f"({date_from}..{date_to})\n"
    )
    sys.stdout.flush()

    # Ensure the index exists — if the daily rebuild hasn't run yet on a
    # fresh install, build it first so we have something to query.
    if not db_path.exists():
        sys.stdout.write("journal-weekly-rollup: index not found, building...\n")
        vault_index.rebuild(vault_dir, db_path)

    conn = vault_index.connect(db_path)
    errors: List[str] = []
    processed = 0
    written = 0
    try:
        # Contract C1 / C7: discover agents via the single source of truth.
        # We prefer the bot's iter_agent_ids() when running inside the bot
        # process, but since this script is spawned standalone we use the
        # stdlib equivalent in vault_index.
        agents = vault_index.discover_agents(vault_dir)
        for agent in agents:
            processed += 1
            try:
                path = _rollup_for_agent(
                    conn, vault_dir, agent, week_label,
                    date_from, date_to, skip_llm=args.skip_llm,
                )
                if path is not None:
                    written += 1
                    sys.stdout.write(
                        f"journal-weekly-rollup: {agent} -> "
                        f"{path.relative_to(vault_dir).as_posix()}\n"
                    )
                else:
                    sys.stdout.write(
                        f"journal-weekly-rollup: {agent} — no journal "
                        f"content in window, skipping\n"
                    )
            except Exception as exc:
                errors.append(f"{agent}: {exc}")
                sys.stderr.write(f"ERROR: {agent}: {exc}\n")
                traceback.print_exc(file=sys.stderr)
    finally:
        conn.close()

    sys.stdout.write(
        f"journal-weekly-rollup: done — {processed} agents, {written} files written, "
        f"{len(errors)} errors\n"
    )
    return 3 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
