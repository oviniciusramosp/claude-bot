#!/usr/bin/env python3
"""Palmeiras Feed v2 — Step: scout (mechanical fetch + cluster)

Pipeline: palmeiras-feed-v2.md
Step-id: scout

Job: fetch all configured sources, dedup by URL against feed-state, cluster
items about the same story across outlets, emit ALL candidates. NO editorial
filtering — the downstream `curate` LLM step decides which (if any) to publish.

Reads:
  - feed-state.json (URL dedup: already-posted URLs)
  - 6 RSS/API sources (palmeiras-api, nossop-rss, gazeta, uol, verdazzo, globoesporte)
  - Notion DB query (authoritative: last 30-day titles, ground truth for dedup)
  - published-index.jsonl (unified cross-pipeline history; fallback/supplement)
  - posts-history.md + pos-jogo-history.md (legacy backup, read iff present)
  - $PIPELINE_STEP_OUTPUT_FILE — destination path for candidates.json
  - $STEP_OVERRIDE_MAX_AGE_HOURS (default 24)
  - $STEP_OVERRIDE_SOURCES (default all)

Writes JSON: { candidates: [...], history_titles: [...], stats: {...} }.
Status report on last stdout line: JSON {status, output_file, reason}.
"""

from __future__ import annotations

import html as html_mod
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ----------------------------------------------------------------------------
# Configuration (env-driven; defaults from accepts_overrides schema)
# ----------------------------------------------------------------------------

VAULT_ROOT = Path("/Users/viniciusramos/claude-bot/vault/parmeirense")
VAULT_ENV_PATH = Path("/Users/viniciusramos/claude-bot/vault/.env")
FEED_STATE_PATH = VAULT_ROOT / "feed-state.json"
POSTS_HISTORY_PATH = VAULT_ROOT / "posts-history.md"
POS_JOGO_HISTORY_PATH = VAULT_ROOT / "pos-jogo-history.md"

NOTION_VERSION = "2022-06-28"
NOTION_HISTORY_DAYS = 30

USER_AGENT = "Mozilla/5.0 (compatible; palmeiras-feed/2.0)"
HTTP_TIMEOUT = 20

ALL_SOURCES = ("palmeiras-api", "nossop-rss", "gazeta", "uol", "verdazzo", "globoesporte")

# Editorial filtering (REJECT_PATTERNS / HIGH_PRIORITY_PATTERNS / TRUSTED_SINGLE_SOURCES /
# corroboration rules / semantic dedup against posts-history) was removed from this
# script. The downstream `curate` step (LLM, haiku) reads candidates.json and applies
# editorial judgment. This script's job is now purely mechanical: fetch, URL-dedup
# against feed-state, cluster the same story across outlets, emit ALL candidates.

# Spam / sportsbook hygiene for verdazzo + similar
HYGIENE_REJECT_PATTERNS = [
    r"flamingo_contact", r"post_type=flamingo_contact",
    r"\baposta", r"\bbet\b", r"\bcassino\b", r"\bodds\b", r"\bpalpite\b",
]

# ----------------------------------------------------------------------------
# Status report helpers (Pipeline v2 contract)
# ----------------------------------------------------------------------------

def emit_status(status: str, output_file: Optional[str], reason: str = "") -> None:
    """Print the JSON status report on stdout's last line and exit appropriately."""
    print(json.dumps({"status": status, "output_file": output_file, "reason": reason}))
    sys.exit(0 if status == "ready" else (0 if status == "skipped" else 1))


def fail(reason: str) -> None:
    print(f"ERROR: {reason}", file=sys.stderr)
    emit_status("failed", None, reason)


# ----------------------------------------------------------------------------
# HTTP helpers
# ----------------------------------------------------------------------------

def http_get(url: str, timeout: int = HTTP_TIMEOUT) -> bytes:
    """Fetch URL with our User-Agent. Raises on error."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def safe_decode(raw: bytes) -> str:
    """Try utf-8, fallback to latin1."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin1", errors="ignore")


