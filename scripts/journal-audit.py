#!/usr/bin/env python3
"""Journal audit — compares vault activity log with journal entries to find gaps.

Reads each agent's ``Agents/<id>/Journal/.activity/YYYY-MM-DD.jsonl`` (written
by the bot) and compares with journal files to identify uncovered sessions
and frontmatter issues.

Usage:
    python3 scripts/journal-audit.py [--date YYYY-MM-DD] [--fix]

Modes:
    (default)  Report gaps and issues to stdout (for Claude to act on)
    --fix      Deterministic fixes: create missing journal files, repair broken
               frontmatter. Does NOT write content — that's Claude's job.

Output: Markdown report to stdout, suitable for Claude to act on.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

# ---------------------------------------------------------------------------
# Vault discovery
# ---------------------------------------------------------------------------


def get_vault_dir() -> Path:
    """Derive vault path from script location: scripts/ -> parent -> vault/."""
    return Path(__file__).resolve().parent.parent / "vault"


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------


def _iter_agent_dirs(vault: Path) -> list[Path]:
    """Yield every direct-child agent directory under the vault.

    In the v3.4 layout agents live directly under the vault root — an agent
    is any subdirectory containing an ``agent-<dirname>.md`` hub file.
    """
    if not vault.is_dir():
        return []
    out: list[Path] = []
    for entry in sorted(vault.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if (entry / f"agent-{entry.name}.md").is_file():
            out.append(entry)
    return out


def load_activity_log(vault: Path, target_date: str) -> list[dict]:
    """Read activity JSONL for the given date from every agent's journal.

    v3.1: the activity log is per-agent under
    ``<agent>/Journal/.activity/YYYY-MM-DD.jsonl``. Walks every agent directly
    under the vault root and concatenates — entries already carry their
    ``agent`` field so we don't lose attribution when merging.

    Falls back to the v3.0 ``Agents/<id>/Journal/.activity/`` path and the
    pre-v3 top-level ``Journal/.activity/`` path so an in-progress migration
    still surfaces data.
    """
    entries: list[dict] = []
    paths: list[Path] = []
    # v3.1: agents directly under the vault root.
    for agent_dir in _iter_agent_dirs(vault):
        candidate = agent_dir / "Journal" / ".activity" / f"{target_date}.jsonl"
        if candidate.exists():
            paths.append(candidate)
    # v3.0 fallback: Agents/<id>/.
    agents_root = vault / "Agents"
    if agents_root.is_dir():
        for agent_dir in sorted(agents_root.iterdir()):
            if not agent_dir.is_dir():
                continue
            candidate = agent_dir / "Journal" / ".activity" / f"{target_date}.jsonl"
            if candidate.exists():
                paths.append(candidate)
    # Pre-v3 fallback.
    legacy = vault / "Journal" / ".activity" / f"{target_date}.jsonl"
    if legacy.exists():
        paths.append(legacy)

    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return entries


def discover_agents(entries: list[dict]) -> set[str]:
    """Extract unique agent IDs from activity entries."""
    return {e.get("agent", "main") for e in entries}


# ---------------------------------------------------------------------------
# Journal file operations
# ---------------------------------------------------------------------------


def get_journal_path(vault: Path, agent: str, target_date: str) -> Path:
    """Return journal file path for an agent under the v3.1 flat layout."""
    return vault / (agent or "main") / "Journal" / f"{target_date}.md"


JOURNAL_TEMPLATE = """\
---
title: "Journal {date}"
description: "pending: no entries yet"
type: journal
created: {date}
updated: {date}
tags: [{tags}]
---
"""


def create_journal_file(path: Path, agent: str, target_date: str) -> None:
    """Create a journal file with valid frontmatter. Deterministic — no Claude needed.
    Daily journal entries do NOT carry a parent wikilink; they live in the Journal
    folder which is sufficient context, and they are excluded from the knowledge
    graph (see scripts/vault-graph-builder.py::is_ephemeral)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tags = "journal" if agent == "main" else f"journal, {agent}"
    content = JOURNAL_TEMPLATE.format(date=target_date, tags=tags)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Frontmatter validation and repair
# ---------------------------------------------------------------------------


