---
title: Publish to Threads
description: Standard procedure for posting to Threads (Meta) via PinchTab. Handles single posts, carousels of images, and character limits.
type: skill
created: 2026-04-10
updated: 2026-04-10
trigger: "when a routine or pipeline step needs to post to Threads — use /publish-threads or reference this skill"
tags: [skill, threads, meta, publishing, pinchtab]
---

# Publish to Threads

Canonical procedure for posting to Threads. There is no stable public API for Threads posting from third-party clients — this skill uses PinchTab (logged-in browser session) exclusively.

## Prerequisites

1. **PinchTab running** on `http://localhost:9870` — check `Tooling.md` for the current preferred setup
2. **User logged into Threads** in the PinchTab-managed browser profile (`https://www.threads.net`)
3. `PINCHTAB_ALLOW_EVALUATE=1` in env if any JS evaluation is needed

## Input contract

- `text` (string, required) — post body (max 500 chars per post)
- `media_paths` (list of strings, optional) — local image paths (up to 10 per post for carousel)
- `reply_to_url` (string, optional) — Threads post URL to reply to
- `thread` (bool, default False) — split long text into a numbered thread of replies

## Procedure

### Step 1 — Verify PinchTab is reachable

```bash
curl -s --max-time 3 http://localhost:9870/ || {
  echo "pinchtab-unavailable"
  exit 1
}
```

If unavailable, notify user and abort: **"PinchTab is not running — start it with `pinchtab serve --port 9870`"**.

### Step 2 — Verify Threads session

```bash
pinchtab nav "https://www.threads.net" --port 9870
sleep 2
pinchtab text --port 9870 | head -40
```

Look for signals:
- **Logged in**: presence of "New thread", "Home", profile link
- **Not logged in**: "Log in", "Sign up", redirect to `/login`

If not logged in, abort with: **"Threads session expired — manual login required in the PinchTab browser"**.

### Step 3 — Open the composer

```bash
pinchtab nav "https://www.threads.net" --port 9870
pinchtab snap -i -c --port 9870
```

Find and click the "New thread" button (usually top-right, labeled `aria-label="Create"` or similar). Alternative: hotkey `n` on some layouts.

### Step 4 — Fill the text

Snapshot the composer:

```bash
pinchtab snap -i -c --port 9870
```

Locate the textarea (role="textbox", contenteditable). Fill via:

```bash
pinchtab fill <ref> "post text" --port 9870
```

If text contains special chars (emoji, newlines, quotes), escape appropriately for the shell.

### Step 5 — Attach media (if any)

For each image in `media_paths`:

1. Find the file input (hidden `<input type="file">` — Threads uses a paperclip/image icon)
2. Use PinchTab file upload to attach
3. Wait for preview thumbnail to appear (poll `pinchtab snap` every 500ms, max 15s)

For **carousels** (multiple images), Threads auto-arranges them. Order matches upload order. Max 10 images per post.

### Step 6 — Post

Click the "Post" button (`aria-label="Post"` or text "Post"). Wait for success:
- URL change to `/home`
- Composer dismissed
- New post visible in feed (optional verification)

Timeout: 30 seconds. If timeout, snapshot the page and include it in the error report.

### Step 7 — Threading (long text)

If `text` >500 chars or `thread=True`:

1. Split text into chunks ≤490 chars, prefer sentence boundaries (`. `, `! `, `? `)
2. Append ` {i}/{n}` counter to each chunk
3. Post the first chunk (Step 4–6)
4. Wait for URL update to `/.../post/{id}`
5. Click "Reply" on the new post
6. Repeat Steps 4–6 with the next chunk
7. Continue until all chunks posted

### Step 8 — Verify and return

After posting, grab the post URL from the browser URL bar:

```bash
pinchtab eval "window.location.href" --port 9870
```

Return the URL to the caller for logging and downstream use (e.g., Telegram notification link).

## Character limits

- **Single post:** 500 chars
- **Image alt text:** 1000 chars
- **Max images per post:** 10
- **Max videos per post:** 1 (max 5 minutes)
- **Video size:** 100MB max

## Error handling

| Symptom | Cause | Action |
|---------|-------|--------|
| `/login` redirect | Session expired | Notify user, abort |
| "Action blocked" | Rate limit / spam filter | Stop posting, wait 1h, notify user |
| Composer doesn't open | UI change / slow load | Retry once with 5s wait, then abort |
| Image upload stuck | Large file / network | Timeout after 30s, abort |
| Post button disabled after fill | Validation failed (empty, too long) | Inspect text length, re-validate |
| "Something went wrong" toast | Temporary Threads issue | Retry once after 10s |

**All errors visible** — log and notify via Telegram.

## Rate limit awareness

Threads is aggressive about automation detection. Defensive limits:

- **Max 1 post per 2 minutes** from automated routines
- **Max 20 posts per day** total (across all routines)
- **Max 3 posts per routine run**
- **Random jitter**: 2–8 seconds between actions within a single post flow

If multiple pipelines post to Threads, coordinate via a shared lock file at `/tmp/threads-publish.lock` (similar to the palmeiras-feed pattern).

## Notes

- Threads UI changes frequently — this skill describes the intent; exact selectors may need adjustment. Always `snap` before `click`/`fill` to verify current structure.
- **NEVER post without explicit approval in the routine design.** Posting is an irreversible public action.
- Media should be hosted or accessible locally — for generated images, use `Skills/generate-image.md` first and save locally before upload.
- Reference: no existing pipeline posts to Threads yet — this skill is new infrastructure. When a pipeline adopts it, update this file with learnings.
- Related tool documentation: `Tooling.md` (PinchTab section)
