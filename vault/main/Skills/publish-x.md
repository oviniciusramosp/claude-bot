---
title: Publish to X (Twitter)
description: Standard procedure for posting to X via the owner's Safari (scripts/safari.py, text posts) or cookie-based API (needed for media). Handles threads, media, character limits, and rate limiting.
type: skill
created: 2026-04-10
updated: 2026-11-16
trigger: "when a routine or pipeline step needs to post a tweet or thread to X/Twitter — use /publish-x or reference this skill"
tags: [skill, x, twitter, publishing, safari]
---

# Publish to X (Twitter)

Canonical procedure for posting to X. There is NO official free API for posting — this skill uses two documented approaches.

## Method selection

**Default for text posts: Safari (the owner's logged-in session)** via `scripts/safari.py`. Read the "Web browsing" section of `Tooling.md` first.

| Use Safari when | Use cookie API when |
|-----------------|---------------------|
| Text-only posts and threads | Posts with media (images/video) |
| Low-volume posting (≤10/day) | Higher volume |
| The owner is logged into X in Safari | Safari is not logged in / not scriptable |

Both methods fail if X requires a fresh login or 2FA challenge. The caller MUST handle that gracefully. Agents never type passwords — if X shows a login screen, say so and stop.

## Prerequisites

- `X_AUTH_TOKEN` and `X_CT0` cookies in `vault/.env` (rotate monthly — see expiration notes below) — for Method 2
- `TWITTER_LIST_ID` (optional — for list-scoped operations)
- For Method 1: Safari logged into X, and scriptable (`python3 scripts/safari.py check` — one-time owner setting: Develop ▸ "Allow JavaScript from Apple Events" + Automation permission)

## Input contract

- `text` (string, required) — tweet body (will be auto-threaded if >280 chars)
- `media_paths` (list of strings, optional) — local image/video paths (max 4 per tweet)
- `reply_to_id` (string, optional) — if posting as a reply to an existing tweet
- `thread` (bool, default False) — if True, split long text into a thread

## Method 1 — Safari (preferred for text)

Run from the repo root (`~/claude-bot`). Keep the **same window open for the whole flow** (open → fill → click → confirm) by using `safari.open_page` as a context manager — the one-shot CLI commands close the window after each call, which would lose the draft.

### Step 1 — Check Safari is scriptable

```bash
python3 scripts/safari.py check
```

If it fails, abort and pass the error text to the owner (it names the switch to turn on).

### Step 2 — Open compose, detect login wall, fill, post, confirm

```python
import sys, time, json
sys.path.insert(0, "/Users/viniciusramos/claude-bot/scripts")
import safari

def post_to_x(text: str) -> str:
    with safari.open_page("https://x.com/compose/post", settle=4) as page:
        url = page.current_url()
        if "/login" in url or "/i/flow/login" in url:
            raise RuntimeError("X session expired — o Safari não está logado no X; o dono precisa entrar uma vez no Safari")

        # Composer is a contenteditable; insertText keeps X's editor state in sync
        ok = page.js("""(() => {
            const box = document.querySelector('[data-testid="tweetTextarea_0"]');
            if (!box) return false;
            box.focus();
            return document.execCommand('insertText', false, %s);
        })()""" % json.dumps(text))
        if not ok:
            raise RuntimeError("X composer not found (UI change?)")

        time.sleep(1)
        clicked = page.js("""(() => {
            const b = document.querySelector('[data-testid="tweetButton"]');
            if (!b || b.disabled || b.getAttribute('aria-disabled') === 'true') return false;
            b.click(); return true;
        })()""")
        if not clicked:
            raise RuntimeError("Post button missing or disabled (empty/too long text?)")

        # Confirm: the compose dialog closes / composer disappears
        for _ in range(20):
            time.sleep(1)
            if not page.js("!!document.querySelector('[data-testid=\"tweetTextarea_0\"]')"):
                return page.current_url()
        raise RuntimeError("Post not confirmed within 20s — check X manually before retrying (avoid duplicates)")
```

If the confirmation times out, **do not retry blindly** — the post may have gone out. Check the profile first.

### Step 3 — Media

Attaching media through Safari JavaScript is **not reliable**: a page script can't fill a file input with a local file. Posts with media must use **Method 2** (cookie API media upload) or be done by the owner by hand. Don't try to fake the upload.

### Step 4 — Threading (if text >280 chars)

Split text into chunks ≤270 chars (leave 10 chars for `" 1/N"` counter). After posting the first tweet:

1. Open the posted tweet's URL with `safari.open_page`
2. Click "Reply" (`[data-testid="reply"]`) via `page.js`
3. Fill the reply composer the same way (`tweetTextarea_0` + `insertText`) with the next chunk (`" 2/N"`)
4. Click `[data-testid="tweetButton"]`, confirm, repeat until all chunks posted

Each chunk should end or start with `" i/N"` counter to make the thread readable. For long threads, Method 2 (chaining `reply_to_id`) is more robust.

## Method 2 — Cookie-based API (GraphQL)

**Warning: cookies expire monthly.** If `X_AUTH_TOKEN` or `X_CT0` rotate, this method fails with 401. The caller MUST detect this and fall back to Safari (Method 1, text only) or notify the user.

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

Media goes through `https://upload.twitter.com/1.1/media/upload.json` in 3 phases: INIT, APPEND, FINALIZE. This is brittle, but it is the only automated way to post media — Safari JavaScript can't attach local files. If it fails, hand the media post to the owner.

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
| Safari lands on `/login` / `/i/flow/login` | Safari not logged into X | Notify the owner to log in once in Safari, abort (never type passwords) |
| `SafariError` | Safari not scriptable | Pass the error text to the owner, abort |
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
