---
title: Review Calendar
description: Standard procedure for checking upcoming relevant dates and events (economic calendar, sports fixtures, macro events) to enrich routine context with time-sensitive information.
type: skill
created: 2026-04-10
updated: 2026-04-10
trigger: "when a routine or pipeline step needs to check upcoming events, match dates, economic releases, or any date-sensitive context — use /review-calendar or reference this skill"
tags: [skill, calendar, dates, events, finnhub, palmeiras, macro]
---

# Review Calendar

Canonical procedure for querying upcoming events that may affect routine output. Prevents pipelines from publishing stale or context-blind content (e.g., a "market outlook" that misses tomorrow's Fed meeting, or a "match preview" that ignores a scheduled game today).

## When to use this skill

Call it early in a pipeline (typically in a collection step) whenever the output should be aware of:

- **Economic calendar** — Fed meetings, CPI, unemployment, GDP, earnings
- **Sports fixtures** — upcoming Palmeiras matches, results of recent games
- **Crypto-specific events** — token unlocks, hard forks, ETF decisions
- **User's personal calendar** — birthdays, deadlines (if the user has provided a source)

## Prerequisites

Read from `vault/.env`:

- `FINNHUB_API_KEY` — economic calendar and market events
- `NOTION_API_KEY` + `NOTION_DB_PALMEIRAS_PARTIDAS` — Palmeiras match database (if maintained)

## Input contract

- `window_days` (int, default 7) — how many days ahead to look
- `categories` (list, default all) — `economic`, `sports`, `crypto`, `personal`
- `relevance_filter` (string, optional) — filter keyword (e.g., "Brazil", "Palmeiras", "BTC")
- `timezone` (string, default "America/Sao_Paulo") — BRT by default

## Date handling (critical)

Always use timezone-aware datetimes. BRT is UTC-3:

```python
import datetime
from datetime import timezone, timedelta

BRT = timezone(timedelta(hours=-3))
now_brt = datetime.datetime.now(BRT)
today = now_brt.date()
tomorrow = today + timedelta(days=1)
window_end = today + timedelta(days=window_days)

# ISO format for API queries
today_iso = today.isoformat()            # "2026-04-10"
window_end_iso = window_end.isoformat()  # "2026-04-17"
now_iso = now_brt.isoformat()            # "2026-04-10T01:30:00-03:00"
```

**24-hour cutoff for "recent" filtering:**

```python
cutoff_ts = now_brt.timestamp() - 86400  # 24 hours ago
# Compare with Unix timestamps from RSS pubDates, APIs, etc.
```

## Source 1 — Finnhub economic calendar

Finnhub's free tier includes economic events for major markets.

```python
import urllib.request, json

FINNHUB_KEY = env["FINNHUB_API_KEY"]

# Economic calendar (Fed meetings, CPI, etc.)
url = f"https://finnhub.io/api/v1/calendar/economic?from={today_iso}&to={window_end_iso}&token={FINNHUB_KEY}"
with urllib.request.urlopen(url, timeout=15) as resp:
    data = json.loads(resp.read())

events = data.get("economicCalendar", [])

# Filter by country (relevant: US, BR, EU for most routines)
relevant_countries = {"US", "BR", "EU", "CN"}
filtered = [
    {
        "time": e.get("time"),
        "country": e.get("country"),
        "event": e.get("event"),
        "impact": e.get("impact"),       # "low" | "medium" | "high"
        "forecast": e.get("forecast"),
        "previous": e.get("previous"),
        "actual": e.get("actual"),
    }
    for e in events
    if e.get("country") in relevant_countries and e.get("impact") in ("medium", "high")
]
```

**High-impact events** to always flag for crypto/markets routines:

- FOMC meeting, Fed rate decision
- US CPI (inflation)
- US Non-Farm Payrolls
- ECB rate decision
- Brazil COPOM (Selic rate)
- Brazil IPCA (inflation)

## Source 2 — Earnings calendar (Finnhub)

For stock/equity-related routines:

```python
url = f"https://finnhub.io/api/v1/calendar/earnings?from={today_iso}&to={window_end_iso}&token={FINNHUB_KEY}"
with urllib.request.urlopen(url, timeout=15) as resp:
    data = json.loads(resp.read())

earnings = data.get("earningsCalendar", [])
# Filter by large-cap symbols: AAPL, MSFT, NVDA, TSLA, META, GOOGL, AMZN, etc.
```

## Source 3 — Palmeiras fixtures (SofaScore)

SofaScore offers a free unofficial API used by `parmeirense` agent. Team ID for Palmeiras is `1963`.

```python
# Upcoming matches
url = "https://api.sofascore.com/api/v1/team/1963/events/next/0"
with urllib.request.urlopen(url, timeout=15) as resp:
    data = json.loads(resp.read())

matches = data.get("events", [])
for m in matches:
    home = m["homeTeam"]["name"]
    away = m["awayTeam"]["name"]
    start_ts = m["startTimestamp"]  # Unix UTC
    start_brt = datetime.datetime.fromtimestamp(start_ts, BRT)
    tournament = m["tournament"]["name"]
    # Relevant flags
    is_today = start_brt.date() == today
    is_tomorrow = start_brt.date() == tomorrow
    hours_until = (start_ts - now_brt.timestamp()) / 3600
```

**Recent results:**

```python
url = "https://api.sofascore.com/api/v1/team/1963/events/last/0"
with urllib.request.urlopen(url, timeout=15) as resp:
    data = json.loads(resp.read())

recent = data.get("events", [])
# Filter matches from last 48h
for m in recent:
    end_ts = m["startTimestamp"]
    if now_brt.timestamp() - end_ts < 172800:  # 48h
        score_home = m["homeScore"].get("current")
        score_away = m["awayScore"].get("current")
```

**Note:** SofaScore may block direct requests — add User-Agent and consider PinchTab fallback (see `Skills/fetch-web.md`).

## Source 4 — Notion Palmeiras matches database (if maintained)

If `NOTION_DB_PALMEIRAS_PARTIDAS` is actively updated, it's the most reliable source (curated by the user):

```python
import urllib.request, json

DB_ID = env["NOTION_DB_PALMEIRAS_PARTIDAS"]
NOTION_KEY = env["NOTION_API_KEY"]

url = f"https://api.notion.com/v1/databases/{DB_ID}/query"
payload = {
    "filter": {
        "and": [
            {"property": "Date", "date": {"on_or_after": today_iso}},
            {"property": "Date", "date": {"on_or_before": window_end_iso}},
        ]
    },
    "sorts": [{"property": "Date", "direction": "ascending"}],
}
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode(),
    headers={
        "Authorization": f"Bearer {NOTION_KEY}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28",
    },
    method="POST",
)
with urllib.request.urlopen(req, timeout=15) as resp:
    data = json.loads(resp.read())
    matches = data.get("results", [])
```

## Source 5 — Crypto-specific events

No single free source. Build a static list of known recurring events and augment with web fetch:

- **Token unlocks** — query tokenunlocks.app (scrape via `Skills/fetch-web.md`)
- **ETF decisions** — SEC calendar (scrape)
- **Hard forks** — CoinMarketCal API (free tier available, would need key)

**Alternative:** maintain a user-curated Notion database `crypto-events` with frontmatter-style entries.

## Relevance scoring

Not all events matter. Apply a relevance score before including in routine context:

```python
def score_event(event, context_keywords):
    score = 0
    # Impact level
    impact_score = {"low": 1, "medium": 3, "high": 5}
    score += impact_score.get(event.get("impact"), 0)
    # Proximity (sooner = more relevant)
    hours_until = event["hours_until"]
    if hours_until < 24: score += 5
    elif hours_until < 72: score += 3
    elif hours_until < 168: score += 1
    # Keyword match
    text = (event.get("event", "") + " " + event.get("country", "")).lower()
    for kw in context_keywords:
        if kw.lower() in text:
            score += 2
    return score

# Keep only events scoring >= 5
relevant = [e for e in all_events if score_event(e, ["fed", "cpi", "btc"]) >= 5]
```

## Output format

Return a structured dict that routines can inject into prompts:

```python
{
    "generated_at": "2026-04-10T01:30:00-03:00",
    "window_days": 7,
    "economic": [
        {
            "time": "2026-04-10T14:30:00Z",
            "time_brt": "2026-04-10 11:30 BRT",
            "hours_until": 10.5,
            "country": "US",
            "event": "CPI m/m",
            "impact": "high",
            "forecast": "0.3%",
            "previous": "0.4%",
        },
        ...
    ],
    "sports": {
        "next_match": {
            "opponent": "Corinthians",
            "competition": "Brasileirão",
            "date_brt": "2026-04-11 16:00 BRT",
            "is_today": False,
            "is_tomorrow": True,
            "venue": "Allianz Parque",
        },
        "recent_result": {
            "opponent": "Santos",
            "score": "2-1",
            "date_brt": "2026-04-08 21:30 BRT",
        },
    },
    "crypto": [],
    "summary": "US CPI in 10h (high impact). Palmeiras vs Corinthians tomorrow 16h BRT.",
}
```

The `summary` field is a one-line human-readable synthesis for quick injection into prompts.

## Error handling

| Symptom | Cause | Action |
|---------|-------|--------|
| Finnhub 401 | Key invalid | Log, skip economic section, continue |
| Finnhub 429 | Free tier limit | Use cached data if available, else skip |
| SofaScore 403 | Bot blocked | Fall back to PinchTab |
| Notion 404 | DB doesn't exist yet | Skip silently (not all users have this DB) |
| Date parse error | API format change | Log full payload, skip item |

**Graceful degradation:** missing sources should produce a partial result, not a full failure. The caller can still use whatever data came back.

## Notes

- **Keep responses small** — inject only the top 3–5 events into routine context, not the full week
- **Time zones matter** — always present times in BRT to the user (or their configured locale), even if APIs return UTC
- **Cache aggressively** — calendar data changes slowly; cache Finnhub results for 1 hour
- For sports beyond Palmeiras, the `SofaScore` pattern generalizes — just swap the team ID
- Reference: no existing pipeline uses this skill — it's new infrastructure. Once a pipeline adopts it, update this file with real-world tuning (relevance thresholds, keyword lists).
- Related: `Skills/fetch-web.md` (for scraping fallbacks), `Tooling.md` (tool preferences)
