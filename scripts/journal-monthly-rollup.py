#!/usr/bin/env python3
"""
journal-monthly-rollup.py — per-agent monthly summary driver (v3.68+).

Invoked by the ``journal-monthly-rollup`` routine on the 1st of each month.
Iterates every agent via ``discover_agents()`` (contracts C1 / C7 — no
hardcoded list, mirrors ``journal-audit`` and ``journal-weekly-rollup``).
For each agent that has at least one journal entry in the prior month,
spawns a short-lived ``claude --print --model sonnet`` subprocess scoped
to that agent's folder to produce a rich monthly summary, then writes it
to ``vault/<agent>/Journal/<YYYY-MM>/<YYYY-MM>.md`` and upserts the file
into the FTS index for immediate searchability.

The monthly file is the **top of the in-month memory hierarchy**:
``agent-journal.md → YYYY-MM.md → YYYY-Www.md → YYYY-MM-DD.md``. Its
frontmatter description is the primary signal an LLM uses when scanning
``agent-journal.md`` to decide which months to open.

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
import calendar as _cal
import datetime as _dt
import logging
import os
import re
import subprocess
import sys
import traceback
from pathlib import Path
from typing import List, Optional, Tuple

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import vault_index  # noqa: E402


_WEEKLY_FNAME_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")
_DAILY_FNAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")


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


def _previous_month(today: Optional[_dt.date] = None) -> Tuple[str, _dt.date, _dt.date]:
    """Return ``(YYYY-MM, first_day, last_day)`` for the month BEFORE ``today``.

    The routine runs on the 1st, so the rollup covers the month that just
    finished (the previous month). When called manually with ``--today``
    inside a month, still rolls up the previous month — never partial.
    """
    if today is None:
        today = _dt.date.today()
    first_of_this = today.replace(day=1)
    last_of_prev = first_of_this - _dt.timedelta(days=1)
    first_of_prev = last_of_prev.replace(day=1)
    label = f"{first_of_prev.year:04d}-{first_of_prev.month:02d}"
    return label, first_of_prev, last_of_prev


def _collect_journal_text(
    conn,
    agent: str,
    date_from: str,
    date_to: str,
) -> str:
    """Concatenate all daily journal sections for ``agent`` within the window.

    Sources rows from the FTS index (``kind='journal'``) — same as the
    weekly rollup. Returns empty string when the agent had no activity.
    """
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


def _list_weeks_in_month(
    vault_dir: Path, agent: str, month_label: str,
) -> List[Tuple[str, Path]]:
    """Return ``(week_label, path)`` for every weekly file inside the month
    folder, sorted ascending. Empty list if the folder doesn't exist yet."""
    month_dir = vault_dir / agent / "Journal" / month_label
    if not month_dir.is_dir():
        return []
    out: List[Tuple[str, Path]] = []
    for p in sorted(month_dir.iterdir()):
        if not p.is_file():
            continue
        m = _WEEKLY_FNAME_RE.match(p.name)
        if m:
            out.append((f"{m.group(1)}-W{m.group(2)}", p))
    return out


def _list_days_in_month(
    vault_dir: Path, agent: str, month_label: str,
) -> List[Tuple[str, Path]]:
    """Return ``(date_str, path)`` for every daily file inside the month
    folder, sorted ascending."""
    month_dir = vault_dir / agent / "Journal" / month_label
    if not month_dir.is_dir():
        return []
    out: List[Tuple[str, Path]] = []
    for p in sorted(month_dir.iterdir()):
        if not p.is_file():
            continue
        m = _DAILY_FNAME_RE.match(p.name)
        if m:
            out.append((m.group(1), p))
    return out