# ----------------------------------------------------------------------------
# Source fetchers — each returns a list of candidate dicts; never raises
# ----------------------------------------------------------------------------

def fetch_palmeiras_api(cutoff: float, posted_urls: Set[str]) -> List[Dict[str, Any]]:
    """Official palmeiras.com.br apiverdao."""
    url = "https://www.palmeiras.com.br/wp-json/apiverdao/v1/buscar-noticias"
    try:
        data = json.loads(safe_decode(http_get(url)))
    except Exception as exc:
        print(f"WARN: palmeiras-api failed: {exc}", file=sys.stderr)
        return []
    items: List[Dict[str, Any]] = []
    for it in data if isinstance(data, list) else data.get("data", []):
        if not isinstance(it, dict):
            continue
        link = str(it.get("link", "")).strip()
        if not link or link in posted_urls:
            continue
        try:
            ts = float(it.get("dataOrder", 0))
        except (TypeError, ValueError):
            ts = 0.0
        if ts < cutoff:
            continue
        items.append({
            "source": "palmeiras-api",
            "tier": 1,
            "title": str(it.get("titulo", "")).strip(),
            "url": link,
            "image_url": str(it.get("img", "")).strip() or None,
            "published_ts": ts,
            "excerpt": "",
            "date_confirmed": True,
        })
    return items


def _parse_rss(raw_xml: str) -> List[Dict[str, Any]]:
    """Parse a generic RSS 2.0 feed into a list of {title, link, pubDate, description}."""
    out: List[Dict[str, Any]] = []
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError:
        return out
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = (it.findtext("link") or "").strip()
        pubdate = (it.findtext("pubDate") or "").strip()
        desc = (it.findtext("description") or "").strip()
        out.append({"title": title, "link": link, "pubDate": pubdate, "description": desc})
    return out


def _rfc822_to_ts(rfc: str) -> float:
    """Parse RSS pubDate (RFC822-ish) to Unix timestamp. Returns 0.0 on failure."""
    if not rfc:
        return 0.0
    formats = ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
               "%a, %d %b %Y %H:%M %z", "%a, %d %b %Y %H:%M:%S")
    for fmt in formats:
        try:
            import datetime
            dt = datetime.datetime.strptime(rfc, fmt)
            if dt.tzinfo is None:
                # Assume UTC if no tz
                return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
            return dt.timestamp()
        except Exception:
            continue
    return 0.0


def _strip_html(text: str) -> str:
    """Strip HTML tags + decode entities. For excerpts only."""
    text = re.sub(r"<[^>]+>", "", text)
    text = html_mod.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_rss(source_name: str, url: str, tier: int,
              cutoff: float, posted_urls: Set[str],
              hygiene_filter: bool = False,
              palmeiras_keyword_required: bool = False,
              latin1_decode: bool = False) -> List[Dict[str, Any]]:
    """Generic RSS fetcher used by nossop, gazeta, uol, verdazzo."""
    try:
        raw = http_get(url)
        text = safe_decode(raw) if not latin1_decode else raw.decode("latin1", errors="ignore")
        try:
            text.encode("utf-8")  # sanity
        except Exception:
            text = raw.decode("utf-8", errors="ignore")
        items_raw = _parse_rss(text)
    except Exception as exc:
        print(f"WARN: {source_name} failed: {exc}", file=sys.stderr)
        return []
    items: List[Dict[str, Any]] = []
    for it in items_raw:
        title = it["title"]
        link = it["link"]
        if not title or not link or link in posted_urls:
            continue
        if hygiene_filter:
            blob = (link + " " + title).lower()
            if any(re.search(p, blob, re.IGNORECASE) for p in HYGIENE_REJECT_PATTERNS):
                continue
            if "@" in title:  # email-looking title (Verdazzo bug)
                continue
        if palmeiras_keyword_required:
            blob = (title + " " + it["description"] + " " + link).lower()
            if "palmeiras" not in blob:
                continue
        ts = _rfc822_to_ts(it["pubDate"])
        if ts < cutoff:
            continue
        items.append({
            "source": source_name,
            "tier": tier,
            "title": title,
            "url": link,
            "image_url": None,
            "published_ts": ts,
            "excerpt": _strip_html(it["description"])[:300],
            "date_confirmed": True,
        })
    return items


