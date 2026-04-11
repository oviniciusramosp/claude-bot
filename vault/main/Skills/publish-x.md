---
title: Publish to X (Twitter)
description: Standard procedure for posting to X via PinchTab (preferred) or cookie-based API. Handles threads, media, character limits, and rate limiting.
type: skill
created: 2026-04-10
updated: 2026-04-10
trigger: "when a routine or pipeline step needs to post a tweet or thread to X/Twitter — use /publish-x or reference this skill"
tags: [skill, x, twitter, publishing, pinchtab]
---

# Publish to X (Twitter)

Canonical procedure for posting to X. There is NO official free API for posting — this skill uses two documented approaches.

## Method selection

**Default: PinchTab (logged-in browser session).** Read `Tooling.md` first to confirm PinchTab is the preferred browser automation tool.

| Use PinchTab when | Use cookie API when |
|-------------------|---------------------|
| Interactive debugging | Fully automated pipeline step |
| Low-volume posting (≤10/day) | Higher volume |
| The user is already logged in | Headless/scheduled execution |

Both methods fail if X requires a fresh login or 2FA challenge. The caller MUST handle that gracefully.

## Prerequisites

- `X_AUTH_TOKEN` and `X_CT0` cookies in `vault/.env` (rotate monthly — see expiration notes below)
- `TWITTER_LIST_ID` (optional — for list-scoped operations)
- PinchTab running on `http://localhost:9870` (for Method 1)

## Input contract

- `text` (string, required) — tweet body (will be auto-threaded if >280 chars)
- `media_paths` (list of strings, optional) — local image/video paths (max 4 per tweet)
- `reply_to_id` (string, optional) — if posting as a reply to an existing tweet
- `thread` (bool, default False) — if True, split long text into a thread

## Method 1 — PinchTab (preferred)

### Step 1 — Check PinchTab availability

```bash
curl -s --max-time 3 http://localhost:9870/ || echo "pinchtab-down"
```

If down, abort and notify user to start PinchTab (`pinchtab serve --port 9870`).

### Step 2 — Navigate to compose

```bash
pinchtab nav "https://x.com/compose/post" --port 9870
```

If redirected to `/login` or `/i/flow/login`, abort with clear error: **"X session expired — manual login required"**.

### Step 3 — Snapshot and fill

```bash
pinchtab snap -i -c --port 9870
```

Locate the composer textarea (role="textbox", `data-testid="tweetTextarea_0"`). Use `pinchtab fill <ref> "text" --port 9870`.

For **media attachments**: find the file input (`data-testid="fileInput"`) and upload via PinchTab's file upload. Wait for upload confirmation before posting.

### Step 4 — Post

Click the "Post" button (`data-testid="tweetButtonInline"`). Poll for confirmation (URL change to `/home` or success toast).

### Step 5 — Threading (if text >280 chars)

Split text into chunks ≤270 chars (leave 10 chars for `" 1/N"` counter). After posting the first tweet:

1. Navigate to the posted tweet's URL
2. Click "Reply"
3. Fill the composer with the next chunk (`" 2/N"`)
4. Repeat until all chunks posted

Each chunk should end or start with `" i/N"` counter to make the thread readable.

## Method 2 — Cookie-based API (GraphQL)

**Warning: cookies expire monthly.** If `X_AUTH_TOKEN` or `X_CT0` rotate, this method fails with 401. The caller MUST detect this and fall back to PinchTab or notify the user.

### Step 1 — Build headers

```python
import os, urllib.request, json

X_AUTH = env["X_AUTH_TOKEN"]
X_CT0 = env["X_CT0"]

HEADERS = {
    "authorization": "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA",  # public X web token
    "cookie": f"auth_token={X_AUTH}; ct0={X_CT0}",
    "x-csrf-token": X_CT0,
    "content-type": "application/json",
    "x-twitter-auth-type": "OAuth2Session",
    "x-twitter-active-user": "yes",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}
```

### Step 2 — POST tweet via GraphQL

```python
endpoint = "https://x.com/i/api/graphql/SoVnbfCycZ7fERGCwpZkYA/CreateTweet"

payload = {
    "variables": {
        "tweet_text": text,
        "dark_request": False,
        "media": {"media_entities": [], "possibly_sensitive": False},
        "semantic_annotation_ids": [],
    },
    "features": {
        "tweetypie_unmention_optimization_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "tweet_awards_web_tipping_enabled": False,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_graphql_exclude_directive_enabled": True,
        "verified_phone_label_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_enhance_cards_enabled": False,
    },
    "queryId": "SoVnbfCycZ7fERGCwpZkYA",
}
if reply_to_id:
    payload["variables"]["reply"] = {
        "in_reply_to_tweet_id": reply_to_id,
        "exclude_reply_user_ids": [],
    }

req = urllib.request.Request(
    endpoint,
    data=json.dumps(payload).encode(),
    headers=HEADERS,
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read())
    tweet_id = result["data"]["create_tweet"]["tweet_results"]["result"]["rest_id"]
```

**Note:** GraphQL `queryId` values change occasionally — if you get 400, inspect a live browser request and update the endpoint + queryId.

### Step 3 — Media upload (cookie method)

Media goes through `https://upload.twitter.com/1.1/media/upload.json` in 3 phases: INIT, APPEND, FINALIZE. This is brittle — prefer PinchTab when posting media.

## Threading rules

- Break text on sentence boundaries (`. `, `! `, `? `) when possible, never mid-word
- Each chunk ≤270 chars, append ` {i}/{n}` counter
- First chunk is the "hook" — make it punchy
- Post chunks sequentially, using the previous tweet's ID as `reply_to_id`

## Error handling

| Symptom | Cause | Action |
|---------|-------|--------|
| 401 on cookie method | `X_AUTH_TOKEN`/`X_CT0` expired | Notify user: "X cookies expired — run cookie refresh routine" |
| 403 | Account flagged | Stop all X posting, notify user immediately |
| 429 | Rate limit | Exponential backoff, max 3 retries. Log wait time |
| PinchTab `/login` redirect | Session expired | Notify user, abort |
| Duplicate content | X rejects identical tweets within 24h | Skip silently, log once |
| Text >25000 chars | Exceeds X long-tweet limit | Truncate with `…` and warn |

**ALL errors MUST be visible.** No silent failures. Log with `logging.error()` and notify via Telegram when possible.

## Cookie rotation

`X_AUTH_TOKEN` and `X_CT0` expire roughly monthly. When a pipeline step fails with 401:

1. Bot notifies user via Telegram
2. User opens browser, logs into X, copies cookies from DevTools → Application → Cookies
3. User updates `vault/.env` with new values
4. Next run recovers automatically

A future routine `x-cookie-health-check` should ping `GET /i/api/graphql/.../Viewer` daily and alert 3 days before expected expiration.

## Notes

- **NEVER post on behalf of the user without explicit approval in the original routine design.** Posting is an irreversible public action.
- The user's handle and account are in `vault/.env` (or inferable from the cookies) — do not hardcode
- For image posts, the image URL should be accessible (use `Skills/generate-image.md` + catbox.moe upload first)
- Reference: no existing pipeline posts to X yet — this skill is new infrastructure