def _read_description(path: Path) -> str:
    """Read the ``description:`` field from a markdown frontmatter, or empty."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not text.startswith("---"):
        return ""
    end = text.find("\n---", 3)
    if end < 0:
        return ""
    fm = text[3:end]
    for line in fm.splitlines():
        line = line.strip()
        if line.startswith("description:"):
            value = line[len("description:"):].strip()
            if value.startswith('"') and value.endswith('"') and len(value) >= 2:
                value = value[1:-1]
            return value
    return ""


def _run_claude_summary(
    agent: str,
    month_label: str,
    raw_text: str,
    workspace: Path,
) -> Tuple[str, str]:
    """Spawn a ``claude --print`` subprocess to produce the monthly summary.

    Returns ``(description, body)``. The description is a single dense
    paragraph (≤400 chars) for the YAML frontmatter; the body is the
    markdown that goes into the file (Themes / Highlights / Decisions /
    Lessons / Carry-forward).
    """
    claude_bin = os.environ.get("CLAUDE_PATH", "/opt/homebrew/bin/claude")
    prompt = (
        f"Você é responsável por produzir o sumário MENSAL do agente "
        f"`{agent}` para o mês `{month_label}`. Recebeu abaixo o texto "
        "bruto de todas as entradas de journal do mês. Gere DUAS saídas "
        "delimitadas pelo separador exato `===DESC===`.\n\n"
        "PARTE 1 — Description (1 parágrafo, máx 400 caracteres, em "
        "português, denso de palavras-chave concretas: temas, projetos, "
        "decisões, agentes/serviços tocados). NÃO comece com 'Auto-generated'. "
        "Esta description vai para o frontmatter YAML e é o principal sinal "
        "que outro LLM (em uma futura sessão) usa para decidir se vale "
        "abrir este mês inteiro. Seja específico e densa em substantivos: "
        "`refactor pipeline crypto-news, criação agente mexc-bot, redesign "
        "vault per-agent v3.1, watchdog notifications` é bom; `Diversas "
        "atividades do mês` é ruim.\n\n"
        "===DESC===\n\n"
        "PARTE 2 — Body (markdown completo, em português) com EXATAMENTE estes "
        "blocos nesta ordem:\n\n"
        "## What you'll find here\n"
        "Um parágrafo (5-8 linhas) descrevendo de forma narrativa o que "
        "aconteceu no mês — projetos centrais, agentes mais ativos, "
        "decisões marcantes, mudanças de rumo.\n\n"
        "## Themes\n- bullet (3-5)\n\n"
        "## Highlights\n- bullet (5-8)\n\n"
        "## Decisions\n- bullet (3-6)\n\n"
        "## Lessons\n- bullet (2-4) — aprendizados que valem revisitar\n\n"
        "## Carry-forward\n- bullet (2-4) — o que ficou pendente para o "
        "próximo mês\n\n"
        "Sem preâmbulo, sem epílogo. Responda APENAS com PARTE 1, o "
        "separador, e PARTE 2.\n\n"
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
        timeout=240,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"claude subprocess failed rc={result.returncode}: "
            f"stderr={result.stderr.strip()[:400]}"
        )
    raw = (result.stdout or "").strip()
    if "===DESC===" in raw:
        desc_part, body_part = raw.split("===DESC===", 1)
        description = desc_part.strip()
        body = body_part.strip()
    else:
        description = f"Monthly rollup for {agent} covering {month_label}."
        body = raw
    description = " ".join(description.split())
    if len(description) > 400:
        description = description[:397] + "…"
    return description, body


def _write_monthly_file(
    vault_dir: Path,
    agent: str,
    month_label: str,
    description: str,
    body: str,
    weeks: List[Tuple[str, Path]],
    days: List[Tuple[str, Path]],
) -> Path:
    """Write ``vault/<agent>/Journal/<YYYY-MM>/<YYYY-MM>.md``.

    Always includes the LLM-generated body PLUS a deterministic ``## Weeks``
    and ``## Days`` block with wikilinks + per-file descriptions, so the
    reader can drill down without re-opening this file.
    """
    month_dir = vault_dir / agent / "Journal" / month_label
    month_dir.mkdir(parents=True, exist_ok=True)
    path = month_dir / f"{month_label}.md"
    today = _dt.date.today().isoformat()
    desc_safe = (description or "").replace('"', '\\"').replace("\n", " ").strip()
    if not desc_safe:
        desc_safe = f"Monthly rollup for {agent} ({month_label})."

    # Pretty month label, e.g. "May 2026"
    try:
        year = int(month_label[:4])
        month = int(month_label[5:7])
        month_name_pretty = f"{_cal.month_name[month]} {year}"
    except (ValueError, IndexError):
        month_name_pretty = month_label

    week_labels = [w[0] for w in weeks]
    day_strs = [d[0] for d in days]
    weeks_yaml = ", ".join(week_labels)
    frontmatter = (
        "---\n"
        f'title: "Journal {month_label} — {agent}"\n'
        f'description: "{desc_safe}"\n'
        "type: journal_monthly\n"
        f"month: {month_label}\n"
        f"agent: {agent}\n"
        f"weeks: [{weeks_yaml}]\n"
        f"days_with_entries: {len(day_strs)}\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        "tags: [journal, monthly, rollup]\n"
        "---\n\n"
        f"# Journal — {month_name_pretty}\n\n"
        "## How to consult this month\n\n"
        "Memory is hierarchical. Read in this order before opening individual days:\n\n"
        "1. The description in this file's frontmatter — themes covered.\n"
        "2. The summary below — narrative of the month.\n"
        "3. Weekly summaries — compact recap per week.\n"
        "4. Individual daily files — only when you need raw detail.\n\n"
    )

    # Weeks section with descriptions pulled from each weekly file's frontmatter
    weeks_lines = ["## Weeks", ""]
    if weeks:
        for week_label, week_path in weeks:
            week_desc = _read_description(week_path)
            link_target = f"{agent}/Journal/{month_label}/{week_label}"
            label = week_label
            if week_desc:
                weeks_lines.append(f"- [[{link_target}|{label}]] — {week_desc}")
            else:
                weeks_lines.append(f"- [[{link_target}|{label}]]")
    else:
        weeks_lines.append("(no weekly summaries available for this month)")
    weeks_block = "\n".join(weeks_lines) + "\n"

    # Days section with descriptions pulled from each daily file's frontmatter
    days_lines = ["", "## Days", ""]
    if days:
        for day_str, day_path in days:
            day_desc = _read_description(day_path)
            link_target = f"{agent}/Journal/{month_label}/{day_str}"
            if day_desc:
                days_lines.append(f"- [[{link_target}|{day_str}]] — {day_desc}")
            else:
                days_lines.append(f"- [[{link_target}|{day_str}]]")
    else:
        days_lines.append("(no daily entries this month)")
    days_block = "\n".join(days_lines) + "\n"

    path.write_text(
        frontmatter + body.strip() + "\n\n" + weeks_block + days_block,
        encoding="utf-8",
    )
    return path


def _rollup_for_agent(
    conn,
    vault_dir: Path,
    agent: str,
    month_label: str,
    date_from: str,
    date_to: str,
    skip_llm: bool = False,
) -> Optional[Path]:
    """Produce one monthly file for one agent.

    Returns the path written, or None if the agent had no journal content
    in the window AND no existing weekly/daily files for the month.
    """
    raw = _collect_journal_text(conn, agent, date_from, date_to)
    weeks = _list_weeks_in_month(vault_dir, agent, month_label)
    days = _list_days_in_month(vault_dir, agent, month_label)
    if not raw and not weeks and not days:
        return None
    workspace = vault_dir / agent
    if skip_llm or not raw.strip():
        # No raw text to summarize OR explicit test mode → write a
        # deterministic placeholder. Mirrors the weekly rollup behavior.
        description = (
            f"Monthly index for {agent} ({month_label}). "
            f"{len(weeks)} weeks, {len(days)} days with entries. "
            f"Pending LLM rollup."
        )
        body = (
            "## What you'll find here\n"
            f"Monthly index for {agent} during {month_label}. "
            "The weekly summaries linked below are the canonical recap; "
            "this file is a deterministic placeholder until the next "
            "monthly rollup runs.\n\n"
            "## Themes\n- (placeholder)\n\n"
            "## Highlights\n- (placeholder)\n\n"
            "## Decisions\n- (placeholder)\n\n"
            "## Lessons\n- (placeholder)\n\n"
            "## Carry-forward\n- (placeholder)\n"
        )
    else:
        description, body = _run_claude_summary(agent, month_label, raw, workspace)
    if not body.strip():
        raise RuntimeError(f"monthly summary for {agent} came back empty")
    path = _write_monthly_file(
        vault_dir, agent, month_label, description, body, weeks, days,
    )
    # Write-through to the FTS index so the new monthly is immediately
    # searchable by the next session.
    try:
        rel = path.relative_to(vault_dir).as_posix()
        vault_index.upsert_file(conn, vault_dir, agent, rel)
    except Exception as exc:
        logging.warning("monthly rollup: write-through failed for %s: %s", agent, exc)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, default=None)
    parser.add_argument("--db", type=Path, default=None)
    parser.add_argument("--today", type=str, default=None,
                        help="Override today's date (YYYY-MM-DD) — testing only")
    parser.add_argument("--month", type=str, default=None,
                        help="Override target month (YYYY-MM). Skips the "
                             "previous-month auto-derivation.")
    parser.add_argument("--agent", type=str, default=None,
                        help="Restrict rollup to one agent (default: all).")
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

    if args.month:
        m = re.match(r"^(\d{4})-(\d{2})$", args.month)
        if not m:
            sys.stderr.write(f"ERROR: --month must be YYYY-MM, got {args.month!r}\n")
            return 2
        year = int(m.group(1))
        month = int(m.group(2))
        first_day = _dt.date(year, month, 1)
        last_day = _dt.date(year, month, _cal.monthrange(year, month)[1])
        month_label = args.month
    else:
        if args.today:
            today = _dt.date.fromisoformat(args.today)
        else:
            today = None
        month_label, first_day, last_day = _previous_month(today)
    date_from = first_day.isoformat()
    date_to = last_day.isoformat()

    sys.stdout.write(
        f"journal-monthly-rollup: vault={vault_dir} month={month_label} "
        f"({date_from}..{date_to})\n"
    )
    sys.stdout.flush()

    if not db_path.exists():
        sys.stdout.write("journal-monthly-rollup: index not found, building...\n")
        vault_index.rebuild(vault_dir, db_path)

    conn = vault_index.connect(db_path)
    errors: List[str] = []
    processed = 0
    written = 0
    try:
        if args.agent:
            agents = [args.agent]
        else:
            agents = vault_index.discover_agents(vault_dir)
        for agent in agents:
            processed += 1
            try:
                path = _rollup_for_agent(
                    conn, vault_dir, agent, month_label,
                    date_from, date_to, skip_llm=args.skip_llm,
                )
                if path is not None:
                    written += 1
                    sys.stdout.write(
                        f"journal-monthly-rollup: {agent} -> "
                        f"{path.relative_to(vault_dir).as_posix()}\n"
                    )
                else:
                    sys.stdout.write(
                        f"journal-monthly-rollup: {agent} — no journal "
                        f"content for {month_label}, skipping\n"
                    )
            except Exception as exc:
                errors.append(f"{agent}: {exc}")
                sys.stderr.write(f"ERROR: {agent}: {exc}\n")
                traceback.print_exc(file=sys.stderr)
    finally:
        conn.close()

    sys.stdout.write(
        f"journal-monthly-rollup: done — {processed} agents, {written} files written, "
        f"{len(errors)} errors\n"
    )
    return 3 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
