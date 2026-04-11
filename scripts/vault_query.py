#!/usr/bin/env python3
"""
vault_query.py — frontmatter-aware query layer over the vault.

Pure stdlib. Built on vault_frontmatter. Imported by:
  - claude-fallback-bot.py (for /find, /lint, _find_relevant_skills)
  - scripts/vault_lint.py
  - scripts/vault_indexes.py
  - mcp-server/vault_mcp_server.py (optional sidecar)

Conceptual API:

    from vault_query import load_vault
    vi = load_vault(Path("vault"))
    routines = vi.find(type="routine", enabled=True, model="opus")
    skills = vi.find(type="skill", tags__contains="publish")
    related = vi.related("Routines/crypto-news", depth=2)
    matches = vi.search_text("polymarket", fields=("title", "description", "tags"))

Filter operators (Django-style suffix):
  - field=value           equality (after type coercion)
  - field__contains=v     substring (strings) or membership (lists)
  - field__in=[a, b]      value in list
  - field__startswith=v
  - field__endswith=v
  - field__exists=True    field present in frontmatter

Also supports CLI usage:

    python3 scripts/vault_query.py --type routine --model opus --json
    python3 scripts/vault_query.py --search "crypto" --json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple

# Allow running as `python3 scripts/vault_query.py` directly
sys.path.insert(0, str(Path(__file__).resolve().parent))

from vault_frontmatter import (  # noqa: E402
    extract_wikilinks,
    get_frontmatter_and_body,
    normalize_id,
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class VaultFile:
    """A single vault markdown file with parsed frontmatter."""

    path: Path  # Absolute path
    rel_path: str  # Path relative to vault root, posix style
    node_id: str  # Stable ID matching graph.json
    frontmatter: Dict[str, Any] = field(default_factory=dict)
    body: str = ""
    wikilinks: List[str] = field(default_factory=list)

    @property
    def type(self) -> str:
        return str(self.frontmatter.get("type", "unknown"))

    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title", self.path.stem))

    @property
    def description(self) -> str:
        return str(self.frontmatter.get("description", ""))

    @property
    def tags(self) -> List[str]:
        t = self.frontmatter.get("tags", [])
        if isinstance(t, list):
            return [str(x) for x in t]
        if isinstance(t, str):
            return [t]
        return []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.rel_path,
            "node_id": self.node_id,
            "type": self.type,
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "frontmatter": self.frontmatter,
        }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


# Directories that are not part of the queryable vault surface.
EXCLUDED_DIR_NAMES = {".graphs", ".obsidian", ".claude", "__pycache__"}


def _is_excluded(filepath: Path, vault_dir: Path) -> bool:
    try:
        rel = filepath.relative_to(vault_dir)
    except ValueError:
        return True
    return any(part in EXCLUDED_DIR_NAMES for part in rel.parts)


def load_vault(vault_dir: Path) -> "VaultIndex":
    """Walk the vault and load every markdown file into a VaultIndex."""
    vault_dir = Path(vault_dir).resolve()
    files: List[VaultFile] = []
    for md in sorted(vault_dir.rglob("*.md")):
        if _is_excluded(md, vault_dir):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        from vault_frontmatter import parse_frontmatter

        fm = parse_frontmatter(text)
        # Body is everything after the second ---
        body = ""
        lines = text.split("\n")
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() == "---":
                    body = "\n".join(lines[i + 1 :]).strip()
                    break
        wikilinks = extract_wikilinks(text)
        rel = md.relative_to(vault_dir).as_posix()
        files.append(
            VaultFile(
                path=md,
                rel_path=rel,
                node_id=normalize_id(md, vault_dir),
                frontmatter=fm,
                body=body,
                wikilinks=wikilinks,
            )
        )
    return VaultIndex(vault_dir=vault_dir, files=files)


# ---------------------------------------------------------------------------
# Query engine
# ---------------------------------------------------------------------------


class VaultIndex:
    """In-memory index of vault files with a small filter API."""

    def __init__(self, vault_dir: Path, files: List[VaultFile]):
        self.vault_dir = Path(vault_dir)
        self.files: List[VaultFile] = files
        self._by_node_id: Dict[str, VaultFile] = {f.node_id: f for f in files}
        self._by_rel_path: Dict[str, VaultFile] = {f.rel_path: f for f in files}

    def __len__(self) -> int:
        return len(self.files)

    def __iter__(self) -> Iterable[VaultFile]:
        return iter(self.files)

    # ----- Single-file lookup -----

    def get(self, key: str) -> Optional[VaultFile]:
        """Look up a file by node_id, relative path, absolute path, or stem.

        Resolution order:
            1. Exact node_id match
            2. Exact relative path match
            3. Absolute path match
            4. Relative path with .md appended
            5. File stem match (e.g. 'crypto-bro' resolves to the first
               file whose stem is 'crypto-bro' — useful for graph hub files
               and skills)
        """
        if key in self._by_node_id:
            return self._by_node_id[key]
        if key in self._by_rel_path:
            return self._by_rel_path[key]
        # Try absolute path
        try:
            ap = Path(key).resolve()
            for f in self.files:
                if f.path == ap:
                    return f
        except Exception:
            pass
        # Try relative path with .md added
        if not key.endswith(".md") and (key + ".md") in self._by_rel_path:
            return self._by_rel_path[key + ".md"]
        # Try stem match (handles agent hub files, skills referenced by stem)
        if not key.endswith(".md"):
            target_stem = key
        else:
            target_stem = key[:-3]
        for f in self.files:
            if f.path.stem == target_stem:
                return f
        return None

    # ----- Bulk filter -----

    def find(self, **filters: Any) -> List[VaultFile]:
        """Filter files by frontmatter properties.

        Supports Django-style suffixes: __contains, __in, __startswith,
        __endswith, __exists. No suffix = equality after type coercion.
        """
        if not filters:
            return list(self.files)
        out: List[VaultFile] = []
        for f in self.files:
            if all(self._match_one(f, k, v) for k, v in filters.items()):
                out.append(f)
        return out

    def find_by(self, predicate: Callable[[VaultFile], bool]) -> List[VaultFile]:
        return [f for f in self.files if predicate(f)]

    @staticmethod
    def _match_one(f: VaultFile, key: str, expected: Any) -> bool:
        # Strip suffix
        op = "eq"
        if "__" in key:
            base, _, op = key.partition("__")
            key = base

        actual: Any
        if key == "type":
            actual = f.type
        elif key == "tags":
            actual = f.tags
        elif key == "title":
            actual = f.title
        elif key == "description":
            actual = f.description
        elif key == "path":
            actual = f.rel_path
        elif key == "node_id":
            actual = f.node_id
        else:
            actual = f.frontmatter.get(key)

        if op == "exists":
            return (actual is not None) == bool(expected)

        if op == "contains":
            if isinstance(actual, list):
                return expected in actual or any(
                    isinstance(x, str) and expected in x for x in actual
                )
            if isinstance(actual, str):
                return str(expected) in actual
            return False

        if op == "in":
            if not isinstance(expected, (list, tuple, set)):
                return False
            return actual in expected

        if op == "startswith":
            return isinstance(actual, str) and actual.startswith(str(expected))

        if op == "endswith":
            return isinstance(actual, str) and actual.endswith(str(expected))

        # Default: equality with light type coercion
        if isinstance(expected, bool) and isinstance(actual, str):
            return actual.lower() in (("true", "yes") if expected else ("false", "no"))
        if isinstance(actual, bool) and isinstance(expected, str):
            return actual == (expected.lower() in ("true", "yes"))
        return actual == expected

    # ----- Text search -----

    def search_text(
        self,
        query: str,
        fields: Tuple[str, ...] = ("title", "description", "tags"),
        limit: Optional[int] = None,
    ) -> List[VaultFile]:
        """Case-insensitive substring search across frontmatter fields."""
        q = query.strip().lower()
        if not q:
            return []
        out: List[VaultFile] = []
        for f in self.files:
            for field_name in fields:
                if field_name == "tags":
                    haystack = " ".join(f.tags).lower()
                elif field_name == "body":
                    haystack = f.body.lower()
                else:
                    haystack = str(f.frontmatter.get(field_name, "")).lower()
                if q in haystack:
                    out.append(f)
                    break
            if limit is not None and len(out) >= limit:
                break
        return out

    # ----- Graph traversal -----

    def related(
        self, key: str, depth: int = 1, graph_path: Optional[Path] = None
    ) -> List[VaultFile]:
        """Walk the knowledge graph from a starting file. Uses .graphs/graph.json
        if available, falls back to wikilinks-only traversal.
        """
        start = self.get(key)
        if start is None:
            return []
        if graph_path is None:
            graph_path = self.vault_dir / ".graphs" / "graph.json"

        adjacency: Dict[str, Set[str]] = {}
        if graph_path.exists():
            try:
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
                for edge in graph.get("edges", []):
                    src = edge.get("source")
                    tgt = edge.get("target")
                    if not src or not tgt:
                        continue
                    adjacency.setdefault(src, set()).add(tgt)
                    adjacency.setdefault(tgt, set()).add(src)
            except (OSError, json.JSONDecodeError):
                pass

        if not adjacency:
            # Fallback: build from wikilinks
            for f in self.files:
                for link in f.wikilinks:
                    target = self.get(link) or self.get(link + ".md")
                    if target:
                        adjacency.setdefault(f.node_id, set()).add(target.node_id)
                        adjacency.setdefault(target.node_id, set()).add(f.node_id)

        visited: Set[str] = {start.node_id}
        frontier: Set[str] = {start.node_id}
        for _ in range(max(0, depth)):
            next_frontier: Set[str] = set()
            for node in frontier:
                for nb in adjacency.get(node, ()):
                    if nb not in visited:
                        visited.add(nb)
                        next_frontier.add(nb)
            frontier = next_frontier
            if not frontier:
                break
        visited.discard(start.node_id)
        return [self._by_node_id[nid] for nid in visited if nid in self._by_node_id]


# ---------------------------------------------------------------------------
# Filter expression parsing (for CLI / Telegram /find)
# ---------------------------------------------------------------------------


def parse_filter_expression(expr: str) -> Dict[str, Any]:
    """Parse a free-form filter expression like:

        type=routine model=opus enabled=true tags__contains=publish

    Returns a dict suitable for VaultIndex.find(**filters).
    """
    out: Dict[str, Any] = {}
    # Split on whitespace but respect quoted values
    tokens: List[str] = []
    buf: List[str] = []
    in_quote = False
    quote_char = ""
    for ch in expr.strip():
        if in_quote:
            if ch == quote_char:
                in_quote = False
            else:
                buf.append(ch)
        else:
            if ch in ('"', "'"):
                in_quote = True
                quote_char = ch
            elif ch.isspace():
                if buf:
                    tokens.append("".join(buf))
                    buf = []
            else:
                buf.append(ch)
    if buf:
        tokens.append("".join(buf))

    for tok in tokens:
        if "=" not in tok:
            continue
        k, _, v = tok.partition("=")
        k = k.strip()
        v = v.strip()
        # Coerce common values
        if v.lower() in ("true", "yes"):
            out[k] = True
        elif v.lower() in ("false", "no"):
            out[k] = False
        else:
            try:
                out[k] = int(v)
            except ValueError:
                try:
                    out[k] = float(v)
                except ValueError:
                    out[k] = v
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _default_vault_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "vault"


def main() -> int:
    p = argparse.ArgumentParser(description="Query the vault by frontmatter.")
    p.add_argument("--vault", type=Path, default=_default_vault_dir())
    p.add_argument(
        "--filter",
        action="append",
        default=[],
        help="Filter expression(s), e.g. type=routine model=opus",
    )
    p.add_argument("--search", help="Free-text search across title/description/tags")
    p.add_argument("--related", help="Show files related to this path/node_id")
    p.add_argument("--depth", type=int, default=1)
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    p.add_argument("--limit", type=int, default=0, help="Limit results (0 = no limit)")
    args = p.parse_args()

    vi = load_vault(args.vault)

    results: List[VaultFile]
    if args.related:
        results = vi.related(args.related, depth=args.depth)
    elif args.search:
        results = vi.search_text(args.search, limit=args.limit or None)
    else:
        filters: Dict[str, Any] = {}
        for expr in args.filter:
            filters.update(parse_filter_expression(expr))
        results = vi.find(**filters)
        if args.limit:
            results = results[: args.limit]

    if args.json:
        print(json.dumps([r.to_dict() for r in results], indent=2, ensure_ascii=False))
    else:
        if not results:
            print("(no results)")
            return 0
        for r in results:
            line = f"[{r.type}] {r.rel_path}"
            if r.title and r.title != r.path.stem:
                line += f" — {r.title}"
            print(line)
            if r.description:
                print(f"    {r.description}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
