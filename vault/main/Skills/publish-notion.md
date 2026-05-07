---
title: Publish to Notion
description: Standard procedure for publishing content to a Notion database. Handles authentication, block conversion, 100-block batching, cover images, and error recovery.
type: skill
created: 2026-04-10
updated: 2026-04-10
trigger: "when a routine or pipeline step needs to create a page in a Notion database — use /publish-notion or reference this skill"
tags: [skill, notion, publishing, integration]
---

# Publish to Notion

Canonical procedure for creating pages in a Notion database. All pipeline steps that publish to Notion MUST follow this skill to avoid duplicating logic.

## Prerequisites

1. **Read credentials from `vault/.env`:**
   - `NOTION_API_KEY` — required
   - Database ID — one of:
     - `NOTION_POSTS_DB_ID` — crypto/general posts
     - `NOTION_PALMEIRAS_DB_ID` — Palmeiras feed
     - `NOTION_DB_PALMEIRAS_PARTIDAS` — Palmeiras matches
     - `NOTION_DB_CRYPTO_NEWS` — crypto news
     - `NOTION_DB_CONTAS` — accounts/finance
     - `NOTION_DB_ADS` — ads tracking

2. **Notion API base:** `https://api.notion.com/v1`
3. **API version header:** `Notion-Version: 2022-06-28`

## Input contract

The caller provides:
- `title` (string, required) — page title
- `database_id` (string, required) — target database
- `content` (string, required) — markdown or custom markup to convert to blocks
- `properties` (dict, optional) — extra Notion page properties (Author, Category, Tags, Language, etc.)
- `cover_url` (string, optional) — external URL for page cover
- `icon` (string, optional) — emoji or external icon URL

## Procedure

### Step 1 — Load credentials

```python
import os, urllib.request, json, re
from pathlib import Path

env = {}
env_path = Path.home() / "claude-bot" / "vault" / ".env"
for line in env_path.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")

NOTION_API_KEY = env["NOTION_API_KEY"]
HEADERS = {
    "Authorization": f"Bearer {NOTION_API_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}
```

### Step 2 — Convert content to Notion blocks

**Custom markup supported** (legacy from crypto-news pipeline):

| Markup | Becomes |
|--------|---------|
| `[heading_1]text` | `heading_1` block |
| `[heading_2]text` | `heading_2` block |
| `[heading_3]text` | `heading_3` block |
| `[paragraph]text` | `paragraph` block |
| `[divider]` | `divider` block |
| `[quote]text` | `quote` block |
| `[bullet]text` | `bulleted_list_item` |
| `[numbered]text` | `numbered_list_item` |
| `[verde]text[/verde]` | paragraph with green annotation |
| `[vermelho]text[/vermelho]` | paragraph with red annotation |
| `**bold**` | rich_text with `bold: true` |
| `_italic_` | rich_text with `italic: true` |
| `` `code` `` | rich_text with `code: true` |
| `[link](url)` | rich_text with link |

**Block builder helpers:**

```python
def rich_text(content, bold=False, italic=False, code=False, color="default", link=None):
    ann = {"bold": bold, "italic": italic, "strikethrough": False,
           "underline": False, "code": code, "color": color}
    rt = {"type": "text", "text": {"content": content}, "annotations": ann}
    if link:
        rt["text"]["link"] = {"url": link}
    return rt

def paragraph(texts):
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": texts}}

def heading(level, text):
    return {"object": "block", "type": f"heading_{level}",
            f"heading_{level}": {"rich_text": [rich_text(text)]}}

def divider():
    return {"object": "block", "type": "divider", "divider": {}}
```

Parse the content line-by-line. For inline markup (`**bold**`, `_italic_`, `[link](url)`), use regex to split a line into `rich_text` segments.

### Step 3 — Build properties

Notion property types MUST match the database schema. Common patterns:

