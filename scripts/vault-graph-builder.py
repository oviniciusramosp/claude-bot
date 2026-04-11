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
import os
import re
import sys
from datetime import datetime
from pathlib import Path

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

# Regex patterns
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
YAML_LIST_RE = re.compile(r"^\s*-\s+(.+)$", re.MULTILINE)
YAML_KV_RE = re.compile(r"^(\w[\w.]*)\s*:\s*(.+)$", re.MULTILINE)
RELATED_BLOCK_RE = re.compile(
    r"^related:\s*\n((?:\s+-\s+.*\n?)*)", re.MULTILINE
)
RELATED_ENTRY_RE = re.compile(
    r'file:\s*"?([^"\n,]+)"?\s*.*?type:\s*(\w+).*?reason:\s*"?([^"\n]*)"?'
)


def parse_frontmatter(text):
    """Extract frontmatter fields from markdown text."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}
    raw = m.group(1)
    fm = {}
    for kv in YAML_KV_RE.finditer(raw):
        key, val = kv.group(1), kv.group(2).strip()
        # Handle inline lists: [a, b, c]
        if val.startswith("[") and val.endswith("]"):
            fm[key] = [
                v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()
            ]
        elif val.lower() in ("true", "false"):
            fm[key] = val.lower() == "true"
        else:
            fm[key] = val.strip("\"'")
    # Parse related blocks
    rm = RELATED_BLOCK_RE.search(raw)
    if rm:
        related = []
        for entry in RELATED_ENTRY_RE.finditer(rm.group(1)):
            related.append(
                {"file": entry.group(1), "type": entry.group(2), "reason": entry.group(3)}
            )
        fm["related"] = related
    return fm


def extract_wikilinks(text):
    """Extract wikilink targets from markdown body, skipping frontmatter and
    fenced code blocks (``` ... ```). Wikilinks inside code blocks are example
    code, not real graph relationships."""
    # Strip frontmatter
    m = FRONTMATTER_RE.match(text)
    body = text[m.end() :] if m else text

    # Strip fenced code blocks before extracting wikilinks. Track open/close
    # state line-by-line so nested or mid-line backticks don't confuse us.
    in_fence = False
    cleaned = []
    for line in body.split("\n"):
        stripped = line.lstrip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        cleaned.append(line)
    return WIKILINK_RE.findall("\n".join(cleaned))


def normalize_id(filepath, vault_dir):
    """Create a stable node ID from file path."""
    rel = filepath.relative_to(vault_dir)
    return str(rel).replace("/", "_").replace(".md", "").replace(" ", "-").lower()


def resolve_wikilink(link, source_dir, vault_dir):
    """Resolve a wikilink target to a file path relative to vault."""
    # Strip section refs
    link = link.split("#")[0].strip()
    if not link:
        return None

    # Try relative to source dir first
    candidates = [
        source_dir / f"{link}.md",
        source_dir / link / f"{link}.md",
        vault_dir / f"{link}.md",
    ]
    # Search common directories
    for subdir in ["Notes", "Skills", "Routines", "Agents", "Journal"]:
        candidates.append(vault_dir / subdir / f"{link}.md")

    for c in candidates:
        if c.exists():
            return c.relative_to(vault_dir)

    # Try glob for nested paths
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

    # Pipeline runtime workspace (any depth)
    if "workspace" in parts:
        return True
    # Bot reactions (config, not knowledge)
    if parts and parts[0] == "Reactions":
        return True
    # Daily journal entries (YYYY-MM-DD.md) at any level — keep Journal.md indexes
    if "Journal" in parts and DAILY_JOURNAL_RE.match(filepath.name):
        return True
    # Agent metadata + instructions (no body / no frontmatter — not graph nodes)
    if (
        len(parts) >= 3
        and parts[0] == "Agents"
        and filepath.name in ("agent.md", "CLAUDE.md")
    ):
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
