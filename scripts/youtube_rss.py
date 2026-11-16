#!/usr/bin/env python3
"""YouTube channel feed reader — RSS first, Safari fallback.

Reads the public Atom feed at
    https://www.youtube.com/feeds/videos.xml?channel_id=<ID>
which is unauthenticated, quota-free, and contains the 15 most recent
uploads (regular videos + livestreams alike). No API key required.

CLI:
    python3 scripts/youtube_rss.py fetch --channel-id UC... [--fallback-browser]

(`--fallback-pinchtab` is still accepted as a deprecated alias of
`--fallback-browser`.)

Stdout: one JSON object per line (JSONL), each:
    {
      "video_id":       "abc123XYZ_0",
      "title":          "...",
      "published_at":   "2026-05-26T18:30:00+00:00",
      "link":           "https://www.youtube.com/watch?v=abc123XYZ_0",
      "thumbnail_url":  "https://i.ytimg.com/vi/abc123XYZ_0/hqdefault.jpg",
      "description":    "...",
      "is_live_hint":   false
    }

`is_live_hint` is a best-effort flag derived from title heuristics
(case+accent insensitive). Downstream callers should apply their own
filter rules — this script's job is purely to surface the feed.

Exit codes:
    0  success (one or more entries on stdout, or empty feed)
    2  RSS unavailable AND fallback disabled / failed
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # scripts/ → safari.py
import safari  # noqa: E402

RSS_URL_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
USER_AGENT = "Mozilla/5.0 (compatible; youtube-rss/1.0)"
HTTP_TIMEOUT = 20

ATOM_NS = "http://www.w3.org/2005/Atom"
YT_NS = "http://www.youtube.com/xml/schemas/2015"
MEDIA_NS = "http://search.yahoo.com/mrss/"

# Heuristic — title fragments that suggest the entry is (was) a livestream.
# This is best-effort; YouTube's public RSS does NOT expose a definitive
# live flag, so the harness downstream applies the real filter.
_LIVE_HINTS = (
    "ao vivo",
    "live",
    "transmissao ao vivo",
    "transmissao",
    "ssaovivo",
)


def _strip_accents(text: str) -> str:
    return (
        unicodedata.normalize("NFD", text or "")
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def _is_live_hint(title: str) -> bool:
    norm = _strip_accents(title)
    return any(h in norm for h in _LIVE_HINTS)


def parse_rss_xml(xml_bytes: bytes) -> List[Dict[str, Any]]:
    """Parse a YouTube channel Atom feed. Returns the list of entries.

    Raises ET.ParseError on malformed XML.
    """
    root = ET.fromstring(xml_bytes)
    entries: List[Dict[str, Any]] = []
    for entry in root.findall(f"{{{ATOM_NS}}}entry"):
        video_id_el = entry.find(f"{{{YT_NS}}}videoId")
        title_el = entry.find(f"{{{ATOM_NS}}}title")
        published_el = entry.find(f"{{{ATOM_NS}}}published")
        link_el = entry.find(f"{{{ATOM_NS}}}link")

        video_id = (video_id_el.text or "").strip() if video_id_el is not None else ""
        if not video_id:
            continue
        title = (title_el.text or "").strip() if title_el is not None else ""
        published = (published_el.text or "").strip() if published_el is not None else ""
        link = ""
        if link_el is not None:
            link = link_el.attrib.get("href", "")
        if not link:
            link = f"https://www.youtube.com/watch?v={video_id}"

        # media:group/media:description and media:thumbnail
        description = ""
        thumbnail_url = ""
        media_group = entry.find(f"{{{MEDIA_NS}}}group")
        if media_group is not None:
            desc_el = media_group.find(f"{{{MEDIA_NS}}}description")
            if desc_el is not None and desc_el.text:
                description = desc_el.text.strip()
            thumb_el = media_group.find(f"{{{MEDIA_NS}}}thumbnail")
            if thumb_el is not None:
                thumbnail_url = thumb_el.attrib.get("url", "")
        if not thumbnail_url:
            thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"

        entries.append(
            {
                "video_id": video_id,
                "title": title,
                "published_at": published,
                "link": link,
                "thumbnail_url": thumbnail_url,
                "description": description,
                "is_live_hint": _is_live_hint(title),
            }
        )
    return entries


def fetch_rss(channel_id: str) -> Optional[bytes]:
    """Fetch the RSS Atom feed. Returns the raw bytes on HTTP 200 with XML
    content, None on any non-200 status, network error, or non-XML body.
    """
    url = RSS_URL_TEMPLATE.format(channel_id=channel_id)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 200:
                return None
            body = resp.read()
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "xml" not in ctype and not body.lstrip().startswith(b"<"):
                return None
            return body
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def fallback_browser(channel_url: str) -> List[Dict[str, Any]]:
    """Scrape /videos via Safari (scripts/safari.py) — best-effort fallback.

    Opens the channel page in its own Safari window (one attempt), reads the
    rendered HTML (video IDs are embedded in ytInitialData), and closes it.
    If Safari can't be driven, the error is reported on stderr and we fall
    back to a raw HTTP GET of the channel page as a last-ditch path.
    """
    html = ""
    try:
        with safari.open_page(channel_url, settle=3) as page:
            html = page.html()
    except safari.SafariError as exc:
        print(f"WARN: Safari fallback failed for {channel_url}: {exc}", file=sys.stderr)

    if not html:
        # Raw HTTP GET — works only if YouTube serves SSR content (logged-out
        # path varies). Best-effort only.
        try:
            req = urllib.request.Request(channel_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
        except Exception:
            return []

    # Extract unique video IDs in order of first appearance.
    seen: Dict[str, None] = {}
    for m in re.finditer(r'"videoId":"([A-Za-z0-9_-]{11})"', html):
        vid = m.group(1)
        if vid not in seen:
            seen[vid] = None

    entries: List[Dict[str, Any]] = []
    for vid in seen.keys():
        # Pair each video ID with the closest title hint (`"title":{"runs":[{"text":"..."}]`).
        # The pairing is approximate — RSS is the source of truth; this is a
        # safety net.
        entries.append(
            {
                "video_id": vid,
                "title": "",  # title unknown via this fallback path
                "published_at": "",
                "link": f"https://www.youtube.com/watch?v={vid}",
                "thumbnail_url": f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
                "description": "",
                "is_live_hint": False,
            }
        )
    return entries


def cmd_fetch(args: argparse.Namespace) -> int:
    channel_id = args.channel_id.strip()
    if not channel_id:
        print("ERROR: --channel-id is required", file=sys.stderr)
        return 2

    rss_bytes = fetch_rss(channel_id)
    entries: List[Dict[str, Any]] = []
    used_fallback = False
    if rss_bytes:
        try:
            entries = parse_rss_xml(rss_bytes)
        except ET.ParseError as exc:
            print(f"ERROR: RSS parse failed: {exc}", file=sys.stderr)
            rss_bytes = None

    if not rss_bytes:
        if not args.fallback_browser:
            print(
                f"ERROR: RSS unavailable for channel {channel_id} and --fallback-browser not set",
                file=sys.stderr,
            )
            return 2
        used_fallback = True
        channel_url = f"https://www.youtube.com/channel/{channel_id}/videos"
        entries = fallback_browser(channel_url)

    if used_fallback:
        print(
            f"WARN: RSS fallback path used (channel {channel_id}); titles/timestamps may be missing",
            file=sys.stderr,
        )

    for entry in entries:
        print(json.dumps(entry, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Read a YouTube channel feed (RSS + Safari fallback)."
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    p_fetch = sub.add_parser("fetch", help="Print channel uploads as JSONL")
    p_fetch.add_argument("--channel-id", required=True)
    p_fetch.add_argument(
        "--fallback-browser",
        action="store_true",
        help="If RSS fails, scrape the /videos page via Safari (scripts/safari.py).",
    )
    # Deprecated alias kept so existing callers don't break.
    p_fetch.add_argument(
        "--fallback-pinchtab",
        dest="fallback_browser",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    p_fetch.set_defaults(func=cmd_fetch)
    return p


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
