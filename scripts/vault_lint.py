#!/usr/bin/env python3
"""
vault_lint.py — vault hygiene linter.

Pure stdlib. Built on vault_query. Detects:

  1. Missing required frontmatter fields (title, description, type, created,
     updated, tags) — except on files that are explicitly exempt (step files,
     agent CLAUDE.md, agent.md hub).
  2. Broken wikilinks — `[[target]]` that doesn't resolve to any vault file.
  3. Orphan files — knowledge nodes unreachable from any index/hub via
     wikilinks. Excludes ephemeral files (daily journals, history rollups,
     reactions, workspace).
  4. Broken pipeline `prompt_file` references — pipeline steps pointing at
     files that don't exist.
  5. Stale routines — `enabled: true` routines that haven't fired in N days
     (requires Phase 5 history rollup; degrades gracefully if absent).
  6. Step-file leakage — pipeline step files containing frontmatter or
     `[[wikilinks]]` (against vault/CLAUDE.md rules).
  7. Index drift — index files claiming children that no longer exist.
     (We do not flag missing children — that's Phase 3's auto-regen job.)
  8. Schedule sanity — routines with both `times` and `interval`, or
     `until` in the past, or empty `days`.

CLI:
    python3 scripts/vault_lint.py                # text report
    python3 scripts/vault_lint.py --json         # JSON report
    python3 scripts/vault_lint.py --category 2 4 # only specific categories
    python3 scripts/vault_lint.py --stale-days 14
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vault_frontmatter import (  # noqa: E402
    extract_wikilinks,
    parse_pipeline_body,
)
from vault_query import VaultFile, VaultIndex, load_vault  # noqa: E402

REQUIRED_FRONTMATTER_KEYS = ("title", "description", "type", "created", "updated", "tags")

# Files that legitimately have no frontmatter. CLAUDE.md (both the vault-wide
# rules file and each agent's personality file) is consumed directly by the
# Claude CLI and is not a graph node. agent-info.md in v3.1 DOES have a full
# frontmatter (it holds the agent metadata), so it is NOT exempt — it will be
# validated like any other knowledge node.
FRONTMATTER_EXEMPT_NAMES = {"CLAUDE.md"}

# Folders whose contents we don't lint (purely runtime data, not knowledge).
# Mirrors vault-graph-builder.is_ephemeral so the linter and the graph stay
# consistent on what counts as a knowledge node.
EXCLUDED_LINT_DIRS = {
    ".graphs",
    ".obsidian",
    ".claude",
    "__pycache__",
    ".workspace",  # v3.5: pipeline runtime data (dot-prefixed so Obsidian hides it)
    "workspace",   # pre-v3.5 fallback — still ignored by the linter
    "Reactions",   # webhook config, see vault/CLAUDE.md "Files that are NOT graph nodes"
}


@dataclass
class LintIssue:
    category: int
    severity: str  # "error" or "warning"
    file: str
    message: str
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "severity": self.severity,
            "file": self.file,
            "message": self.message,
            "detail": self.detail,
        }


@dataclass
class LintReport:
    issues: List[LintIssue] = field(default_factory=list)
    files_scanned: int = 0

    def add(self, issue: LintIssue) -> None:
        self.issues.append(issue)

    @property
    def is_clean(self) -> bool:
        return not self.issues

    def filtered(self, categories: Optional[List[int]] = None) -> "LintReport":
        if not categories:
            return self
        return LintReport(
            issues=[i for i in self.issues if i.category in categories],
            files_scanned=self.files_scanned,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "files_scanned": self.files_scanned,
            "issues_count": len(self.issues),
            "by_category": {
                str(c): sum(1 for i in self.issues if i.category == c)
                for c in sorted({i.category for i in self.issues})
            },
            "issues": [i.to_dict() for i in self.issues],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_lintable(f: VaultFile) -> bool:
    return not any(part in EXCLUDED_LINT_DIRS for part in Path(f.rel_path).parts)


def _is_step_file(f: VaultFile) -> bool:
    """Pipeline step files live under ``<agent>/Routines/{pipeline}/steps/*.md``.

    Accepts two layouts as a safety net during migrations:
    - v3.1 flat layout:    <agent>/Routines/<pipeline>/steps/<step>.md
    - v3.0 wrapped layout: Agents/<agent>/Routines/<pipeline>/steps/<step>.md
    - Legacy (pre-v3):     Routines/<pipeline>/steps/<step>.md
    """
    parts = Path(f.rel_path).parts
    if not parts or not parts[-1].endswith(".md"):
        return False
    # v3.1 flat: <agent>/Routines/<pipeline>/steps/<step>.md
    if (
        len(parts) >= 5
        and parts[1] == "Routines"
        and parts[3] == "steps"
    ):
        return True
    # v3.0 wrapped: Agents/<agent>/Routines/<pipeline>/steps/<step>.md
    if (
        len(parts) >= 6
        and parts[0] == "Agents"
        and parts[2] == "Routines"
        and parts[4] == "steps"
    ):
        return True
    # Pre-v3 legacy: Routines/<pipeline>/steps/<step>.md
    if (
        len(parts) >= 4
        and parts[0] == "Routines"
        and parts[2] == "steps"
    ):
        return True
    return False


def _is_daily_journal(f: VaultFile) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}\.md$", Path(f.rel_path).name))


def _is_history_rollup(f: VaultFile) -> bool:
    return ".history" in Path(f.rel_path).parts


def _is_index_file(f: VaultFile) -> bool:
    """Index files have type=index OR are the README/Tooling root files."""
    if f.type == "index":
        return True
    name = Path(f.rel_path).name
    return name in ("README.md", "Tooling.md")


def _resolve_wikilink_target(link: str, source_dir: Path, vault_dir: Path) -> Optional[Path]:
    """Resolve a wikilink, mirroring vault-graph-builder.resolve_wikilink."""
    link = link.split("#")[0].strip()
    if not link:
        return None
    candidates = [
        source_dir / f"{link}.md",
        source_dir / link / f"{link}.md",
        vault_dir / f"{link}.md",
    ]
    # v3.4: prefer same-agent sibling subfolders first (isolamento total).
    try:
        rel_parts = source_dir.relative_to(vault_dir).parts
        agent_root: Optional[Path] = None
        if rel_parts:
            first_candidate = vault_dir / rel_parts[0]
            if (first_candidate / f"agent-{rel_parts[0]}.md").is_file():
                agent_root = first_candidate
        if agent_root is not None:
            for subdir in ("Skills", "Routines", "Journal", "Notes",
                           "Reactions", "Lessons", ".workspace"):
                candidates.append(agent_root / subdir / f"{link}.md")
            candidates.append(agent_root / f"{link}.md")
    except ValueError:
        pass
    # Path-qualified wikilinks resolve against the vault root.
    if "/" in link:
        candidates.append(vault_dir / f"{link}.md")
    for c in candidates:
        if c.exists():
            return c
    for match in vault_dir.rglob(f"{link}.md"):
        if not any(p in EXCLUDED_LINT_DIRS for p in match.relative_to(vault_dir).parts):
            return match
    return None


# ---------------------------------------------------------------------------
# Lint passes
# ---------------------------------------------------------------------------


def lint_missing_frontmatter(vi: VaultIndex, report: LintReport) -> None:
    for f in vi:
        if not _is_lintable(f):
            continue
        if Path(f.rel_path).name in FRONTMATTER_EXEMPT_NAMES:
            continue
        if _is_step_file(f):
            continue  # Step files have no frontmatter by design
        if _is_history_rollup(f):
            continue  # Optional / written by bot
        if _is_daily_journal(f):
            continue  # Variable shape, audited separately
        missing = [k for k in REQUIRED_FRONTMATTER_KEYS if k not in f.frontmatter]
        if missing:
            report.add(
                LintIssue(
                    category=1,
                    severity="error",
                    file=f.rel_path,
                    message=f"Missing required frontmatter: {', '.join(missing)}",
                )
            )


def lint_broken_wikilinks(vi: VaultIndex, report: LintReport) -> None:
    for f in vi:
        if not _is_lintable(f):
            continue
        if not f.wikilinks:
            continue
        for link in f.wikilinks:
            target = _resolve_wikilink_target(link, f.path.parent, vi.vault_dir)
            if target is None:
                report.add(
                    LintIssue(
                        category=2,
                        severity="warning",
                        file=f.rel_path,
                        message=f"Broken wikilink: [[{link}]]",
                    )
                )


def lint_orphans(vi: VaultIndex, report: LintReport) -> None:
    """A file is an orphan if it is a knowledge node and no other file links
    to it via wikilink. Indexes, step files, daily journals, history rollups,
    and ephemeral files are exempt."""
    inbound: Dict[str, int] = {}
    for f in vi:
        if not _is_lintable(f):
            continue
        for link in f.wikilinks:
            target = _resolve_wikilink_target(link, f.path.parent, vi.vault_dir)
            if target is not None:
                rel = target.relative_to(vi.vault_dir).as_posix()
                inbound[rel] = inbound.get(rel, 0) + 1

    for f in vi:
        if not _is_lintable(f):
            continue
        if _is_index_file(f):
            continue
        if _is_step_file(f):
            continue
        if _is_daily_journal(f):
            continue
        if _is_history_rollup(f):
            continue
        if Path(f.rel_path).name in FRONTMATTER_EXEMPT_NAMES:
            continue
        if f.type in ("agent", "context", "history"):
            continue  # Reachable through their parent agent dir
        if inbound.get(f.rel_path, 0) == 0:
            report.add(
                LintIssue(
                    category=3,
                    severity="warning",
                    file=f.rel_path,
                    message="Orphan file (no inbound wikilinks)",
                )
            )


def lint_broken_prompt_files(vi: VaultIndex, report: LintReport) -> None:
    for f in vi.find(type="pipeline"):
        steps = parse_pipeline_body(f.body)
        # Bot resolves prompt_file as `(pipeline_md.parent / pipeline_md.stem / pf)`
        # — the per-pipeline subfolder is named after the pipeline file's stem.
        pipeline_dir = f.path.parent / f.path.stem
        for step in steps:
            pf = step.get("prompt_file")
            if not pf:
                continue
            target = (pipeline_dir / str(pf)).resolve()
            if not target.exists():
                report.add(
                    LintIssue(
                        category=4,
                        severity="error",
                        file=f.rel_path,
                        message=f"Pipeline step '{step.get('id', '?')}' references missing prompt_file: {pf}",
                    )
                )


def lint_stale_routines(
    vi: VaultIndex, report: LintReport, stale_days: int
) -> None:
    """A routine with `enabled: true` that has not fired in `stale_days` days,
    based on history rollups (Phase 5). If no history exists yet, this pass
    is a no-op."""
    history_files = vi.find(type="history")
    if not history_files:
        return
    last_run: Dict[str, date] = {}
    for h in history_files:
        for ln in h.body.split("\n"):
            m = re.match(
                r"^##\s+(\d{4}-\d{2}-\d{2})(?:\s+\d{2}:\d{2})?\s+—\s+(.+?)\s*$",
                ln.strip(),
            )
            if not m:
                continue
            try:
                d = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            name = m.group(2).strip()
            if name not in last_run or d > last_run[name]:
                last_run[name] = d

    threshold = date.today() - timedelta(days=stale_days)
    for r in vi.find(type__in=["routine", "pipeline"]):
        if r.frontmatter.get("enabled") is False:
            continue
        name = Path(r.rel_path).stem
        if name not in last_run:
            continue  # Never run — first-run grace
        if last_run[name] < threshold:
            report.add(
                LintIssue(
                    category=5,
                    severity="warning",
                    file=r.rel_path,
                    message=f"Routine has not fired since {last_run[name]} ({(date.today() - last_run[name]).days} days)",
                )
            )


def lint_step_file_leakage(vi: VaultIndex, report: LintReport) -> None:
    for f in vi:
        if not _is_step_file(f):
            continue
        if f.frontmatter:
            report.add(
                LintIssue(
                    category=6,
                    severity="error",
                    file=f.rel_path,
                    message="Step file has frontmatter (against vault/CLAUDE.md rules — risk of LLM leakage)",
                )
            )
        if f.wikilinks:
            report.add(
                LintIssue(
                    category=6,
                    severity="error",
                    file=f.rel_path,
                    message=f"Step file contains wikilinks: {', '.join('[[' + w + ']]' for w in f.wikilinks)}",
                )
            )


def lint_index_drift(vi: VaultIndex, report: LintReport) -> None:
    """Index files that link to a child that no longer exists."""
    for f in vi:
        if not _is_index_file(f):
            continue
        for link in f.wikilinks:
            target = _resolve_wikilink_target(link, f.path.parent, vi.vault_dir)
            if target is None:
                report.add(
                    LintIssue(
                        category=7,
                        severity="warning",
                        file=f.rel_path,
                        message=f"Index points to missing child: [[{link}]]",
                    )
                )


def lint_schedule_sanity(vi: VaultIndex, report: LintReport) -> None:
    today = date.today()
    for r in vi.find(type__in=["routine", "pipeline"]):
        sched = r.frontmatter.get("schedule")
        if not isinstance(sched, dict):
            continue
        times = sched.get("times")
        interval = sched.get("interval")
        if times and interval:
            report.add(
                LintIssue(
                    category=8,
                    severity="error",
                    file=r.rel_path,
                    message="Schedule has both `times` and `interval` (mutually exclusive)",
                )
            )
        if not times and not interval:
            report.add(
                LintIssue(
                    category=8,
                    severity="error",
                    file=r.rel_path,
                    message="Schedule has neither `times` nor `interval`",
                )
            )
        days = sched.get("days")
        if days is not None and isinstance(days, list) and not days:
            report.add(
                LintIssue(
                    category=8,
                    severity="warning",
                    file=r.rel_path,
                    message="Schedule has empty `days` list",
                )
            )
        until = sched.get("until")
        if until:
            try:
                d = date.fromisoformat(str(until).strip())
                if d < today:
                    report.add(
                        LintIssue(
                            category=8,
                            severity="warning",
                            file=r.rel_path,
                            message=f"Schedule `until` is in the past: {until}",
                        )
                    )
            except ValueError:
                report.add(
                    LintIssue(
                        category=8,
                        severity="error",
                        file=r.rel_path,
                        message=f"Schedule `until` is not a valid YYYY-MM-DD: {until}",
                    )
                )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


LINT_PASSES = [
    (1, lint_missing_frontmatter),
    (2, lint_broken_wikilinks),
    (3, lint_orphans),
    (4, lint_broken_prompt_files),
    (5, lint_stale_routines),  # Special — needs stale_days
    (6, lint_step_file_leakage),
    (7, lint_index_drift),
    (8, lint_schedule_sanity),
]


def lint_vault(
    vault_dir: Path,
    categories: Optional[List[int]] = None,
    stale_days: int = 14,
) -> LintReport:
    vi = load_vault(vault_dir)
    report = LintReport(files_scanned=len(vi))
    selected = set(categories) if categories else None
    for cat, fn in LINT_PASSES:
        if selected and cat not in selected:
            continue
        if cat == 5:
            fn(vi, report, stale_days)
        else:
            fn(vi, report)
    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_vault_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "vault"


def _format_text_report(report: LintReport) -> str:
    if report.is_clean:
        return f"✅ Vault clean ({report.files_scanned} files scanned, 0 issues)"
    lines = [
        f"⚠️  Vault lint: {len(report.issues)} issue(s) across {report.files_scanned} file(s)",
        "",
    ]
    by_cat: Dict[int, List[LintIssue]] = {}
    for issue in report.issues:
        by_cat.setdefault(issue.category, []).append(issue)
    cat_names = {
        1: "Missing frontmatter",
        2: "Broken wikilinks",
        3: "Orphan files",
        4: "Broken prompt_file",
        5: "Stale routines",
        6: "Step-file leakage",
        7: "Index drift",
        8: "Schedule sanity",
    }
    for cat in sorted(by_cat):
        lines.append(f"## [{cat}] {cat_names.get(cat, '?')}  ({len(by_cat[cat])})")
        for issue in by_cat[cat]:
            sev = "❌" if issue.severity == "error" else "⚠️"
            lines.append(f"  {sev} {issue.file}: {issue.message}")
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description="Lint the vault for hygiene issues.")
    p.add_argument("--vault", type=Path, default=_default_vault_dir())
    p.add_argument("--category", type=int, nargs="*", help="Run only these categories")
    p.add_argument("--stale-days", type=int, default=14)
    p.add_argument("--json", action="store_true")
    p.add_argument(
        "--exit-code",
        action="store_true",
        help="Exit with non-zero status if issues found",
    )
    args = p.parse_args()

    report = lint_vault(args.vault, args.category, args.stale_days)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(_format_text_report(report))

    if args.exit_code and not report.is_clean:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
