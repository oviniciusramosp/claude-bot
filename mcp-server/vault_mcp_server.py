#!/usr/bin/env python3
"""
vault_mcp_server.py — MCP server exposing the claude-bot vault.

This is an OPTIONAL sidecar. The Telegram bot does not depend on it; the bot
remains stdlib-only. Install separately:

    cd mcp-server
    pip install -r requirements.txt
    python vault_mcp_server.py

Then point your MCP client (Claude Desktop, Cursor, sibling Claude Code
instances) at this server. Example Claude Desktop config snippet:

    {
      "mcpServers": {
        "claude-bot-vault": {
          "command": "python",
          "args": ["/absolute/path/to/claude-bot/mcp-server/vault_mcp_server.py"]
        }
      }
    }

The server wraps scripts/vault_query.py and scripts/vault_lint.py — both pure
stdlib — and exposes them as MCP tools so any MCP client can:

  - search the vault by frontmatter properties
  - read individual files with structured frontmatter
  - list folder contents (cheap, frontmatter only)
  - walk the knowledge graph
  - run the vault linter
  - create notes and append to today's journal
  - read recent execution history for a routine/pipeline

The vault location is auto-detected from the parent of `mcp-server/`, but
can be overridden by setting `CLAUDE_BOT_VAULT` in the environment.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Locate the project root and add scripts/ to sys.path so we can import
# the same helpers the bot uses.
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# Vault path: env override or `<project_root>/vault`
VAULT_DIR = Path(os.environ.get("CLAUDE_BOT_VAULT") or (PROJECT_ROOT / "vault")).resolve()

# Import the shared helpers
from vault_frontmatter import get_frontmatter_and_body  # noqa: E402
from vault_lint import lint_vault  # noqa: E402
from vault_query import (  # noqa: E402
    VaultFile,
    load_vault,
    parse_filter_expression,
)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    sys.stderr.write(
        "ERROR: the `mcp` package is not installed.\n"
        "Run: cd mcp-server && pip install -r requirements.txt\n"
        f"Original error: {exc}\n"
    )
    sys.exit(1)


mcp = FastMCP("claude-bot-vault")


def _file_to_dict(f: VaultFile) -> Dict[str, Any]:
    """Lightweight serialization of a VaultFile for MCP tool responses."""
    return {
        "path": f.rel_path,
        "node_id": f.node_id,
        "type": f.type,
        "title": f.title,
        "description": f.description,
        "tags": f.tags,
        "frontmatter": f.frontmatter,
    }


# ---------------------------------------------------------------------------
# Tool: vault_search
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_search(filter_expr: str = "", limit: int = 50) -> Dict[str, Any]:
    """Search the vault by frontmatter properties.

    `filter_expr` follows the same syntax as the bot's /find command:

        type=routine model=opus enabled=true
        type=skill tags__contains=publish
        type=pipeline agent=crypto-bro

    Suffixes supported: __contains, __in, __startswith, __endswith, __exists.

    Returns up to `limit` matches with their frontmatter.
    """
    vi = load_vault(VAULT_DIR)
    filters = parse_filter_expression(filter_expr) if filter_expr else {}
    results = vi.find(**filters)
    if limit:
        results = results[:limit]
    return {
        "filter": filter_expr,
        "count": len(results),
        "results": [_file_to_dict(r) for r in results],
    }


# ---------------------------------------------------------------------------
# Tool: vault_read
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_read(path: str) -> Dict[str, Any]:
    """Read a single vault file by relative path (or node_id).

    Returns frontmatter + body. Returns an error message if the path does
    not resolve to any vault file.
    """
    vi = load_vault(VAULT_DIR)
    f = vi.get(path)
    if f is None:
        return {"error": f"not found: {path}"}
    return {
        "path": f.rel_path,
        "node_id": f.node_id,
        "frontmatter": f.frontmatter,
        "body": f.body,
        "wikilinks": f.wikilinks,
    }


# ---------------------------------------------------------------------------
# Tool: vault_list
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_list(folder: str = "") -> Dict[str, Any]:
    """List files in a vault folder (frontmatter only — cheap).

    `folder` is a path relative to the vault root (e.g. `Routines`, `Skills`).
    Empty string lists everything at the root level.
    """
    vi = load_vault(VAULT_DIR)
    folder = folder.strip("/")
    results: List[Dict[str, Any]] = []
    for f in vi:
        if folder and not f.rel_path.startswith(folder + "/"):
            continue
        results.append(
            {
                "path": f.rel_path,
                "type": f.type,
                "title": f.title,
                "description": f.description,
                "tags": f.tags,
            }
        )
    return {"folder": folder or "(root)", "count": len(results), "results": results}


# ---------------------------------------------------------------------------
# Tool: vault_related
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_related(path: str, depth: int = 1) -> Dict[str, Any]:
    """Walk the knowledge graph from a starting file.

    Uses vault/.graphs/graph.json when present, falls back to wikilink
    traversal otherwise. Returns the set of files reachable within `depth`
    edges from the starting node.
    """
    vi = load_vault(VAULT_DIR)
    related = vi.related(path, depth=depth)
    return {
        "from": path,
        "depth": depth,
        "count": len(related),
        "results": [_file_to_dict(r) for r in related],
    }


# ---------------------------------------------------------------------------
# Tool: vault_lint
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_lint_tool(stale_days: int = 14) -> Dict[str, Any]:
    """Run the vault hygiene linter and return a structured JSON report.

    Detects: missing frontmatter, broken wikilinks, orphan files, broken
    pipeline `prompt_file` references, stale routines (no execution in
    `stale_days`), step-file leakage, index drift, and schedule sanity issues.
    """
    report = lint_vault(VAULT_DIR, stale_days=stale_days)
    return report.to_dict()


# ---------------------------------------------------------------------------
# Tool: vault_create_note
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_create_note(
    slug: str, summary: str, tags: Optional[List[str]] = None
) -> Dict[str, Any]:
    """Create a new Notes/{slug}.md file with proper frontmatter.

    Refuses to overwrite an existing note (the bot's auto-extraction path
    handles updates by appending `## Update YYYY-MM-DD` instead).

    `tags` are added on top of the default `[note, mcp]`.
    """
    notes_dir = VAULT_DIR / "Notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    safe_slug = slug.strip().lower().replace(" ", "-")
    if not safe_slug or "/" in safe_slug or ".." in safe_slug:
        return {"error": f"invalid slug: {slug!r}"}
    path = notes_dir / f"{safe_slug}.md"
    if path.exists():
        return {"error": f"note already exists: {path.relative_to(VAULT_DIR).as_posix()}"}
    today = time.strftime("%Y-%m-%d")
    tag_list = ["note", "mcp"] + list(tags or [])
    tag_str = "[" + ", ".join(tag_list) + "]"
    text = (
        f"---\n"
        f'title: "{safe_slug}"\n'
        f'description: "{summary[:140]}"\n'
        f"type: note\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"tags: {tag_str}\n"
        f"---\n\n"
        f"[[Notes]]\n\n"
        f"{summary}\n"
    )
    path.write_text(text, encoding="utf-8")
    return {"created": path.relative_to(VAULT_DIR).as_posix()}


# ---------------------------------------------------------------------------
# Tool: vault_append_journal
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_append_journal(text: str, agent_id: Optional[str] = None) -> Dict[str, Any]:
    """Append a timestamped entry to today's journal.

    If `agent_id` is provided, appends to vault/Agents/{agent_id}/Journal/
    instead of the main vault/Journal/.
    """
    today = time.strftime("%Y-%m-%d")
    timestamp = time.strftime("%H:%M")
    if agent_id:
        journal_dir = VAULT_DIR / "Agents" / agent_id / "Journal"
    else:
        journal_dir = VAULT_DIR / "Journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal_path = journal_dir / f"{today}.md"
    if not journal_path.exists():
        header = (
            f"---\n"
            f'title: "Journal {today}"\n'
            f'description: "Daily log for {today}."\n'
            f"type: journal\n"
            f"created: {today}\n"
            f"updated: {today}\n"
            f"tags: [journal]\n"
            f"---\n\n"
        )
        journal_path.write_text(header, encoding="utf-8")
    entry = f"## {timestamp}\n\n{text.strip()}\n\n---\n\n"
    with journal_path.open("a", encoding="utf-8") as f:
        f.write(entry)
    return {
        "appended_to": journal_path.relative_to(VAULT_DIR).as_posix(),
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Tool: vault_history
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_history(routine: Optional[str] = None, limit: int = 20) -> Dict[str, Any]:
    """Read recent routine/pipeline execution records from the history rollup.

    With no `routine` argument, returns the most recent N records across all
    routines. With `routine` set, filters to that routine only.
    """
    vi = load_vault(VAULT_DIR)
    history_files = vi.find(type="history")
    if not history_files:
        return {"count": 0, "records": [], "note": "no history rollup files yet"}

    # Concatenate all history bodies, then split into per-record blocks.
    combined = "\n".join(h.body for h in history_files)
    records: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in combined.split("\n"):
        if line.startswith("## "):
            if current:
                records.append(current)
            # `## YYYY-MM-DD HH:MM — name`
            header = line[3:].strip()
            parts = header.split(" — ", 1)
            timestamp = parts[0] if parts else ""
            name = parts[1] if len(parts) > 1 else ""
            current = {"timestamp": timestamp, "name": name, "fields": {}}
        elif current and line.startswith("- "):
            kv = line[2:].split(":", 1)
            if len(kv) == 2:
                current["fields"][kv[0].strip()] = kv[1].strip()
    if current:
        records.append(current)

    # Filter by routine name if requested
    if routine:
        records = [r for r in records if r["name"] == routine]
    # Most recent first
    records.sort(key=lambda r: r["timestamp"], reverse=True)
    if limit:
        records = records[:limit]
    return {"count": len(records), "records": records}


# ---------------------------------------------------------------------------
# Resources (read-only data exposed alongside the tools)
# ---------------------------------------------------------------------------


@mcp.resource("vault://routines")
def routines_resource() -> str:
    """Auto-rendered list of all routines with their schedule + agent."""
    vi = load_vault(VAULT_DIR)
    lines = ["# Routines\n"]
    for r in vi.find(type__in=["routine", "pipeline"]):
        sched = r.frontmatter.get("schedule", {})
        times = sched.get("times") if isinstance(sched, dict) else None
        time_str = ", ".join(times) if isinstance(times, list) else "—"
        lines.append(
            f"- **{r.path.stem}** ({r.type}) — {r.description} _[{time_str}]_"
        )
    return "\n".join(lines)


@mcp.resource("vault://skills")
def skills_resource() -> str:
    """Auto-rendered list of all skills."""
    vi = load_vault(VAULT_DIR)
    lines = ["# Skills\n"]
    for s in sorted(vi.find(type="skill"), key=lambda x: x.path.stem):
        lines.append(f"- **{s.path.stem}** — {s.description}")
    return "\n".join(lines)


@mcp.resource("vault://graph")
def graph_resource() -> str:
    """Raw contents of vault/.graphs/graph.json (the lightweight knowledge graph)."""
    graph_path = VAULT_DIR / ".graphs" / "graph.json"
    if not graph_path.is_file():
        return "{}"
    return graph_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    sys.stderr.write(f"claude-bot-vault MCP server starting (vault: {VAULT_DIR})\n")
    mcp.run()


if __name__ == "__main__":
    main()