def fetch_ge_globo(cutoff: float, posted_urls: Set[str]) -> List[Dict[str, Any]]:
    """GloboEsporte (ge.globo.com) — Palmeiras listing page scraper.
    GE has no RSS feed; dates are embedded in article URL paths (/noticia/YYYY/MM/DD/).
    Fetches the Palmeiras listing page and extracts title+URL pairs from embedded JSON.
    """
    listing_url = "https://ge.globo.com/futebol/times/palmeiras/"
    try:
        raw = http_get(listing_url)
        text = safe_decode(raw)
    except Exception as exc:
        print(f"WARN: globoesporte failed: {exc}", file=sys.stderr)
        return []

    import datetime
    # Extract "title":"...", "url":"...noticia/YYYY/MM/DD/..." pairs from page JSON.
    # GE lists articles newest-first, so match position = recency within the same day.
    # We use position as a sub-second offset (position 0 = +59s, position N = less)
    # so that intra-day ordering is preserved without extra HTTP requests.
    pattern = r'"title":"([^"]{10,200})","url":"(https://ge\.globo\.com/[^"]*noticia/(\d{4})/(\d{2})/(\d{2})/[^"]+\.ghtml)"'
    matches = re.findall(pattern, text)

    items: List[Dict[str, Any]] = []
    seen_urls: Set[str] = set()
    position = 0
    for title, url, year, month, day in matches:
        if url in seen_urls or url in posted_urls:
            continue
        seen_urls.add(url)
        # Filter: must mention Palmeiras in URL path or title
        if "palmeiras" not in url.lower() and "palmeiras" not in title.lower():
            continue
        # Skip hygiene patterns (apostas, palpites, etc.)
        blob = (url + " " + title).lower()
        if any(re.search(p, blob, re.IGNORECASE) for p in HYGIENE_REJECT_PATTERNS):
            continue
        try:
            dt = datetime.datetime(int(year), int(month), int(day), 12, 0,
                                   tzinfo=datetime.timezone.utc)
            # Subtract position in seconds: position 0 → latest, position N → older
            ts = dt.timestamp() - position
        except ValueError:
            continue
        if ts < cutoff:
            continue
        title_clean = html_mod.unescape(title).strip()
        items.append({
            "source": "globoesporte",
            "tier": 1,
            "title": title_clean,
            "url": url,
            "image_url": None,
            "published_ts": ts,
            "excerpt": "",
            "date_confirmed": True,
        })
        position += 1
    return items


# ----------------------------------------------------------------------------
# Topic grouping + dedup
# ----------------------------------------------------------------------------

STOPWORDS_PT = frozenset({
    "a", "ao", "aos", "as", "com", "da", "das", "de", "do", "dos", "e",
    "em", "na", "nas", "no", "nos", "o", "os", "para", "por", "que",
    "se", "um", "uma", "uns", "umas", "the", "of", "to", "in", "and",
})


