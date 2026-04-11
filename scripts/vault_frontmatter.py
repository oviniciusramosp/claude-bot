#!/usr/bin/env python3
"""
vault_frontmatter.py — single source of truth for parsing YAML frontmatter
in vault markdown files.

Pure stdlib (no pyyaml). Imported by:
  - claude-fallback-bot.py (the bot)
  - scripts/vault-graph-builder.py
  - scripts/vault_query.py
  - scripts/vault_lint.py
  - scripts/vault_indexes.py
  - mcp-server/vault_mcp_server.py (optional sidecar)

Supports:
  - Scalars (int, float, bool, string)
  - Quoted strings ("..." or '...')
  - Flow lists ([a, b, c])
  - Block lists (- a / - b / - c) at top level and one level nested
  - Nested blocks one level deep (e.g. schedule: \\n   times: ...)
  - Block scalars (| literal and > folded, with optional - chomp)
  - The vault-specific `related:` block of objects with file/type/reason

If a vault file ever needs YAML features beyond this (anchors, multi-doc,
deep nesting), the right answer is to add support here, not to add another
parser. Drift between parsers has been a recurring source of bugs.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Regex constants (shared)
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _indent_of(line: str) -> int:
    """Count leading spaces (tabs expanded to 4)."""
    n = 0
    for ch in line:
        if ch == " ":
            n += 1
        elif ch == "\t":
            n += 4
        else:
            break
    return n


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and (
        (s[0] == '"' and s[-1] == '"') or (s[0] == "'" and s[-1] == "'")
    ):
        return s[1:-1]
    return s


def _parse_yaml_value(val: str) -> Any:
    """Parse a single YAML value: bool, number, quoted string, flow list, or plain string."""
    if val.lower() in ("true", "yes"):
        return True
    if val.lower() in ("false", "no"):
        return False
    # Flow list: [a, b, c]
    if val.startswith("[") and val.endswith("]"):
        items = val[1:-1].split(",")
        return [_strip_quotes(i.strip()) for i in items if i.strip()]
    # Quoted string
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        return val[1:-1]
    # Try number
    try:
        if "." in val:
            return float(val)
        return int(val)
    except ValueError:
        pass
    return val


def _read_block_scalar(
    lines: List[str], start: int, end: int, parent_indent: int
) -> Tuple[str, int]:
    """Collect a YAML block scalar starting at `start`.

    Returns (joined_text, consumed_lines). Only lines indented strictly deeper
    than `parent_indent` are included. Strips the minimum indent from each line.
    """
    collected: List[str] = []
    j = start
    while j < end:
        line = lines[j]
        if line.strip() == "":
            collected.append("")
            j += 1
            continue
        if _indent_of(line) <= parent_indent:
            break
        collected.append(line)
        j += 1
    if not collected:
        return "", j - start
    # Find minimum indent among non-empty collected lines
    min_indent = min(_indent_of(ln) for ln in collected if ln.strip())
    dedented = [ln[min_indent:] if len(ln) >= min_indent else ln for ln in collected]
    # Strip trailing empty lines
    while dedented and dedented[-1] == "":
        dedented.pop()
    return "\n".join(dedented), j - start


def _read_block_list(
    lines: List[str], start: int, end: int, parent_indent: int
) -> Tuple[List[Any], int]:
    """Collect a block list starting at `start`.

    A block list looks like:
        - item1
        - item2
        - file: foo
          type: bar

    Returns (items, consumed_lines). Each item is either a scalar (parsed via
    _parse_yaml_value) or a dict if the dash is followed by `key: value` and
    subsequent indented `key: value` lines.
    """
    items: List[Any] = []
    j = start
    while j < end:
        line = lines[j]
        if line.strip() == "":
            j += 1
            continue
        line_indent = _indent_of(line)
        if line_indent <= parent_indent:
            break
        stripped = line.strip()
        if not stripped.startswith("- "):
            # Not a list item — stop
            break
        rest = stripped[2:].strip()
        # Inline `- key: value` starts an object item
        if ":" in rest and not rest.startswith("[") and not rest.startswith('"'):
            key, _, val = rest.partition(":")
            key = key.strip()
            val = val.strip()
            obj: Dict[str, Any] = {}
            if val:
                obj[key] = _parse_yaml_value(val)
            else:
                obj[key] = ""
            j += 1
            # Read continuation lines (indented deeper than the dash)
            dash_indent = line_indent
            while j < end:
                cont = lines[j]
                if cont.strip() == "":
                    j += 1
                    continue
                cont_indent = _indent_of(cont)
                if cont_indent <= dash_indent:
                    break
                cont_stripped = cont.strip()
                if ":" in cont_stripped and not cont_stripped.startswith("-"):
                    ck, _, cv = cont_stripped.partition(":")
                    obj[ck.strip()] = _parse_yaml_value(cv.strip())
                    j += 1
                else:
                    break
            items.append(obj)
        else:
            items.append(_parse_yaml_value(rest))
            j += 1
    return items, j - start


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> Dict[str, Any]:
    """Parse YAML frontmatter from a markdown file.

    Supports scalars, quoted strings, flow lists, block lists (one level deep),
    nested blocks (one level), and block scalars (`|` literal and `>` folded).
    """
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return {}
    end = -1
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end < 0:
        return {}

    result: Dict[str, Any] = {}
    current_block: Optional[str] = None
    i = 1
    while i < end:
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # Indented sub-key of an open nested block
        if (
            current_block
            and line.startswith("  ")
            and ":" in stripped
            and not stripped.startswith("-")
        ):
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val in ("|", "|-", ">", ">-"):
                scalar, consumed = _read_block_scalar(
                    lines, i + 1, end, _indent_of(line)
                )
                if isinstance(result.get(current_block), dict):
                    result[current_block][key] = (
                        scalar
                        if val.startswith("|")
                        else scalar.replace("\n", " ").strip()
                    )
                i += 1 + consumed
                continue
            if isinstance(result.get(current_block), dict):
                result[current_block][key] = _parse_yaml_value(val)
            i += 1
            continue

        # Top-level key
        if ":" in stripped and not stripped.startswith("-"):
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                # Could be a nested block (next line is `  key: value`)
                # or a block list (next line is `  - item`)
                # Look ahead to decide
                lookahead = i + 1
                while lookahead < end and lines[lookahead].strip() == "":
                    lookahead += 1
                if lookahead < end:
                    nxt = lines[lookahead]
                    nxt_stripped = nxt.strip()
                    if nxt_stripped.startswith("- "):
                        items, consumed = _read_block_list(
                            lines, i + 1, end, _indent_of(line)
                        )
                        result[key] = items
                        i += 1 + consumed
                        current_block = None
                        continue
                # Default to nested dict block
                result[key] = {}
                current_block = key
            elif val in ("|", "|-", ">", ">-"):
                scalar, consumed = _read_block_scalar(
                    lines, i + 1, end, _indent_of(line)
                )
                result[key] = (
                    scalar if val.startswith("|") else scalar.replace("\n", " ").strip()
                )
                i += 1 + consumed
                current_block = None
                continue
            else:
                result[key] = _parse_yaml_value(val)
                current_block = None
        i += 1
    return result


def get_frontmatter_and_body(filepath: Path) -> Tuple[Dict[str, Any], str]:
    """Return (frontmatter_dict, body_text) from a markdown file.

    Returns ({}, "") if the file cannot be read.
    """
    try:
        text = filepath.read_text(encoding="utf-8")
    except Exception:
        return {}, ""
    fm = parse_frontmatter(text)
    lines = text.split("\n")
    if lines and lines[0].strip() == "---":
        end = -1
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                end = i
                break
        if end >= 0:
            body = "\n".join(lines[end + 1 :]).strip()
            return fm, body
    return fm, text.strip()


_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def extract_wikilinks(text: str) -> List[str]:
    """Extract wikilink targets from markdown body, skipping frontmatter,
    fenced code blocks (```...```), and inline code spans (`...`). Wikilinks
    inside code are documentation examples, not real graph relationships.
    """
    m = FRONTMATTER_RE.match(text)
    body = text[m.end() :] if m else text

    in_fence = False
    cleaned = []
    for line in body.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        # Strip inline code spans before extracting wikilinks
        cleaned.append(_INLINE_CODE_RE.sub("", line))
    return WIKILINK_RE.findall("\n".join(cleaned))


def normalize_id(filepath: Path, vault_dir: Path) -> str:
    """Create a stable node ID from file path. Mirrors vault-graph-builder."""
    rel = filepath.relative_to(vault_dir)
    return (
        str(rel).replace("/", "_").replace(".md", "").replace(" ", "-").lower()
    )


# ---------------------------------------------------------------------------
# Serializer
# ---------------------------------------------------------------------------


def _serialize_value(val: Any) -> str:
    """Serialize a single YAML value to string form."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, list):
        items = [_serialize_value(v) for v in val]
        return "[" + ", ".join(items) + "]"
    if val is None:
        return ""
    s = str(val)
    # Quote strings containing special chars
    if any(ch in s for ch in (":", "#", "\n")) or s.strip() != s:
        return '"' + s.replace('"', '\\"') + '"'
    return s


