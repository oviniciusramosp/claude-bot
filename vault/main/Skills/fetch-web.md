---
title: Fetch Web Content
description: Standard procedure for fetching and parsing web content. Covers tool selection (PinchTab vs curl), RSS parsing, HTML extraction, retries, and rate limiting.
type: skill
created: 2026-04-10
updated: 2026-04-10
trigger: "when a routine or pipeline step needs to fetch content from a web URL, RSS feed, or API — use /fetch-web or reference this skill"
tags: [skill, web, fetch, scraping, pinchtab, rss]
---

# Fetch Web Content

Canonical procedure for retrieving content from the web. Standardizes tool selection, parsing patterns, and error handling across all pipelines.

## Tool selection

**Always read `Tooling.md` first** — it is the authoritative source for tool preferences.

Decision tree:

```
Is it a JSON API or RSS/XML feed?
  → curl + urllib (fast, no overhead)

Is it a static HTML page (no JS required)?
  → curl + HTML parser (regex or xml.etree)

Is it a JS-heavy SPA or requires login?
  → PinchTab (logged session, JS rendering)

Is it rate-limited or behind bot detection?
  → PinchTab (real browser, authenticated)
```

## Prerequisites

- **PinchTab** running on `http://localhost:9870` (for JS/logged sites) — see `Tooling.md`
- `PINCHTAB_ALLOW_EVALUATE=1` in env if JS evaluation is needed
- Python stdlib only (no `requests`, `beautifulsoup4` — the bot is stdlib-only)

## Input contract

- `url` (string, required) — target URL
- `method` (string, default "auto") — `curl`, `pinchtab`, `auto`
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

## Method 2 — PinchTab (JS/logged sites)

### Step 1 — Health check

```python
import subprocess
try:
    subprocess.run(["curl", "-s", "--max-time", "3", "http://localhost:9870/"],
                   check=True, capture_output=True, timeout=5)
    pinchtab_ok = True
except Exception:
    pinchtab_ok = False

if not pinchtab_ok:
    # Fall back to curl or notify
    raise RuntimeError("PinchTab unavailable — cannot fetch JS-heavy sites")
```

### Step 2 — Navigate and extract

```bash
pinchtab nav "$URL" --port 9870
sleep 2  # allow JS to render
pinchtab text --port 9870
```

Or programmatically:

```python
subprocess.run(["pinchtab", "nav", url, "--port", "9870"], check=True, timeout=30)
time.sleep(2)
result = subprocess.run(["pinchtab", "text", "--port", "9870"],
                        capture_output=True, text=True, timeout=10)
page_text = result.stdout
```

### Step 3 — Snapshot for structured extraction

When you need to click, fill, or navigate deeper:

```bash
pinchtab snap -i -c --port 9870
```

This returns a structured snapshot with clickable element references. Use `pinchtab click <ref>` and `pinchtab fill <ref> "text"` for interaction.

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
    "method": "curl" | "pinchtab",
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
| 403 Forbidden | Bot detection / geoblock | Try PinchTab fallback; if still 403, notify user |
| 429 | Rate limited | Exponential backoff, max 3 retries |
| 5xx | Server error | Retry 3x with backoff, then abort |
| Connection timeout | Network / slow site | Retry with progressive timeout, then abort |
| SSL error | Cert issue | Log, abort (do NOT skip SSL verification) |
| Empty body | Soft block / JS required | Try PinchTab |
| Non-UTF8 content | Charset mismatch | Decode with `errors="replace"` + log warning |
| PinchTab down | Service not running | Notify user to start PinchTab |

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
- For complex HTML parsing, prefer PinchTab's `text` extraction over hand-written regex
- Reference implementations: `Routines/palmeiras-feed/steps/fetch-web.md`, `Routines/crypto-news/steps/collect.md`, `Routines/crypto-ta-analise/steps/collect-*.md`
- Tool preferences: always check `Tooling.md` before introducing a new fetching approach
