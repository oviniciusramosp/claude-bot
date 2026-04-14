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
# vault_index is an optional import — if the FTS library fails to load
# (e.g. sqlite3 without FTS5), the three search/timeline/get tools below
# return a helpful error message instead of crashing the server.
try:
    import vault_index  # noqa: E402
except Exception as _vi_exc:  # pragma: no cover
    vault_index = None  # type: ignore
    _VAULT_INDEX_IMPORT_ERROR = str(_vi_exc)
else:
    _VAULT_INDEX_IMPORT_ERROR = ""

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


# ---------------------------------------------------------------------------
# Vault FTS5 index — optional cache shared with the bot
# ---------------------------------------------------------------------------

# Default index location mirrors claude-fallback-bot.py:VAULT_INDEX_DB so
# the MCP sidecar and the bot read/write the same file. Users running the
# sidecar in a non-default home can override with CLAUDE_BOT_INDEX_DB.
_VAULT_INDEX_DB = Path(
    os.environ.get("CLAUDE_BOT_INDEX_DB")
    or (Path.home() / ".claude-bot" / "vault-index.sqlite")
).resolve()

_VAULT_INDEX_CONN: Optional[Any] = None


def _get_vault_index_conn():
    """Return a cached sqlite3 connection to the index, or None.

    The connection is opened lazily on first use and reused across tool
    calls so we don't pay the FTS5 setup cost on every request. Fail-open
    everywhere — missing DB, missing FTS5 extension, and any sqlite error
    surface as None so the tools return a friendly error instead of
    crashing the MCP server.
    """
    global _VAULT_INDEX_CONN
    if vault_index is None:
        return None
    if _VAULT_INDEX_CONN is not None:
        return _VAULT_INDEX_CONN
    if not _VAULT_INDEX_DB.exists():
        return None
    try:
        _VAULT_INDEX_CONN = vault_index.connect(_VAULT_INDEX_DB)
        return _VAULT_INDEX_CONN
    except Exception as exc:
        sys.stderr.write(f"vault-index: connect failed: {exc}\n")
        return None


def _vault_index_write_through(
    agent: str,
    rel_path: str,
    journal_section: Optional[tuple] = None,
) -> None:
    """Fire-and-forget write-through from MCP write tools.

    Best-effort: any failure is logged to stderr and swallowed. The
    daily ``vault-index-update`` routine is the safety net — users never
    see a broken search because the MCP server couldn't keep the cache
    in sync.
    """
    if vault_index is None or not agent:
        return
    conn = _get_vault_index_conn()
    if conn is None:
        return
    try:
        if journal_section is not None:
            ts, text = journal_section
            vault_index.upsert_journal_section(
                conn, VAULT_DIR, agent, rel_path, ts, text,
            )
        else:
            vault_index.upsert_file(conn, VAULT_DIR, agent, rel_path)
    except Exception as exc:
        sys.stderr.write(
            f"vault-index write-through failed for {agent}/{rel_path}: {exc}\n"
        )


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
    rel = path.relative_to(VAULT_DIR).as_posix()
    # Write-through to the FTS index so the note is immediately searchable.
    # Notes created via this tool are currently vault-root scoped (legacy),
    # so we tag them under "main" for index purposes; when the MCP tool
    # grows an explicit agent_id parameter this will switch to that value.
    _vault_index_write_through(agent="main", rel_path=rel)
    return {"created": rel}