def serialize_frontmatter(
    fm: Dict[str, Any], ordered_keys: Optional[List[str]] = None
) -> str:
    """Serialize a frontmatter dict back to a YAML block (without --- delimiters).

    Preserves key order if `ordered_keys` is provided. Nested dicts become
    indented blocks. Multi-line strings become block scalars (`|`).
    """
    keys = ordered_keys if ordered_keys else list(fm.keys())
    # Append any keys present in fm but not in ordered_keys (preserve them)
    for k in fm.keys():
        if k not in keys:
            keys.append(k)

    out: List[str] = []
    for k in keys:
        if k not in fm:
            continue
        v = fm[k]
        if isinstance(v, dict):
            out.append(f"{k}:")
            for sk, sv in v.items():
                if isinstance(sv, str) and "\n" in sv:
                    out.append(f"  {sk}: |")
                    for ln in sv.split("\n"):
                        out.append(f"    {ln}")
                else:
                    out.append(f"  {sk}: {_serialize_value(sv)}")
        elif isinstance(v, list) and v and isinstance(v[0], dict):
            # Block list of objects
            out.append(f"{k}:")
            for item in v:
                first = True
                for ik, iv in item.items():
                    prefix = "  - " if first else "    "
                    out.append(f"{prefix}{ik}: {_serialize_value(iv)}")
                    first = False
        elif isinstance(v, str) and "\n" in v:
            out.append(f"{k}: |")
            for ln in v.split("\n"):
                out.append(f"  {ln}")
        else:
            out.append(f"{k}: {_serialize_value(v)}")
    return "\n".join(out)


