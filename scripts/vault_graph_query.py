#!/usr/bin/env python3
"""
vault_graph_query.py — cheap graph neighborhood lookup for the vault.

Pure stdlib. Built on vault_query (which loads `.graphs/graph.json` if
present and falls back to wikilink traversal otherwise).

Use this BEFORE doing extensive globbing in the vault when you only need
to find files related to a specific topic. The cost is a single JSON read
+ a BFS — way cheaper than rglobbing dozens of files.

CLI:

    python3 scripts/vault_graph_query.py --node crypto-bro --depth 2
    python3 scripts/vault_graph_query.py --node Routines/crypto-news.md
    python3 scripts/vault_graph_query.py --node Notes/polymarket --type related_to
    python3 scripts/vault_graph_query.py --node crypto-bro --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vault_query import VaultFile, load_vault  # noqa: E402


def _default_vault_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "vault"


def main() -> int:
    p = argparse.ArgumentParser(description="Walk the vault knowledge graph.")
    p.add_argument("--vault", type=Path, default=_default_vault_dir())
    p.add_argument(
        "--node",
        required=True,
        help="Starting node — accepts a relative path, node_id, or stem name.",
    )
    p.add_argument("--depth", type=int, default=1, help="BFS depth (default 1)")
    p.add_argument(
        "--type",
        choices=("references", "related_to", "all"),
        default="all",
        help="Filter edges by relation type (uses graph.json edges)",
    )
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    vi = load_vault(args.vault)
    start = vi.get(args.node)
    if start is None:
        sys.stderr.write(f"❌ Node not found: {args.node}\n")
        sys.stderr.write(
            "Try the relative path (e.g. `Routines/crypto-news.md`) or the "
            "stem (e.g. `crypto-news`).\n"
        )
        return 1

    related = vi.related(args.node, depth=args.depth)

    # If --type is set and graph.json exists, filter edges in a second pass
    if args.type != "all":
        graph_path = args.vault / ".graphs" / "graph.json"
        if graph_path.is_file():
            try:
                graph = json.loads(graph_path.read_text(encoding="utf-8"))
                allowed_node_ids = {start.node_id}
                for edge in graph.get("edges", []):
                    if edge.get("relation") != args.type:
                        continue
                    src, tgt = edge.get("source"), edge.get("target")
                    if src == start.node_id and tgt:
                        allowed_node_ids.add(tgt)
                    elif tgt == start.node_id and src:
                        allowed_node_ids.add(src)
                related = [r for r in related if r.node_id in allowed_node_ids]
            except (OSError, json.JSONDecodeError):
                pass

    if args.limit:
        related = related[: args.limit]

    if args.json:
        out = {
            "from": {"node_id": start.node_id, "path": start.rel_path, "type": start.type},
            "depth": args.depth,
            "count": len(related),
            "results": [
                {
                    "path": r.rel_path,
                    "node_id": r.node_id,
                    "type": r.type,
                    "title": r.title,
                    "description": r.description,
                    "tags": r.tags,
                }
                for r in related
            ],
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        print(f"From: [{start.type}] {start.rel_path}")
        print(f"Depth: {args.depth}")
        if not related:
            print("(no related files)")
            return 0
        print(f"\n{len(related)} related file(s):")
        for r in related:
            line = f"  [{r.type}] {r.rel_path}"
            if r.title and r.title != r.path.stem:
                line += f" — {r.title}"
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