# ---------------------------------------------------------------------------
# Tool: vault_append_journal
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_append_journal(text: str, agent_id: Optional[str] = None) -> Dict[str, Any]:
    """Append a timestamped entry to today's journal.

    Writes to `vault/<agent_id>/Journal/YYYY-MM-DD.md` (v3.1 flat per-agent
    layout). If `agent_id` is omitted, defaults to "main".
    """
    today = time.strftime("%Y-%m-%d")
    timestamp = time.strftime("%H:%M")
    agent = agent_id or "main"
    journal_dir = VAULT_DIR / agent / "Journal"
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal_path = journal_dir / f"{today}.md"
    if not journal_path.exists():
        header = (
            f"---\n"
            f'title: "Journal {today}"\n'
            f'description: "pending: no entries yet"\n'
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
    rel = journal_path.relative_to(VAULT_DIR).as_posix()
    # Write-through to the FTS index so SessionStart auto-recall sees this
    # section on the very next fresh session. Fail-open per the
    # zero-silent-errors rule at the bot layer.
    _vault_index_write_through(
        agent=agent, rel_path=rel, journal_section=(timestamp, text),
    )
    return {
        "appended_to": rel,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Tool: vault_search_text  (FTS5 full-text search — v3.18+)
# ---------------------------------------------------------------------------


def _vault_index_error_payload() -> Dict[str, Any]:
    """Shared error payload when the FTS index is unavailable."""
    if vault_index is None:
        return {
            "error": "vault-index module unavailable",
            "reason": _VAULT_INDEX_IMPORT_ERROR or "import failed",
            "hint": "Ensure sqlite3 was built with FTS5 support.",
        }
    return {
        "error": "vault-index database not yet built",
        "hint": "Run scripts/vault-index-update.py or wait for the 04:05 "
                "daily vault-index-update routine.",
    }


@mcp.tool()
def vault_search_text(
    query: str,
    agent_id: str,
    kinds: Optional[List[str]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 20,
    include_private: bool = True,
) -> Dict[str, Any]:
    """Full-text search over the per-agent vault index.

    Progressive disclosure — returns a compact list of hits with integer
    IDs, titles, and FTS5 snippets (~50-100 tokens per hit). Call
    ``vault_get_excerpt`` to fetch the body of a specific entry only when
    you need it. Optionally expand context around a hit with
    ``vault_timeline``.

    Scoped hard to a single agent (contract C3) — ``agent_id`` is
    required. ``kinds`` filters by the indexed categories
    (``journal``, ``journal_weekly``, ``lesson``, ``note``). ``date_from``
    and ``date_to`` accept ``YYYY-MM-DD`` strings for journals and
    ``YYYY-Www`` for weekly rollups.

    By default, rows from files with any ``<private>`` marker are
    returned (their private TEXT has already been stripped at index time).
    Pass ``include_private=False`` to hide those files entirely — used by
    SessionStart auto-recall for extra caution.
    """
    conn = _get_vault_index_conn()
    if conn is None:
        return _vault_index_error_payload()
    if not agent_id or not agent_id.strip():
        return {"error": "agent_id is required (contract C2 — per-agent isolation)"}
    try:
        hits = vault_index.search(
            conn, agent_id.strip(), query,
            kinds=kinds, date_from=date_from, date_to=date_to,
            limit=limit, include_private=include_private,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        sys.stderr.write(f"vault_search_text failed: {exc}\n")
        return {"error": f"search failed: {exc}"}
    return {
        "agent": agent_id.strip(),
        "query": query,
        "count": len(hits),
        "results": [
            {
                "id": h.id,
                "kind": h.kind,
                "rel_path": h.rel_path,
                "section_path": h.section_path,
                "date": h.date,
                "title": h.title,
                "snippet": h.snippet,
            }
            for h in hits
        ],
    }


# ---------------------------------------------------------------------------
# Tool: vault_timeline
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_timeline(
    agent_id: str,
    entry_id: int,
    before: int = 3,
    after: int = 3,
    include_private: bool = True,
) -> Dict[str, Any]:
    """Return the entries immediately before and after ``entry_id`` in
    chronological order, scoped to ``agent_id``.

    Useful for expanding context around a search hit without having to
    fetch every surrounding file. Returns the neighbors with short
    snippets — call ``vault_get_excerpt`` if you need the full body.
    """
    conn = _get_vault_index_conn()
    if conn is None:
        return _vault_index_error_payload()
    if not agent_id or not agent_id.strip():
        return {"error": "agent_id is required (contract C2)"}
    try:
        hits = vault_index.timeline(
            conn, agent_id.strip(), int(entry_id),
            before=int(before), after=int(after),
            include_private=include_private,
        )
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        sys.stderr.write(f"vault_timeline failed: {exc}\n")
        return {"error": f"timeline failed: {exc}"}
    return {
        "agent": agent_id.strip(),
        "anchor_id": int(entry_id),
        "count": len(hits),
        "results": [
            {
                "id": h.id,
                "kind": h.kind,
                "rel_path": h.rel_path,
                "section_path": h.section_path,
                "date": h.date,
                "title": h.title,
                "snippet": h.snippet,
            }
            for h in hits
        ],
    }


# ---------------------------------------------------------------------------
# Tool: vault_get_excerpt
# ---------------------------------------------------------------------------


@mcp.tool()
def vault_get_excerpt(
    agent_id: str,
    entry_id: int,
    max_chars: int = 800,
) -> Dict[str, Any]:
    """Return the full (up to ``max_chars``) body of a single indexed
    entry, scoped to ``agent_id``.

    Use after ``vault_search_text`` / ``vault_timeline`` to fetch the
    body of hits that actually matter — this is the third tier of the
    progressive-disclosure pattern, mirroring claude-mem's
    ``get_observations``.
    """
    conn = _get_vault_index_conn()
    if conn is None:
        return _vault_index_error_payload()
    if not agent_id or not agent_id.strip():
        return {"error": "agent_id is required (contract C2)"}
    try:
        detail = vault_index.get_excerpt(
            conn, agent_id.strip(), int(entry_id), max_chars=int(max_chars),
        )
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        sys.stderr.write(f"vault_get_excerpt failed: {exc}\n")
        return {"error": f"get_excerpt failed: {exc}"}
    if detail is None:
        return {"error": f"no entry id={entry_id} for agent={agent_id!r}"}
    return {
        "id": detail.id,
        "agent": detail.agent,
        "kind": detail.kind,
        "rel_path": detail.rel_path,
        "section_path": detail.section_path,
        "date": detail.date,
        "title": detail.title,
        "body": detail.body,
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