def parse_pipeline_body(body: str) -> List[Dict[str, Any]]:
    """Extract step definitions from a ```pipeline fenced block in markdown.

    Returns a list of dicts, each with keys like id, name, model, depends_on,
    prompt_file, timeout, retry, output. Used by the bot, the linter, and the
    indexer — single source of truth.
    """
    in_block = False
    block_lines: List[str] = []
    for line in body.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```pipeline"):
            in_block = True
            continue
        if in_block and stripped == "```":
            break
        if in_block:
            block_lines.append(line)

    if not block_lines:
        return []

    steps: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    for line in block_lines:
        stripped = line.strip()
        if not stripped or stripped == "steps:":
            continue
        if stripped.startswith("- "):
            if current is not None:
                steps.append(current)
            current = {}
            stripped = stripped[2:].strip()
        if current is None:
            continue
        if ":" in stripped:
            colon = stripped.index(":")
            key = stripped[:colon].strip()
            val = stripped[colon + 1 :].strip()
            if val:
                current[key] = _parse_yaml_value(val)
    if current:
        steps.append(current)
    return steps


def write_frontmatter_file(
    filepath: Path, fm: Dict[str, Any], body: str, ordered_keys: Optional[List[str]] = None
) -> None:
    """Write a markdown file with frontmatter + body. Atomic-ish (write then rename)."""
    yaml_block = serialize_frontmatter(fm, ordered_keys)
    text = f"---\n{yaml_block}\n---\n\n{body.strip()}\n"
    tmp = filepath.with_suffix(filepath.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(filepath)
