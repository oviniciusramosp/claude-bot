---
title: Fetch Web Content
description: Standard procedure for fetching and parsing web content. Covers tool selection (WebFetch/curl for public pages, the owner's Safari via scripts/safari.py for logged-in or JS pages), parallel browser use, RSS parsing, HTML extraction, retries, and rate limiting.
type: skill
created: 2026-04-10
updated: 2026-11-16
trigger: "when a routine or pipeline step needs to fetch content from a web URL, RSS feed, or API — use /fetch-web or reference this skill"
tags: [skill, web, fetch, scraping, safari, rss]
version: 2
---

# Fetch Web Content

Canonical procedure for retrieving content from the web. Standardizes tool selection, parsing patterns, and error handling across all pipelines.

## Tool selection

**Always read `Tooling.md` first** — it is the authoritative source for tool preferences.

Decision tree:

```
Is it a JSON API or RSS/XML feed?
  → curl + urllib (fast, no overhead)

Is it a public static HTML page (article, docs, no login)?
  → WebFetch, or curl + HTML parser (regex or xml.etree)

Is it a JS-heavy SPA or does it require login (X, Threads, banks…)?
  → Safari via scripts/safari.py (the owner's logged-in sessions, real JS rendering)

Is it rate-limited or behind bot detection?
  → Safari via scripts/safari.py (real browser, authenticated)
```

If Safari can't do something, the backup is Chrome with the Claude extension — the owner has to enable it, so ask before relying on it. PinchTab was removed on 2026-11-16: never call `pinchtab` or ports 9867/9869/9870.

## Concurrency caveats — parallel browser use

`scripts/safari.py` opens **each page in its own Safari window** and closes only that window, so parallel pipeline steps no longer share one "current URL" and can't overwrite each other's navigation (the race that used to hit PinchTab's single session).

Still, avoid heavy parallel browser use:

- Every window is a real page in the owner's Safari — many at once slow the Mac down and compete with whatever the owner is doing.
- Authenticated SPAs (X, Threads) rate-limit and flag bursts from the same logged-in account. Hitting them from several steps at once looks like a bot.

**Rule:** in a pipeline where several steps read logged-in sites through Safari, prefer chaining them with `depends_on:` (a few seconds of serialization) over running them all at once. Two independent sites in parallel is fine; a fan-out of browser steps is not.

```yaml
# PREFER — browser steps on the same logged-in account run one after another
steps:
  - id: collect-x
    method: safari
  - id: collect-threads
    method: safari
    depends_on: [collect-x]
```

## Prerequisites

- **Safari** on this Mac with the owner's logins, scriptable once (owner, one time): Safari ▸ Settings ▸ Advanced ▸ "Show features for web developers", then Develop ▸ "Allow JavaScript from Apple Events", and allow the calling app under System Settings ▸ Privacy & Security ▸ Automation ▸ Safari. `python3 scripts/safari.py check` tells whether it's ready.
- Python stdlib only (no `requests`, `beautifulsoup4` — the bot is stdlib-only)

## Input contract

- `url` (string, required) — target URL
- `method` (string, default "auto") — `curl`, `safari`, `auto`
- `timeout` (int, default 20) — seconds
- `user_agent` (string, optional) — custom UA (default: Mozilla/5.0 Chrome/120)
- `parse` (string, optional) — `rss`, `json`, `html-text`, `html-links`, `raw`

## Method 1 — curl + urllib (static content)

### Step 1 — Basic GET

```python
import urllib.request, json

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

req = urllib.request.Request(url, headers={
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
})
with urllib.request.urlopen(req, timeout=timeout) as resp:
    content = resp.read().decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
    status = resp.status
```

### Step 2 — Parse based on content type

**RSS/Atom (XML):**

```python
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

root = ET.fromstring(content)
items = []

# RSS 2.0
for item in root.iter("item"):
    title = item.findtext("title", "").strip()
    link = item.findtext("link", "").strip()
    pub_date = item.findtext("pubDate", "").strip()
    description = item.findtext("description", "").strip()
    try:
        ts = parsedate_to_datetime(pub_date).timestamp()
    except Exception:
        ts = 0
    items.append({"title": title, "link": link, "published_ts": ts, "description": description})

# Atom (namespace-aware)
# atom_ns = {"a": "http://www.w3.org/2005/Atom"}
# for entry in root.findall("a:entry", atom_ns): ...
```

**JSON API:**

```python
data = json.loads(content)
```

**HTML text extraction** (heuristic, no BeautifulSoup):

```python
import re
# Strip scripts and styles
clean = re.sub(r"<script\b[^>]*>.*?</script>", "", content, flags=re.DOTALL | re.IGNORECASE)
clean = re.sub(r"<style\b[^>]*>.*?</style>", "", clean, flags=re.DOTALL | re.IGNORECASE)
# Strip tags
clean = re.sub(r"<[^>]+>", " ", clean)
# Collapse whitespace
clean = re.sub(r"\s+", " ", clean).strip()
# Decode HTML entities
import html
clean = html.unescape(clean)
```

**Extract headlines (heuristic):**

Lines between 15 and 250 chars containing topic keywords, excluding navigation/footer patterns:

```python
lines = [l.strip() for l in clean.split("\n") if l.strip()]
headlines = []
keywords = re.compile(r"palmeiras|verdão|verdao|abel|alviverde", re.IGNORECASE)
noise = re.compile(r"cookie|assinante|publicidade|©|todos os direitos", re.IGNORECASE)

for line in lines:
    if 15 <= len(line) <= 250 and keywords.search(line) and not noise.search(line):
        headlines.append(line)
        if len(headlines) >= 8:
            break
```

## Method 2 — Safari (JS/logged sites)

Paths below are relative to the repo root (`~/claude-bot`).

### Step 1 — Check Safari is scriptable

```bash
python3 scripts/safari.py check
```

If it fails, the error says which switch is off — report it to the owner (it's a one-time setting) and abort. Don't skip silently.

### Step 2 — Open and extract text

```bash
python3 scripts/safari.py text "$URL" --settle 3            # page text
python3 scripts/safari.py text "$URL" --settle 3 --scroll 3 # scroll to load more first
```

Or programmatically:

```python
import sys
sys.path.insert(0, "/Users/viniciusramos/claude-bot/scripts")
import safari

try:
    with safari.open_page(url, settle=3) as page:   # own window, closed on exit
        page.scroll(passes=3, pause=2)              # optional, for infinite feeds
        page_text = page.text()
except safari.SafariError as exc:
    raise RuntimeError(f"Safari fetch failed for {url}: {exc}")
```

### Step 3 — Structured extraction with JavaScript

Prefer a JS expression with CSS selectors over the raw text blob — it returns JSON (lists, dicts) with real links:

```bash
python3 scripts/safari.py js "$URL" "Array.from(document.querySelectorAll('article a[href*=status]')).map(a => a.href)"
```

```python
with safari.open_page(url, settle=3) as page:
    if "/login" in page.current_url():
        raise RuntimeError("Safari is not logged in on this site — the owner must log in once in Safari")
    items = page.js("Array.from(document.querySelectorAll('article')).slice(0,10).map(a => a.innerText)")
```

For a statement block, wrap it: `page.js("(() => { ...; return x; })()")`. For promises use `page.js_async(...)`.

**Login wall:** if the page lands on a login screen, say so plainly ("o Safari não está logado no X"). Never type passwords — the owner logs in once in Safari.

## Retry and timeout strategy

Standard pattern across all fetches:

```python
def fetch_with_retry(url, max_retries=3, base_timeout=20):
    last_error = None
    for attempt in range(max_retries):
        try:
            timeout = base_timeout * (1 + attempt * 0.5)  # progressive timeout
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode(errors="replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(2 ** attempt)  # exponential backoff
                last_error = e
                continue
            raise  # don't retry other HTTP errors
        except (urllib.error.URLError, TimeoutError) as e:
            time.sleep(2 ** attempt)
            last_error = e
            continue
    raise last_error
```

## Rate limiting per domain

Respect target sites. Defensive limits:

| Site type | Min delay between requests |
|-----------|---------------------------|
| Public API (Binance, Finnhub, etc.) | 200ms |
| News RSS feeds | 1s |
| HTML scraping (portals) | 3s |
| Authenticated SPA (X, Threads) | 5s |

For pipelines that hit the same domain many times, maintain a `last_request_time` dict and sleep as needed:

```python
_last_hit = {}
def throttle(domain, min_gap):
    now = time.time()
    gap = now - _last_hit.get(domain, 0)
    if gap < min_gap:
        time.sleep(min_gap - gap)
    _last_hit[domain] = time.time()
```

## Output normalization

Return a consistent dict to callers:

```python
{
    "url": url,
    "status": 200,
    "fetched_at": "2026-04-10T01:30:00-03:00",
    "method": "curl" | "safari",
    "content_type": "text/html",
    "parsed": {
        # parse-specific fields
        # For RSS: {"items": [...]}
        # For JSON: {"data": {...}}
        # For HTML: {"text": "...", "headlines": [...]}
    },
    "raw": "..." if caller asked for it,
}
```

## Error handling

| Symptom | Cause | Action |
|---------|-------|--------|
| 404 | URL wrong | Log, abort (don't retry) |
| 403 Forbidden | Bot detection / geoblock | Try the Safari method; if still 403, notify user |
| 429 | Rate limited | Exponential backoff, max 3 retries |
| 5xx | Server error | Retry 3x with backoff, then abort |
| Connection timeout | Network / slow site | Retry with progressive timeout, then abort |
| SSL error | Cert issue | Log, abort (do NOT skip SSL verification) |
| Empty body | Soft block / JS required | Try the Safari method |
| Non-UTF8 content | Charset mismatch | Decode with `errors="replace"` + log warning |
| `SafariError` (JavaScript from Apple Events / Automation) | Safari not scriptable | Notify the owner with the error text (one-time setting) |
| Login screen in Safari | Owner not logged in on that site | Notify the owner to log in once in Safari; never type passwords |

**All errors visible** — log with context (URL, method, attempt count) and notify user when the failure blocks a routine.

## Caching

For frequently-accessed resources (RSS feeds polled every 30min), cache results in `/tmp/fetch-cache/{url-hash}.json` with a TTL field. Skip fetches within the TTL.

```python
import hashlib
cache_dir = Path("/tmp/fetch-cache")
cache_dir.mkdir(exist_ok=True)
cache_key = hashlib.sha256(url.encode()).hexdigest()[:16]
cache_file = cache_dir / f"{cache_key}.json"

if cache_file.exists():
    cached = json.loads(cache_file.read_text())
    if time.time() - cached["fetched_ts"] < ttl:
        return cached["data"]
```

## Security and privacy

- **Never follow redirects to unknown domains** without validating
- **Never submit forms** unless the routine explicitly requires it
- **Never store credentials in URLs** (query strings leak to logs)
- **Never fetch URLs provided by untrusted sources** (pipeline inputs from other steps count as trusted IF the previous step was trusted)
- Respect `robots.txt` for scraping — for polite scraping, check before hitting unfamiliar domains

## Notes

- The bot is stdlib-only — NO `requests`, NO `beautifulsoup4`, NO `lxml`. Use `urllib` + `xml.etree` + `re` + `html`
- For complex HTML parsing, prefer Safari's `text` / `js` extraction over hand-written regex
- Reference implementations (Pipeline v2 scripts): `parmeirense/Routines/palmeiras-feed/scripts/scout_v2.py`, `crypto-bro/Routines/crypto-news-scout/scripts/collect_data_v2.py`, `crypto-bro/Routines/crypto-ta-analise/scripts/collect_*_v2.py`
- Tool preferences: always check `Tooling.md` before introducing a new fetching approach
