---
title: Publish to Threads
description: Standard procedure for posting to Threads (Meta) via the owner's Safari (scripts/safari.py). Handles text posts, threads and character limits; image carousels need the owner.
type: skill
created: 2026-04-10
updated: 2026-11-16
trigger: "when a routine or pipeline step needs to post to Threads — use /publish-threads or reference this skill"
tags: [skill, threads, meta, publishing, safari]
---

# Publish to Threads

Canonical procedure for posting to Threads. There is no stable public API for Threads posting from third-party clients — this skill uses the owner's **Safari** (logged-in session) via `scripts/safari.py` exclusively. Read the "Web browsing" section of `Tooling.md` first.

## Prerequisites

1. **Safari scriptable** — `python3 scripts/safari.py check` (run from the repo root, `~/claude-bot`). One-time owner setting: Develop ▸ "Allow JavaScript from Apple Events" + Automation permission for the calling app.
2. **Owner logged into Threads in Safari** (`https://www.threads.com`). Agents never type passwords.

## Input contract

- `text` (string, required) — post body (max 500 chars per post)
- `media_paths` (list of strings, optional) — local image paths (see Step 5: not automatable from Safari)
- `reply_to_url` (string, optional) — Threads post URL to reply to
- `thread` (bool, default False) — split long text into a numbered thread of replies

## Procedure

Keep the **same Safari window open for the whole flow** (open → compose → fill → post → confirm) by using `safari.open_page` as a context manager — the one-shot CLI commands close their window after each call.

### Step 1 — Verify Safari is scriptable

```bash
python3 scripts/safari.py check
```

If it fails, abort and pass the error text to the owner (it names the switch to turn on).

### Step 2 — Open Threads and verify the session

```python
import sys, time, json
sys.path.insert(0, "/Users/viniciusramos/claude-bot/scripts")
import safari

with safari.open_page("https://www.threads.com", settle=4) as page:
    url = page.current_url()
    body = page.js("document.body.innerText.slice(0, 2000)")
    logged_out = "/login" in url or ("Log in" in body and "New thread" not in body)
    if logged_out:
        raise RuntimeError("Threads session expired — o Safari não está logado no Threads; o dono precisa entrar uma vez no Safari")
    ...  # Steps 3–6 run inside this same `with` block
```

Signals:
- **Logged in**: "New thread" / "What's new?", "Home", profile link
- **Not logged in**: "Log in", "Sign up", redirect to `/login`

### Step 3 — Open the composer

```python
    opened = page.js("""(() => {
        const b = document.querySelector('[aria-label="Create"], [aria-label="New thread"]')
              || Array.from(document.querySelectorAll('div[role=button], a')).find(e => /what's new\?/i.test(e.innerText));
        if (!b) return false; b.click(); return true;
    })()""")
    if not opened:
        raise RuntimeError("Threads composer button not found (UI change?)")
    time.sleep(2)
```

### Step 4 — Fill the text

The composer is a contenteditable (`role="textbox"`). Focus it and insert the text with `execCommand('insertText')` so Threads' editor state updates:

```python
    ok = page.js("""(() => {
        const box = document.querySelector('div[role=dialog] [contenteditable=true][role=textbox]')
                 || document.querySelector('[contenteditable=true][role=textbox]');
        if (!box) return false;
        box.focus();
        return document.execCommand('insertText', false, %s);
    })()""" % json.dumps(text))
    if not ok:
        raise RuntimeError("Threads composer textbox not found")
```

`json.dumps` quotes emoji, newlines and quotes safely for JavaScript.

### Step 5 — Media (image carousels)

**Not automatable from Safari.** Attaching an image needs a local file put into a hidden `<input type="file">`, and a page script cannot fill a file input. So:

- Posts with images (single image or carousel) → hand them to the **owner** to attach and post by hand, or
- **skip the media** and post text only, if the routine design allows it — and say so in the report.

Never fake an upload or claim the images were attached.

### Step 6 — Post and confirm

```python
    time.sleep(1)
    clicked = page.js("""(() => {
        const d = document.querySelector('div[role=dialog]') || document;
        const b = Array.from(d.querySelectorAll('div[role=button], button'))
                  .find(e => e.innerText.trim() === 'Post' && e.getAttribute('aria-disabled') !== 'true');
        if (!b) return false; b.click(); return true;
    })()""")
    if not clicked:
        raise RuntimeError("Post button missing or disabled (empty/too long text?)")
    for _ in range(30):
        time.sleep(1)
        if not page.js("!!document.querySelector('div[role=dialog] [contenteditable=true]')"):
            break
    else:
        raise RuntimeError("Post not confirmed within 30s — check Threads before retrying (avoid duplicates)")
```

Success = the composer dialog closes (optionally a "Posted" toast / new post in the feed). If it times out, **don't retry blindly** — the post may have gone out; check the profile first.

### Step 7 — Threading (long text)

If `text` >500 chars or `thread=True`:

1. Split text into chunks ≤490 chars, prefer sentence boundaries (`. `, `! `, `? `)
2. Append ` {i}/{n}` counter to each chunk
3. Post the first chunk (Steps 3–6)
4. Open the new post (`safari.open_page(post_url)`), click its "Reply" button via `page.js`
5. Fill and post the next chunk (Steps 4–6)
6. Continue until all chunks posted

### Step 8 — Verify and return

Find the new post's URL on the owner's profile (first `a[href*="/post/"]`):

```python
with safari.open_page("https://www.threads.com/@<handle>", settle=4) as page:
    post_url = page.js("(document.querySelector('a[href*=\"/post/\"]') || {}).href || ''")
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
| `/login` redirect / "Log in" in Safari | Safari not logged into Threads | Notify the owner to log in once in Safari, abort (never type passwords) |
| `SafariError` | Safari not scriptable | Pass the error text to the owner, abort |
| "Action blocked" | Rate limit / spam filter | Stop posting, wait 1h, notify user |
| Composer doesn't open | UI change / slow load | Retry once with 5s wait, then abort |
| Post has images | File inputs can't be filled from JS | Hand to the owner, or post text only if the routine allows |
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

- Threads UI changes frequently — this skill describes the intent; exact selectors may need adjustment. Before clicking/filling, check the element exists with `page.js(...)` (e.g. list `[role=button]` texts) to verify the current structure.
- **NEVER post without explicit approval in the routine design.** Posting is an irreversible public action.
- Images can't be attached from Safari JavaScript — image posts go to the owner (generate them with `Skills/generate-image.md` and send the files along).
- Reference: no existing pipeline posts to Threads yet — this skill is new infrastructure. When a pipeline adopts it, update this file with learnings.
- Related tool documentation: `Tooling.md` ("Web browsing" section) and `scripts/safari.py`