def validate_frontmatter(content: str) -> tuple[bool, list[str]]:
    """Validate YAML frontmatter. Returns (is_valid, list of issues)."""
    issues = []
    lines = content.split("\n")

    if not lines or lines[0].strip() != "---":
        issues.append("missing opening `---` delimiter")
        return False, issues

    # Find closing delimiter — must appear before any markdown content
    closing_idx = None
    for i in range(1, min(len(lines), 30)):
        stripped = lines[i].strip()
        if stripped == "---":
            closing_idx = i
            break
        if stripped.startswith("#") or (stripped.startswith("- ") and ":" not in stripped):
            issues.append("missing closing `---` delimiter (markdown content found before closing)")
            return False, issues

    if closing_idx is None:
        issues.append("missing closing `---` delimiter")
        return False, issues

    fm_block = "\n".join(lines[1:closing_idx])
    required = ["title", "type"]
    for field in required:
        if not re.search(rf"^{field}\s*:", fm_block, re.MULTILINE):
            issues.append(f"missing required field `{field}`")

    return len(issues) == 0, issues


def fix_frontmatter(path: Path, agent: str, target_date: str) -> str:
    """Fix broken frontmatter in a journal file. Returns description of what was fixed."""
    content = path.read_text(encoding="utf-8")
    lines = content.split("\n")

    # Find where frontmatter ends (or where it should end)
    body_start = 0
    has_opening = lines[0].strip() == "---" if lines else False

    if has_opening:
        # Look for closing ---
        for i in range(1, min(len(lines), 30)):
            stripped = lines[i].strip()
            if stripped == "---":
                body_start = i + 1
                return "frontmatter already valid"  # shouldn't be called
            if stripped.startswith("#") or (stripped.startswith("- ") and ":" not in stripped):
                # Markdown content before closing --- → insert closing before this line
                # Extract existing frontmatter fields
                fm_lines = lines[1:i]
                body_lines = lines[i:]
                break
        else:
            # No closing found within 30 lines
            fm_lines = lines[1:min(len(lines), 10)]
            body_lines = lines[min(len(lines), 10):]
    else:
        # No opening --- at all
        fm_lines = []
        body_lines = lines

    # Build valid frontmatter from existing fields + defaults
    fm_dict: dict[str, str] = {}
    for fl in fm_lines:
        m = re.match(r"^(\w[\w-]*)\s*:\s*(.+)", fl)
        if m:
            fm_dict[m.group(1)] = m.group(2).strip()

    tags = "journal" if agent == "main" else f"journal, {agent}"
    fm_dict.setdefault("title", f'"Journal {target_date}"')
    current_desc = fm_dict.get("description", "")
    if not current_desc or is_generic_description(current_desc):
        summaries = extract_heading_summaries("\n".join(body_lines))
        auto_desc = build_description_from_headings(summaries)
        if auto_desc:
            fm_dict["description"] = auto_desc
        elif not current_desc:
            fm_dict["description"] = '"pending: no entries yet"'
    fm_dict.setdefault("type", "journal")
    fm_dict.setdefault("created", target_date)
    fm_dict.setdefault("updated", target_date)
    fm_dict.setdefault("tags", f"[{tags}]")

    # Rebuild the file
    new_fm = "---\n"
    for k, v in fm_dict.items():
        new_fm += f"{k}: {v}\n"
    new_fm += "---\n"

    # Strip any leading parent-index wikilink line — daily journals are
    # ephemeral logs and don't belong in the knowledge graph (see
    # scripts/vault-graph-builder.py::is_ephemeral). The line is harmless
    # but pollutes Obsidian's graph view.
    body_lines = list(body_lines)
    while body_lines and not body_lines[0].strip():
        body_lines.pop(0)
    if body_lines and re.match(
        r"^\[\[(?:[\w/-]+\|)?[\w/ -]+\]\]\s*$", body_lines[0].strip()
    ):
        body_lines.pop(0)

    body_text = "\n".join(body_lines).strip()
    body_text = f"\n{body_text}" if body_text else ""

    path.write_text(new_fm + body_text + "\n", encoding="utf-8")
    return "frontmatter repaired"


# ---------------------------------------------------------------------------
# Session grouping
# ---------------------------------------------------------------------------


def extract_entry_times(content: str) -> list[str]:
    """Extract HH:MM timestamps from journal entry headers (## HH:MM — ...)."""
    return re.findall(r"^##\s+(\d{2}:\d{2})\s+—", content, re.MULTILINE)


GENERIC_DESC_PATTERNS = [
    re.compile(r"^Daily (log|journal)\b", re.IGNORECASE),
    re.compile(r"^Registro d[eo]\b", re.IGNORECASE),
    re.compile(r"^Activities for\b", re.IGNORECASE),
    re.compile(r"^Journal (belonging to|entries for)\b", re.IGNORECASE),
    re.compile(r"^pending:", re.IGNORECASE),
    re.compile(r"^\d{4}-\d{2}-\d{2}"),
]


def is_generic_description(desc: str) -> bool:
    """Return True if the description is a known generic placeholder."""
    if not desc:
        return True
    desc = desc.strip().strip('"').strip("'")
    if not desc:
        return True
    return any(p.search(desc) for p in GENERIC_DESC_PATTERNS)


