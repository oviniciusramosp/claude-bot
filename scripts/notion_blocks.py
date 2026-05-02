#!/usr/bin/env python3
"""
notion_blocks.py — Convert vault markup to Notion API block objects.

Usage:
    python3 notion_blocks.py <content_file>
    python3 notion_blocks.py -  (reads from stdin)

Output: JSON array of Notion block objects, written to stdout.

Markup handled:
    [heading_1] text     → heading_1 block
    [heading_2] text     → heading_2 block
    [heading_3] text     → heading_3 block
    [paragraph] text     → paragraph block (also default for unmarked lines)
    [divider]            → divider block
    [quote] text         → quote block
    **text**             → bold annotation
    _text_               → italic annotation
    [verde]text[/verde]  → green color annotation
    [vermelho]text[/vermelho] → red color annotation
    {{chart:...}}        → paragraph block with plain text (chart embed syntax)
"""

import re
import sys
import json


def _strip_inline(text, base_annotations=None):
    """Parse **bold** and _italic_ within a text fragment.

    base_annotations: dict merged into every segment (e.g. {"color": "green"}).
    Returns a list of Notion rich_text segment dicts.
    """
    base = base_annotations or {}
    segments = []
    pattern = re.compile(r'\*\*(.*?)\*\*|_(.*?)_|([^*_]+)', re.DOTALL)
    for m in pattern.finditer(text):
        if m.group(1) is not None:  # **bold**
            ann = {**base, "bold": True}
            segments.append(_rich_text_segment(m.group(1), ann))
        elif m.group(2) is not None:  # _italic_
            ann = {**base, "italic": True}
            segments.append(_rich_text_segment(m.group(2), ann))
        elif m.group(3):  # plain
            seg = _rich_text_segment(m.group(3), base if base else None)
            segments.append(seg)
    return segments


def _rich_text_segment(text, annotations=None):
    seg = {"type": "text", "text": {"content": text}}
    if annotations:
        full_ann = {
            "bold": False, "italic": False, "strikethrough": False,
            "underline": False, "code": False, "color": "default",
        }
        full_ann.update(annotations)
        seg["annotations"] = full_ann
    return seg


def parse_rich_text(text):
    """Convert a markup string into a Notion rich_text array.

    Handles [verde]/[vermelho] color blocks and **bold**/_italic_ inside them.
    Never returns an empty list — falls back to plain text segment.
    """
    segments = []
    pattern = re.compile(
        r'\[verde\](.*?)\[/verde\]'
        r'|\[vermelho\](.*?)\[/vermelho\]'
        r'|([^\[]+|\[(?!verde\]|vermelho\]|/verde\]|/vermelho\])[^\]]*\]?)',
        re.DOTALL
    )
    for m in pattern.finditer(text):
        if m.group(1) is not None:
            segments.extend(_strip_inline(m.group(1), {"color": "green"}))
        elif m.group(2) is not None:
            segments.extend(_strip_inline(m.group(2), {"color": "red"}))
        elif m.group(3):
            segments.extend(_strip_inline(m.group(3)))

    return segments if segments else [{"type": "text", "text": {"content": text}}]


BLOCK_MARKERS = [
    ("[heading_1]", "heading_1"),
    ("[heading_2]", "heading_2"),
    ("[heading_3]", "heading_3"),
    ("[paragraph]", "paragraph"),
    ("[quote]",     "quote"),
]


def content_to_blocks(content):
    """Convert a full content string to a list of Notion block dicts."""
    blocks = []
    for line in content.strip().splitlines():
        line = line.strip()
        if not line:
            continue

        # Skip Obsidian wikilinks (parent index links injected by the vault harness)
        if line.startswith("[[") and line.endswith("]]"):
            continue

        if line == "[divider]":
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            continue

        block_type = "paragraph"
        text = line
        for marker, btype in BLOCK_MARKERS:
            if line.startswith(marker):
                block_type = btype
                text = line[len(marker):].strip()
                break

        rich_text = parse_rich_text(text)
        blocks.append({
            "object": "block",
            "type": block_type,
            block_type: {"rich_text": rich_text},
        })

    return blocks


def main():
    if len(sys.argv) < 2:
        print("Usage: notion_blocks.py <file_path | ->", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    if path == "-":
        content = sys.stdin.read()
    else:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

    blocks = content_to_blocks(content)
    print(json.dumps(blocks, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
