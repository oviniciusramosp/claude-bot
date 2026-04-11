#!/usr/bin/env python3
"""
vault_indexes.py — auto-regenerate vault index files from vault_query.

Pure stdlib. Built on vault_query. Walks the vault, finds files containing
marker blocks of the form:

    <!-- vault-query:start filter="type=routine" sort="title" format="- [[{stem}]] — {description}" -->
    (auto-generated content here, will be replaced)
    <!-- vault-query:end -->

Re-renders the inner content using the live vault state. Manual edits OUTSIDE
the markers are preserved verbatim. Manual edits INSIDE are overwritten on
the next run.

Why this beats Obsidian Bases (.base files): an AI walking the vault by
filesystem sees live data inline as plain markdown — no plugin, no rendering
step required. Humans browsing in Obsidian get the same content.

Marker directives (all optional except `filter`):

    filter="type=routine model=opus enabled=true"
        Same syntax as `vault_query.parse_filter_expression`. Supports
        Django-style suffixes (__contains, __in, __startswith, __endswith,
        __exists).

    sort="title"
        Field name to sort by (asc). Prefix with `-` for descending. Default: title.

    group_by="agent"
        If set, results are grouped under `### {field}: {value}` headers.
        Files missing the field land in a `### {field}: —` group at the end.

    format="- [[{stem}]] — {description}"
        Per-row format string. Placeholders are pulled from frontmatter,
        plus the synthetic fields {stem}, {title}, {description}, {tags},
        {path}, {type}. Missing values render as empty string.

    empty="(no matches)"
        Text to render when the query has zero results.

    limit=N
        Cap the number of results.

CLI:

    python3 scripts/vault_indexes.py                # update all index files
    python3 scripts/vault_indexes.py --check        # exit 1 if any file would change
    python3 scripts/vault_indexes.py --vault PATH
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vault_query import VaultFile, VaultIndex, load_vault, parse_filter_expression  # noqa: E402

MARKER_START_RE = re.compile(
    r"<!--\s*vault-query:start\s+(.*?)\s*-->",
    re.DOTALL,
)
MARKER_END = "<!-- vault-query:end -->"
DIRECTIVE_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def _parse_directives(raw: str) -> Dict[str, str]:
    return {m.group(1): m.group(2) for m in DIRECTIVE_RE.finditer(raw)}


def _format_row(template: str, f: VaultFile) -> str:
    """Substitute placeholders in `template` with frontmatter values from `f`."""
    synthetic = {
        "stem": f.path.stem,
        "title": f.title,
        "description": f.description,
        "tags": ", ".join(f.tags),
        "path": f.rel_path,
        "type": f.type,
        "node_id": f.node_id,
        # `parent` = name of the directory containing the file. Useful for
        # files like Agents/{id}/agent.md where the link target is `{id}`,
        # not `agent`. Falls back to "" at the vault root.
        "parent": f.path.parent.name if f.path.parent.name else "",
    }

    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key in synthetic:
            return synthetic[key] or ""
        v = f.frontmatter.get(key)
        if v is None:
            return ""
        if isinstance(v, list):
            return ", ".join(str(x) for x in v)
        if isinstance(v, dict):
            # Render dicts as `k=v` pairs (compact, useful for schedule)
            return ", ".join(f"{k}={vv}" for k, vv in v.items())
        return str(v)

    return re.sub(r"\{(\w+)\}", repl, template)


def _sort_files(files: List[VaultFile], sort_spec: str) -> List[VaultFile]:
    spec = sort_spec.strip()
    reverse = False
    if spec.startswith("-"):
        reverse = True
        spec = spec[1:]
    field = spec or "title"

    def key(f: VaultFile) -> Tuple[int, str]:
        if field == "title":
            v = f.title
        elif field == "stem":
            v = f.path.stem
        elif field == "path":
            v = f.rel_path
        elif field == "type":
            v = f.type
        else:
            raw = f.frontmatter.get(field, "")
            v = "" if raw is None else str(raw)
        # Files with empty key sort last in ascending order, first in descending
        return (0 if v else 1, v.lower() if isinstance(v, str) else str(v))

    return sorted(files, key=key, reverse=reverse)


def _render_block(vi: VaultIndex, directives: Dict[str, str]) -> str:
    """Render a single marker block from directives + vault index."""
    filter_expr = directives.get("filter", "")
    fmt = directives.get("format", "- [[{stem}]] — {description}")
    sort_spec = directives.get("sort", "title")
    group_by = directives.get("group_by")
    empty_text = directives.get("empty", "_(no matches)_")
    limit = int(directives.get("limit", "0") or 0)

    filters = parse_filter_expression(filter_expr) if filter_expr else {}
    files = vi.find(**filters)
    files = _sort_files(files, sort_spec)
    if limit:
        files = files[:limit]

    if not files:
        return empty_text

    if group_by:
        groups: Dict[str, List[VaultFile]] = {}
        for f in files:
            g = f.frontmatter.get(group_by)
            if g is None:
                key = "—"
            elif isinstance(g, bool):
                key = "true" if g else "false"
            elif isinstance(g, list):
                key = ", ".join(str(x) for x in g) or "—"
            else:
                key = str(g)
            groups.setdefault(key, []).append(f)
        out_lines: List[str] = []
        for k in sorted(groups.keys(), key=lambda s: (s == "—", s.lower())):
            out_lines.append(f"### {group_by}: {k}")
            out_lines.append("")
            for f in groups[k]:
                out_lines.append(_format_row(fmt, f))
            out_lines.append("")
        return "\n".join(out_lines).rstrip()
    else:
        return "\n".join(_format_row(fmt, f) for f in files)


def regenerate_file(filepath: Path, vi: VaultIndex) -> Tuple[bool, str]:
    """Regenerate marker blocks in a single file. Returns (changed, new_text)."""
    original = filepath.read_text(encoding="utf-8")
    out: List[str] = []
    pos = 0
    changed = False
    while True:
        start_match = MARKER_START_RE.search(original, pos)
        if not start_match:
            out.append(original[pos:])
            break
        # Append everything up to the start marker (inclusive)
        out.append(original[pos : start_match.end()])
        end_idx = original.find(MARKER_END, start_match.end())
        if end_idx == -1:
            # Unterminated marker — bail and leave as-is
            out.append(original[start_match.end() :])
            break
        directives = _parse_directives(start_match.group(1))
        rendered = _render_block(vi, directives)
        # Always sandwich the rendered block in newlines so the markers stay
        # on their own lines.
        new_block = "\n" + rendered + "\n"
        old_block = original[start_match.end() : end_idx]
        if new_block != old_block:
            changed = True
        out.append(new_block)
        out.append(MARKER_END)
        pos = end_idx + len(MARKER_END)
    return changed, "".join(out)


def find_marker_files(vault_dir: Path) -> List[Path]:
    """Return all .md files containing a vault-query marker."""
    results: List[Path] = []
    for md in vault_dir.rglob("*.md"):
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "vault-query:start" in text:
            results.append(md)
    return results


def regenerate_vault(
    vault_dir: Path, check_only: bool = False
) -> Tuple[List[Path], List[Path]]:
    """Regenerate all marker blocks in the vault.

    Returns (changed_files, all_files_scanned). In check_only mode, no
    writes are performed but the changed list is still populated.
    """
    vi = load_vault(vault_dir)
    files = find_marker_files(vault_dir)
    changed: List[Path] = []
    for f in files:
        was_changed, new_text = regenerate_file(f, vi)
        if was_changed:
            changed.append(f)
            if not check_only:
                f.write_text(new_text, encoding="utf-8")
    return changed, files


def _default_vault_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "vault"


def main() -> int:
    p = argparse.ArgumentParser(description="Regenerate vault index marker blocks.")
    p.add_argument("--vault", type=Path, default=_default_vault_dir())
    p.add_argument(
        "--check",
        action="store_true",
        help="Don't write — exit 1 if any file would change",
    )
    args = p.parse_args()

    changed, scanned = regenerate_vault(args.vault, check_only=args.check)
    if not scanned:
        print("(no marker files found)")
        return 0
    if args.check:
        if changed:
            print(f"⚠️  {len(changed)} file(s) would change:")
            for f in changed:
                print(f"  - {f.relative_to(args.vault)}")
            return 1
        print(f"✅ All {len(scanned)} marker files are up to date.")
        return 0
    if changed:
        print(f"✅ Updated {len(changed)} of {len(scanned)} marker file(s):")
        for f in changed:
            print(f"  - {f.relative_to(args.vault)}")
    else:
        print(f"✅ All {len(scanned)} marker files already up to date.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