def extract_heading_summaries(content: str) -> list[str]:
    """Extract summary text from journal entry headers (## HH:MM — Summary)."""
    return re.findall(r"^##\s+\d{2}:\d{2}\s+—\s+(.+)", content, re.MULTILINE)


def build_description_from_headings(summaries: list[str]) -> str:
    """Build a description string from extracted heading summaries."""
    if not summaries:
        return ""
    seen: set[str] = set()
    unique: list[str] = []
    for s in summaries:
        key = s.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(s.strip())
    desc = ", ".join(unique)
    if len(desc) > 200:
        desc = desc[:200].rsplit(",", 1)[0]
    return desc


def time_close(t1: str, t2: str, tolerance_min: int = 30) -> bool:
    """Check if two HH:MM times are within tolerance_min of each other."""
    try:
        h1, m1 = map(int, t1.split(":"))
        h2, m2 = map(int, t2.split(":"))
        diff = abs((h1 * 60 + m1) - (h2 * 60 + m2))
        return diff <= tolerance_min
    except (ValueError, AttributeError):
        return False


def is_covered(activity_time: str, journal_times: list[str]) -> bool:
    """Check if an activity entry's time is covered by any journal entry."""
    return any(time_close(activity_time, jt) for jt in journal_times)


def group_interactive_sessions(entries: list[dict]) -> list[dict]:
    """Group interactive entries by session name into summaries.

    Each response logs an entry, so a session with 9 messages produces 9 entries.
    We collapse these into one summary per session with message count, time range,
    full user messages, and Claude response summaries.
    """
    sessions: dict[str, dict] = {}
    for e in entries:
        name = e.get("session", "unknown")
        if name not in sessions:
            sessions[name] = {
                "session": name,
                "first_time": e.get("time", "?"),
                "last_time": e.get("time", "?"),
                "messages": 0,
                "turns": [],  # list of {"user": ..., "response": ...}
            }
        s = sessions[name]
        s["messages"] += 1
        s["last_time"] = e.get("time", "?")

        # Collect full conversation turns
        user_msg = e.get("user", e.get("preview", "")).strip()
        response = e.get("response", "").strip()
        if user_msg:
            s["turns"].append({
                "time": e.get("time", "?"),
                "user": user_msg,
                "response": response,
            })

    return list(sessions.values())


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def format_session_block(sg: dict) -> list[str]:
    """Format a single session group for the report."""
    lines = []
    ft, lt = sg["first_time"], sg["last_time"]
    time_range = f"{ft}–{lt}" if ft != lt else ft
    lines.append(
        f"### Session {sg['session']} (~{time_range}, {sg['messages']} msgs)"
    )
    lines.append("")
    for turn in sg["turns"]:
        # Show user message (full, not truncated)
        user = turn["user"]
        lines.append(f"**[{turn['time']}] User:** {user}")
        # Show response summary
        resp = turn["response"]
        if resp:
            lines.append(f"**Claude:** {resp}")
        lines.append("")
    return lines