```python
properties = {
    "Title": {"title": [{"text": {"content": title}}]},
}

# Optional additions based on database schema:
if author:
    properties["Author"] = {"rich_text": [{"text": {"content": author}}]}
if category:
    properties["Category"] = {"multi_select": [{"name": category}]}
if tags:  # list of strings
    properties["Tags"] = {"multi_select": [{"name": t} for t in tags]}
if language:
    properties["Language"] = {"select": {"name": language}}
if url:
    properties["URL"] = {"url": url}
if date_iso:
    properties["Date"] = {"date": {"start": date_iso}}
properties.setdefault("Published", {"checkbox": False})
```

**ALWAYS check the target database's actual schema first** before adding properties. If unsure, query `GET /v1/databases/{database_id}` and read the `properties` field.

### Step 4 — Create the page (first 100 blocks)

Notion limits `children` to 100 blocks per `POST /v1/pages`. Truncate and keep the remainder for batch-append:

```python
page = {
    "parent": {"database_id": database_id},
    "properties": properties,
    "children": all_blocks[:100],
}
if cover_url:
    page["cover"] = {"type": "external", "external": {"url": cover_url}}
if icon:
    if icon.startswith("http"):
        page["icon"] = {"type": "external", "external": {"url": icon}}
    else:
        page["icon"] = {"type": "emoji", "emoji": icon}

req = urllib.request.Request(
    "https://api.notion.com/v1/pages",
    data=json.dumps(page).encode(),
    headers=HEADERS,
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read())
    page_id = result["id"]
    page_url = result["url"]
```

### Step 5 — Append remaining blocks (if >100)

```python
remaining = all_blocks[100:]
while remaining:
    batch = remaining[:100]
    remaining = remaining[100:]
    req = urllib.request.Request(
        f"https://api.notion.com/v1/blocks/{page_id}/children",
        data=json.dumps({"children": batch}).encode(),
        headers=HEADERS,
        method="PATCH",
    )
    urllib.request.urlopen(req, timeout=30).read()
```

### Step 6 — Return result

Return the page URL and ID so the caller can notify the user or log the publication.

## Error handling

All errors MUST be visible (CLAUDE.md zero-silent-errors policy):

1. **401 Unauthorized** — API key invalid or expired. Log error, notify user via Telegram, do NOT retry.
2. **400 Bad Request** — schema mismatch. Log the Notion error message + the properties sent. Notify user. Do NOT retry.
3. **429 Rate limit** — wait 5s, retry up to 3 times with exponential backoff.
4. **5xx** — retry up to 3 times with 2s backoff. If still failing, notify user.
5. **Network timeout** — retry once with 60s timeout.

On unrecoverable failure, write the full payload to `/tmp/notion-failed-{timestamp}.json` and include the path in the error message so the user can manually recover.

## Deduplication

Before creating a page, the caller SHOULD check if an equivalent page already exists. Strategies:

- **By URL property** — query `POST /v1/databases/{database_id}/query` with filter on URL
- **By title fuzzy match** — normalize (lowercase, strip accents, strip punctuation) and compare
- **By state file** — maintain a JSON state file with last-N published URLs/titles (see `vault/Agents/parmeirense/feed-state.json` for a reference pattern)

Skipping duplicates is the caller's responsibility — this skill always creates a new page when called.

## Notes

- **Never hardcode database IDs** — always read from `vault/.env`
- **Never hardcode API keys** — always read from `vault/.env`
- Blocks have a 2000-character content limit per `rich_text` element — split long paragraphs
- Images inside content use `image` blocks with `{"type": "external", "external": {"url": ...}}` — host via `Skills/generate-image.md` (catbox.moe upload pattern)
- For Telegram notification after publishing, read `agent.md` for `chat_id`/`thread_id` and use the bot's standard sendMessage pattern
- Reference implementations (Pipeline v2 scripts): `crypto-bro/Routines/crypto-news-produce/scripts/publish_notion_v2.py`, `crypto-bro/Routines/crypto-ta-analise/scripts/publish_notion_ta_v2.py`, `parmeirense/Routines/palmeiras-feed/scripts/publish_notion_v2.py`
