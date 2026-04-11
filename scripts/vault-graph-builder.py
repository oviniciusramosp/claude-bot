#!/usr/bin/env python3
"""
vault-graph-builder.py — Generate a lightweight knowledge graph from the vault.

Extracts nodes from YAML frontmatter and edges from wikilinks.
No LLM calls, no external dependencies beyond Python stdlib.
Output: vault/.graphs/graph.json (compatible with Graphify query format).

Usage:
    python3 scripts/vault-graph-builder.py [--vault PATH] [--output PATH]
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Share parsing logic with the bot and the query layer.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vault_frontmatter import (  # noqa: E402
    extract_wikilinks,
    normalize_id,
    parse_frontmatter,
)

VAULT_DIR = Path(__file__).resolve().parent.parent / "vault"
OUTPUT_DIR = VAULT_DIR / ".graphs"

# Parse CLI args
args = sys.argv[1:]
i = 0
while i < len(args):
    if args[i] == "--vault" and i + 1 < len(args):
        VAULT_DIR = Path(args[i + 1])
        OUTPUT_DIR = VAULT_DIR / ".graphs"
        i += 2
    elif args[i] == "--output" and i + 1 < len(args):
        OUTPUT_DIR = Path(args[i + 1])
        i += 2
    else:
        i += 1

# parse_frontmatter, extract_wikilinks, normalize_id, FRONTMATTER_RE, and
# WIKILINK_RE are imported from vault_frontmatter at the top of this file.


def _is_agent_root(candidate: Path) -> bool:
    """Return True iff `candidate` is a directory with `agent-<dirname>.md` inside.

    v3.4: each agent's hub file is named after the directory itself
    (`agent-main.md` inside `main/`, `agent-crypto-bro.md` inside `crypto-bro/`).
    """
    return (candidate / f"agent-{candidate.name}.md").is_file()


def _agent_from_source_dir(source_dir: Path, vault_dir: Path) -> Optional[Path]:
    """Return the ``<agent>/`` root for the folder containing a source file.

    Given a source dir like ``vault/crypto-bro/Routines/``, returns
    ``vault/crypto-bro``. Returns ``None`` when the source file isn't inside
    an agent directory (e.g. the top-level README/CLAUDE.md/Tooling.md).
    """
    try:
        rel = source_dir.relative_to(vault_dir)
    except ValueError:
        return None
    parts = rel.parts
    if not parts:
        return None
    candidate = vault_dir / parts[0]
    if _is_agent_root(candidate):
        return candidate
    return None


def resolve_wikilink(link, source_dir, vault_dir):
    """Resolve a wikilink target to a file path relative to vault.

    v3.1 flat per-agent layout: every agent lives directly at the vault root
    (``vault/<id>/Skills/``, ``vault/<id>/Routines/``, …). Wikilinks inside an
    agent's files should resolve within that agent's subtree first; top-level
    wikilinks (from README.md or CLAUDE.md) may reference any agent via a
    path-qualified form like ``[[main/agent-info]]``.

    Resolution order:
    1. Inside the same directory as the source file (or the exact path if
       the link contains a ``/``).
    2. Inside any sibling subfolder of the same agent (Skills/Routines/…).
    3. Direct child of vault root (matches agent hub references like
       ``[[main/agent-info]]``).
    4. Anywhere else via rglob (last-resort fallback).
    """
    link = link.split("#")[0].strip()
    if not link:
        return None

    candidates = [
        source_dir / f"{link}.md",
        source_dir / link / f"{link}.md",
        vault_dir / f"{link}.md",
    ]

    # Same-agent sibling subfolders (isolamento total: never leave the agent).
    agent_root = _agent_from_source_dir(source_dir, vault_dir)
    if agent_root is not None:
        for subdir in ("Skills", "Routines", "Journal", "Notes", "Reactions",
                       "Lessons", ".workspace"):
            candidates.append(agent_root / subdir / f"{link}.md")
        candidates.append(agent_root / f"{link}.md")

    # Path-qualified wikilinks resolve against the vault root.
    if "/" in link:
        candidates.append(vault_dir / f"{link}.md")

    for c in candidates:
        if c.exists():
            return c.relative_to(vault_dir)

    # Last-resort rglob
    for match in vault_dir.rglob(f"{link}.md"):
        if ".graphs" not in str(match) and ".obsidian" not in str(match):
            return match.relative_to(vault_dir)

    return None


# Files/dirs that exist on disk but should NOT appear in the knowledge graph.
# These are ephemeral runtime artifacts (pipeline outputs, daily logs, bot
# reactions, agent metadata) — not knowledge nodes. Including them pollutes
# the graph with orphans and forces editors to add fake backlinks.
DAILY_JOURNAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def is_ephemeral(filepath: Path, vault_dir: Path) -> bool:
    """Return True if the file is runtime data, not a knowledge node."""
    try:
        rel = filepath.relative_to(vault_dir)
    except ValueError:
        return False
    parts = rel.parts

    # Pipeline runtime workspace (any depth). v3.5 dot-prefixes it so Obsidian
    # hides it from the graph view, but the graph builder must exclude it too
    # so we don't create knowledge-graph nodes for pipeline step outputs.
    if ".workspace" in parts or "workspace" in parts:
        return True
    # Bot reactions (webhook config, not knowledge) — v3.1: per-agent reactions.
    if "Reactions" in parts:
        return True
    # Daily journal entries (YYYY-MM-DD.md) at any level — keep Journal.md indexes
    if "Journal" in parts and DAILY_JOURNAL_RE.match(filepath.name):
        return True
    # Routine execution history rollups (<agent>/Routines/.history/YYYY-MM.md).
    if ".history" in parts:
        return True
    # Per-agent CLAUDE.md instruction files are read by Claude CLI, not browsed
    # in the graph. agent-info.md IS a graph node (the hub), so it stays in.
    if len(parts) >= 2 and filepath.name == "CLAUDE.md":
        return True
    return False


def build_graph(vault_dir):
    """Build the knowledge graph from vault markdown files."""
    vault_dir = Path(vault_dir)
    nodes = []
    edges = []
    node_ids = set()

    # Collect all markdown files
    md_files = sorted(
        f
        for f in vault_dir.rglob("*.md")
        if ".graphs" not in str(f)
        and ".obsidian" not in str(f)
        and ".claude" not in str(f)
        and "__pycache__" not in str(f)
        and not is_ephemeral(f, vault_dir)
    )

    for filepath in md_files:
        try:
            text = filepath.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        fm = parse_frontmatter(text)
        node_id = normalize_id(filepath, vault_dir)
        rel_path = str(filepath.relative_to(vault_dir))

        # Derive owning agent from the path (<agent>/...). Top-level files
        # like README.md / CLAUDE.md / Tooling.md have agent=None — they are
        # the shared vault surface.
        rel_parts = Path(rel_path).parts
        owner_agent = None
        if len(rel_parts) >= 2:
            first = vault_dir / rel_parts[0]
            if _is_agent_root(first):
                owner_agent = rel_parts[0]

        # Create node
        node = {
            "id": node_id,
            "label": fm.get("title", filepath.stem),
            "file_type": "document",
            "source_file": rel_path,
            "type": fm.get("type", "unknown"),
            "description": fm.get("description", ""),
            "tags": fm.get("tags", []),
            "created": fm.get("created", ""),
            "updated": fm.get("updated", ""),
            "agent": owner_agent,
        }
        nodes.append(node)
        node_ids.add(node_id)

        # Extract wikilink edges
        wikilinks = extract_wikilinks(text)
        for link in wikilinks:
            resolved = resolve_wikilink(link, filepath.parent, vault_dir)
            if resolved:
                target_id = normalize_id(vault_dir / resolved, vault_dir)
                edges.append(
                    {
                        "source": node_id,
                        "target": target_id,
                        "relation": "references",
                        "confidence": "EXTRACTED",
                        "confidence_score": 1.0,
                        "source_file": rel_path,
                        "weight": 1.0,
                    }
                )

        # Extract related edges from frontmatter
        for rel in fm.get("related", []):
            target_file = rel.get("file", "")
            resolved = resolve_wikilink(target_file, filepath.parent, vault_dir)
            if resolved:
                target_id = normalize_id(vault_dir / resolved, vault_dir)
                conf_type = rel.get("type", "inferred").upper()
                conf_score = {"EXTRACTED": 1.0, "INFERRED": 0.7, "AMBIGUOUS": 0.3}.get(
                    conf_type, 0.5
                )
                edges.append(
                    {
                        "source": node_id,
                        "target": target_id,
                        "relation": "related_to",
                        "confidence": conf_type,
                        "confidence_score": conf_score,
                        "source_file": rel_path,
                        "reason": rel.get("reason", ""),
                        "weight": conf_score,
                    }
                )

    # Filter edges to only reference existing nodes
    edges = [e for e in edges if e["source"] in node_ids and e["target"] in node_ids]

    # Remove duplicate edges
    seen = set()
    unique_edges = []
    for e in edges:
        key = (e["source"], e["target"], e["relation"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(e)

    return {
        "nodes": nodes,
        "edges": unique_edges,
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "generator": "vault-graph-builder",
            "vault_path": str(vault_dir),
            "total_nodes": len(nodes),
            "total_edges": len(unique_edges),
        },
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    graph = build_graph(VAULT_DIR)
    output_path = OUTPUT_DIR / "graph.json"
    output_path.write_text(json.dumps(graph, indent=2, ensure_ascii=False))
    print(
        f"Graph generated: {graph['metadata']['total_nodes']} nodes, "
        f"{graph['metadata']['total_edges']} edges → {output_path}"
    )


if __name__ == "__main__":
    main()