def format_report(vault: Path, target_date: str, entries: list[dict]) -> str:
    """Generate the full audit report."""
    agents = set(discover_agents(entries))

    # Also check for agent journal directories that might exist even without activity
    agents_dir = vault / "Agents"
    if agents_dir.is_dir():
        for agent_dir in agents_dir.iterdir():
            if agent_dir.is_dir():
                journal_path = get_journal_path(vault, agent_dir.name, target_date)
                if journal_path.exists() and agent_dir.name not in agents:
                    agents.add(agent_dir.name)
    agents = sorted(agents)

    lines = [f"# Journal Audit {target_date}", ""]

    for agent in agents:
        agent_entries = [e for e in entries if e.get("agent", "main") == agent]
        interactive = [e for e in agent_entries if e.get("type") == "interactive"]
        routines = [e for e in agent_entries if e.get("type") == "routine"]
        pipelines = [e for e in agent_entries if e.get("type") == "pipeline"]

        session_groups = group_interactive_sessions(interactive)

        journal_path = get_journal_path(vault, agent, target_date)
        rel_path = journal_path.relative_to(vault)

        lines.append(f"## {agent}")
        lines.append(f"Journal: {rel_path}")

        if journal_path.exists():
            content = journal_path.read_text(encoding="utf-8")
            fm_ok, fm_issues = validate_frontmatter(content)
            journal_times = extract_entry_times(content)

            if fm_ok:
                lines.append("Frontmatter: OK")
            else:
                lines.append(f"Frontmatter: BROKEN — {'; '.join(fm_issues)}")

            lines.append(
                f"Entries: {len(journal_times)} | "
                f"Activity: {len(session_groups)} sessions ({len(interactive)} msgs), "
                f"{len(routines)} routines, {len(pipelines)} pipelines"
            )
            lines.append("")

            # Find uncovered sessions
            uncovered = []
            for sg in session_groups:
                ft = sg["first_time"]
                lt = sg["last_time"]
                if not is_covered(ft, journal_times) and not is_covered(lt, journal_times):
                    uncovered.append(sg)

            if uncovered:
                lines.append("## Uncovered sessions — WRITE THESE TO THE JOURNAL")
                lines.append("")
                for sg in uncovered:
                    lines.extend(format_session_block(sg))
            else:
                if session_groups:
                    lines.append("All sessions covered ✓")
                    lines.append("")

            # Pipeline events
            if pipelines:
                lines.append("### Pipeline activity")
                for e in pipelines:
                    name = e.get("pipeline", "?")
                    status = e.get("status", "?")
                    t = e.get("time", "?")
                    elapsed = e.get("elapsed")
                    elapsed_str = f" ({elapsed}s)" if elapsed else ""
                    lines.append(f"- {t} {name} — {status}{elapsed_str}")
                lines.append("")

            # Routine summary
            if routines:
                lines.append("### Routine activity")
                for e in routines:
                    name = e.get("routine", e.get("session", "?"))
                    t = e.get("time", "?")
                    lines.append(f"- {t} {name}")
                lines.append("")
        else:
            lines.append("Journal: MISSING (will be created with --fix)")
            lines.append(
                f"Activity: {len(session_groups)} sessions ({len(interactive)} msgs), "
                f"{len(routines)} routines, {len(pipelines)} pipelines"
            )
            lines.append("")

            if session_groups:
                lines.append("## All sessions need journal entries — WRITE THESE")
                lines.append("")
                for sg in session_groups:
                    lines.extend(format_session_block(sg))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# --fix: deterministic repairs
# ---------------------------------------------------------------------------


def fix_all(vault: Path, target_date: str, entries: list[dict]) -> list[str]:
    """Create missing journal files and fix broken frontmatter. Returns log of actions."""
    actions = []
    agents = sorted(discover_agents(entries))

    for agent in agents:
        journal_path = get_journal_path(vault, agent, target_date)

        if not journal_path.exists():
            create_journal_file(journal_path, agent, target_date)
            actions.append(f"CREATED {journal_path.relative_to(vault)}")
        else:
            content = journal_path.read_text(encoding="utf-8")
            fm_ok, fm_issues = validate_frontmatter(content)
            if not fm_ok:
                result = fix_frontmatter(journal_path, agent, target_date)
                actions.append(
                    f"FIXED {journal_path.relative_to(vault)}: {result} "
                    f"(was: {'; '.join(fm_issues)})"
                )
            else:
                # Fix generic descriptions on otherwise-valid files
                desc_match = re.search(r"^description:\s*(.+)$", content, re.MULTILINE)
                if desc_match and is_generic_description(desc_match.group(1)):
                    summaries = extract_heading_summaries(content)
                    auto_desc = build_description_from_headings(summaries)
                    if auto_desc:
                        new_content = re.sub(
                            r"^description:\s*.+$",
                            f"description: {auto_desc}",
                            content,
                            count=1,
                            flags=re.MULTILINE,
                        )
                        journal_path.write_text(new_content, encoding="utf-8")
                        actions.append(
                            f"UPDATED description {journal_path.relative_to(vault)}"
                        )

    return actions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description="Journal audit — find gaps in daily journals")
    parser.add_argument("--date", default=date.today().isoformat(),
                        help="Date to audit (YYYY-MM-DD, default: today)")
    parser.add_argument("--fix", action="store_true",
                        help="Create missing journal files and fix broken frontmatter")
    args = parser.parse_args()

    vault = get_vault_dir()
    if not vault.is_dir():
        print(f"Error: vault directory not found at {vault}", file=sys.stderr)
        sys.exit(1)

    entries = load_activity_log(vault, args.date)
    if not entries:
        print(f"# Journal Audit {args.date}")
        print()
        print(f"No activity log found for {args.date}.")
        print(f"Expected: {vault / 'Journal' / '.activity' / (args.date + '.jsonl')}")
        print()
        print("The activity log is written by the bot during the day.")
        print("If the bot was running, check that it has been updated to v2.14.0+.")
        return

    if args.fix:
        actions = fix_all(vault, args.date, entries)
        if actions:
            print("## Deterministic fixes applied:")
            for a in actions:
                print(f"- {a}")
            print()
        else:
            print("## No structural fixes needed.")
            print()

    report = format_report(vault, args.date, entries)
    print(report)


if __name__ == "__main__":
    main()