def normalize_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def title_tokens(t: str) -> Set[str]:
    return {w for w in normalize_title(t).split() if len(w) >= 3 and w not in STOPWORDS_PT}


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def group_into_topics(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cluster items about the same story. Same URL → same topic; otherwise
    fuzzy title match (Jaccard ≥ 0.45 OR ≥ 3 shared significant tokens)."""
    topics: List[Dict[str, Any]] = []
    for it in items:
        token_set = title_tokens(it["title"])
        # Try to merge into an existing topic
        merged = False
        for tp in topics:
            if it["url"] in tp["urls"]:
                tp["fontes"].append(it)
                merged = True
                break
            if jaccard(token_set, tp["tokens"]) >= 0.45 or len(token_set & tp["tokens"]) >= 3:
                tp["fontes"].append(it)
                tp["urls"].add(it["url"])
                tp["tokens"] |= token_set
                merged = True
                break
        if not merged:
            topics.append({
                "urls": {it["url"]},
                "tokens": set(token_set),
                "fontes": [it],
            })
    # Project to a stable schema
    out: List[Dict[str, Any]] = []
    for tp in topics:
        primary = max(tp["fontes"], key=lambda f: (f["tier"] == 1, f.get("published_ts", 0)))
        out.append({
            "primary_title": primary["title"],
            "primary_url": primary["url"],
            "primary_image": primary.get("image_url"),
            "primary_ts": primary.get("published_ts", 0),
            "fontes": tp["fontes"],
            "tokens": tp["tokens"],
            "titulos_originais": [
                {"fonte": f["source"], "titulo": f["title"]} for f in tp["fontes"]
            ],
        })
    return out


# ----------------------------------------------------------------------------
# Notion env loader
# ----------------------------------------------------------------------------

def load_env() -> Dict[str, str]:
    """Read NOTION_API_KEY + NOTION_PALMEIRAS_DB_ID from vault/.env."""
    if not VAULT_ENV_PATH.is_file():
        return {}
    out: Dict[str, str] = {}
    for line in VAULT_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def fetch_notion_history_titles() -> List[str]:
    """Query Notion DB for posts published in the last NOTION_HISTORY_DAYS days.

    Returns a list of title strings to be merged into history_titles.
    Falls back silently if credentials are missing or the request fails — the
    local posts-history.md still provides coverage.
    """
    env = load_env()
    notion_token = env.get("NOTION_API_KEY", "")
    db_id = env.get("NOTION_PALMEIRAS_DB_ID", "")
    if not notion_token or not db_id:
        print("WARN: Notion credentials not found in vault/.env — skipping Notion history fetch",
              file=sys.stderr)
        return []

    cutoff_date = time.strftime(
        "%Y-%m-%d",
        time.localtime(time.time() - NOTION_HISTORY_DAYS * 86400),
    )
    payload = {
        "filter": {
            "property": "Date",
            "date": {"on_or_after": cutoff_date},
        },
        "sorts": [{"property": "Date", "direction": "descending"}],
        "page_size": 100,
    }
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

    titles: List[str] = []
    has_more = True
    next_cursor: Optional[str] = None

    while has_more:
        if next_cursor:
            payload["start_cursor"] = next_cursor

        try:
            req = urllib.request.Request(
                f"https://api.notion.com/v1/databases/{db_id}/query",
                data=json.dumps(payload).encode(),
                headers=headers,
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
        except Exception as exc:
            print(f"WARN: Notion history fetch failed: {exc}", file=sys.stderr)
            break

        for page in data.get("results", []):
            title_prop = page.get("properties", {}).get("Title", {})
            rich = title_prop.get("title", [])
            text = "".join(r.get("plain_text", "") for r in rich).strip()
            if text:
                titles.append(text)

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    print(f"INFO: Notion history: {len(titles)} published titles fetched (last {NOTION_HISTORY_DAYS}d)",
          file=sys.stderr)
    return titles


# ----------------------------------------------------------------------------
# Semantic dedup against posts-history.md
# ----------------------------------------------------------------------------

def load_history_titles() -> List[str]:
    """Recent published titles across BOTH feed and pos-jogo pipelines.

    Primary source: vault/parmeirense/.workspace/published-index.jsonl
    (unified store written by every parmeirense publish step). Falls back
    to the legacy markdown files (posts-history.md, pos-jogo-history.md)
    if the JSONL store is missing/empty — keeps the migration safe.

    Cross-pipeline awareness: feed must see pos-jogo titles too, otherwise
    post-match stories get re-published as standings/news framing.
    """
    titles: List[str] = []

    # Primary: unified published-index.jsonl
    try:
        import datetime as _dt
        # Add the repo's scripts/ dir to sys.path so we can import the helper.
        scripts_dir = Path("/Users/viniciusramos/claude-bot/scripts")
        if str(scripts_dir) not in sys.path:
            sys.path.insert(0, str(scripts_dir))
        from published_index import PublishedIndex  # type: ignore

        idx = PublishedIndex(agent_id="parmeirense")
        brt = _dt.timezone(_dt.timedelta(hours=-3))
        since = (_dt.datetime.now(brt) - _dt.timedelta(days=30)).isoformat(timespec="seconds")
        for row in idx.query(since=since):
            t = row.get("title")
            if t:
                titles.append(t)
    except Exception as exc:
        print(f"WARN: published-index read failed (using legacy markdown): {exc}",
              file=sys.stderr)

    # Fallback / supplement: legacy markdown files. Cheap to read and keeps
    # the 30-day window honest while the JSONL store fills up.
    for path in (POSTS_HISTORY_PATH, POS_JOGO_HISTORY_PATH):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        # Format: "- **Titulo** — intro..." or "- **Titulo** [match info]"
        titles.extend(re.findall(r"^-\s*\*\*([^*]+)\*\*", text, re.MULTILINE))

    # Dedup while preserving first-seen order.
    seen: Set[str] = set()
    out: List[str] = []
    for t in titles:
        norm = t.lower().strip()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(t)
    return out


def is_recent_duplicate(topic_tokens: Set[str], history_titles: List[str],
                        threshold: float = 0.60) -> bool:
    """Reject if the topic's title is too similar to a recently-posted one."""
    for ht in history_titles:
        if jaccard(topic_tokens, title_tokens(ht)) >= threshold:
            return True
    return False


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

def main() -> int:
    output_path_str = os.environ.get("PIPELINE_STEP_OUTPUT_FILE", "")
    if not output_path_str:
        fail("PIPELINE_STEP_OUTPUT_FILE env var not set")
    output_path = Path(output_path_str)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Override knobs
    try:
        max_age_hours = int(os.environ.get("STEP_OVERRIDE_MAX_AGE_HOURS", "24"))
    except ValueError:
        max_age_hours = 24
    max_age_hours = max(1, min(72, max_age_hours))  # clamp 1-72

    sources_override_raw = os.environ.get("STEP_OVERRIDE_SOURCES", "")
    if sources_override_raw.strip():
        try:
            sources_subset = set(json.loads(sources_override_raw))
        except json.JSONDecodeError:
            sources_subset = set(ALL_SOURCES)
    else:
        sources_subset = set(ALL_SOURCES)

    cutoff = time.time() - max_age_hours * 3600

    # 1. Load dedup state
    posted_urls: Set[str] = set()
    if FEED_STATE_PATH.is_file():
        try:
            state = json.loads(FEED_STATE_PATH.read_text(encoding="utf-8"))
            posted_urls = {p.get("url_fonte", "") for p in state.get("posts_criados", [])
                           if p.get("url_fonte")}
        except (OSError, json.JSONDecodeError) as exc:
            print(f"WARN: feed-state.json read failed: {exc}", file=sys.stderr)

    print(f"INFO: cutoff={time.strftime('%Y-%m-%d %H:%M', time.localtime(cutoff))} "
          f"posted_urls_count={len(posted_urls)} sources={sorted(sources_subset)}")

    # 2. Fetch all sources
    all_items: List[Dict[str, Any]] = []
    stats: Dict[str, int] = {}
    if "palmeiras-api" in sources_subset:
        items = fetch_palmeiras_api(cutoff, posted_urls)
        all_items.extend(items); stats["palmeiras-api"] = len(items)
    if "nossop-rss" in sources_subset:
        items = fetch_rss("nossop-rss", "https://nossopalestra.com.br/feed/", 1, cutoff, posted_urls)
        all_items.extend(items); stats["nossop-rss"] = len(items)
    if "gazeta" in sources_subset:
        items = fetch_rss("web-gazeta", "https://www.gazetaesportiva.com/times/palmeiras/feed/",
                          2, cutoff, posted_urls)
        all_items.extend(items); stats["gazeta"] = len(items)
    if "uol" in sources_subset:
        items = fetch_rss("web-uol", "https://rss.uol.com.br/feed/esporte.xml",
                          2, cutoff, posted_urls, palmeiras_keyword_required=True)
        all_items.extend(items); stats["uol"] = len(items)
    if "verdazzo" in sources_subset:
        items = fetch_rss("web-verdazzo", "https://www.verdazzo.com.br/feed/",
                          2, cutoff, posted_urls, hygiene_filter=True)
        all_items.extend(items); stats["verdazzo"] = len(items)
    if "globoesporte" in sources_subset:
        items = fetch_ge_globo(cutoff, posted_urls)
        all_items.extend(items); stats["globoesporte"] = len(items)

    print(f"INFO: stats={stats} total_fresh={len(all_items)}")

    if not all_items:
        # Soft success: nothing fresh to publish
        output_path.write_text("NO_REPLY", encoding="utf-8")
        emit_status("skipped", str(output_path),
                    reason=f"no fresh items in last {max_age_hours}h across {len(stats)} sources")

    # 3. Group items about the same story (mechanical clustering only)
    topics = group_into_topics(all_items)
    print(f"INFO: grouped into {len(topics)} candidate topics")

    # 4. Load recent published titles — passed to curate step for LLM-based dedup.
    # Primary source: Notion (ground truth). Fallback: posts-history.md.
    notion_titles = fetch_notion_history_titles()
    local_titles = load_history_titles()
    # Merge: Notion titles first (authoritative), then local ones not already covered.
    seen_norm = {t.lower().strip() for t in notion_titles}
    extra_local = [t for t in local_titles if t.lower().strip() not in seen_norm]
    history_titles = notion_titles + extra_local

    # 5. Build flat candidate list. NO editorial filtering — that's curate's job.
    now_ts = time.time()
    candidates: List[Dict[str, Any]] = []
    for t in topics:
        fontes_out = []
        for f in t["fontes"]:
            entry = {
                "nome": f["source"],
                "tier": f["tier"],
                "title": f["title"],
                "url": f["url"],
                "excerpt": f.get("excerpt", ""),
            }
            if f.get("image_url"):
                entry["image_url"] = f["image_url"]
            fontes_out.append(entry)
        primary_ts = t.get("primary_ts", 0) or 0
        age_hours = round((now_ts - primary_ts) / 3600, 1) if primary_ts else None
        candidates.append({
            "primary_title": t["primary_title"],
            "primary_url": t["primary_url"],
            "primary_image": t.get("primary_image"),
            "age_hours": age_hours,
            "n_fontes": len(t["fontes"]),
            "n_outlets": len({f["source"] for f in t["fontes"]}),
            "has_tier1": any(f["tier"] == 1 for f in t["fontes"]),
            "titulos_originais": t["titulos_originais"],
            "fontes": fontes_out,
        })

    # Stable order: most-corroborated, freshest first (informational; curate decides).
    candidates.sort(
        key=lambda c: (
            c["n_outlets"],
            c["has_tier1"],
            c["age_hours"] is not None and -c["age_hours"] or 0,
        ),
        reverse=True,
    )

    output_data = {
        "candidates": candidates,
        "history_titles": history_titles,
        "stats": {**stats, "total_fresh": len(all_items), "n_candidates": len(candidates)},
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %z", time.localtime(now_ts)),
    }
    output_path.write_text(json.dumps(output_data, ensure_ascii=False, indent=2), encoding="utf-8")
    emit_status("ready", str(output_path),
                reason=f"{len(candidates)} candidates from {len(stats)} sources")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        fail(f"unhandled exception: {type(exc).__name__}: {exc}")
