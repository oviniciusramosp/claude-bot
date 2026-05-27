---
title: Palmeiras Editorial Learn (Weekly)
description: Sunday-night rollup that reads the past week of published posts and user replies, then writes editorial-priorities.md to bias next week's curation. Audience-engagement learning loop.
type: routine
created: 2026-05-26
updated: 2026-05-26
tags: [routine, parmeirense, learning, editorial]
schedule:
  times: ["22:00"]
  days: [sun]
model: opus
enabled: true
context: minimal
---

[[parmeirense/Routines/agent-routines|Routines]]

You are running the weekly editorial learning loop for the Parmeirense agent. The goal is to read what we published in the past 7 days, what user replies came in, and distill a small set of biases that the curation steps of our pipelines will inject into next week's prompts.

This routine is **idempotent**: rerunning it for the same week MUST overwrite `Notes/editorial-priorities.md` with the same content (no append). Work strictly from the data; do not embellish.

## 1. Compute the window

- "Now" is the routine's runtime (Sunday 22:00 BRT).
- `window_end = today (Sunday) 23:59:59 BRT`.
- `window_start = window_end - 7 days + 1 second` (i.e. the previous Monday 00:00 BRT).
- Format both as `YYYY-MM-DD`.

Use bash:

```bash
WEEK_END=$(date +%Y-%m-%d)
WEEK_START=$(date -v-6d +%Y-%m-%d 2>/dev/null || date -d "6 days ago" +%Y-%m-%d)
echo "$WEEK_START to $WEEK_END"
```

## 2. Read published posts in the window

Run:

```bash
python3 ~/claude-bot/scripts/published_index.py query --agent parmeirense --since "$WEEK_START"
```

Output is JSONL — one published post per line. Parse each line. Filter out any line whose `published_at` is after `window_end 23:59:59 BRT` (defensive; in practice all returned lines will be within window since the run is at 22:00 of the end day).

For each post keep: `post_id`, `pipeline`, `published_at`, `topic_key`, `title`, `features`, `cover_image`.

## 3. Read user replies in the window

Read `.workspace/post-replies.jsonl` directly (path: `~/claude-bot/vault/parmeirense/.workspace/post-replies.jsonl`). If the file does not exist, treat as zero replies.

For each line parse the JSON. Keep only replies where `received_at` is between `window_start 00:00 BRT` and `window_end 23:59 BRT` inclusive.

For each reply keep: `post_id`, `reply_text`, `user.username` (or `user.first_name`), `received_at`.

## 4. Join replies onto posts

Build a working table keyed by `post_id`. Each row:

- `post_id`, `pipeline`, `title`, `topic_key`, `features`, `cover_image`
- `reply_count` (int)
- `reply_texts` (list of strings, in chronological order)

Posts with no replies have `reply_count = 0` and `reply_texts = []`. Replies whose `post_id` does not match any published post in the window go into a separate `orphan_replies` bucket (still useful as signal — usually means the reply landed on a post from the previous week).

## 5. Insufficient-signal check (mandatory)

Count: `n_posts = len(working_table)`, `n_substantive_replies = number of replies across all posts whose reply_text has > 20 characters AND is not just an emoji or a one-word reaction like "boa", "show", "top", "ruim", "fraco"`.

**If `n_posts < 5` OR `n_substantive_replies < 3`:**

1. If `Notes/editorial-priorities.md` already exists, leave it untouched. Output via Telegram (see step 7): `"Editorial priorities: insufficient signal this week (N_posts posts, N_replies substantive replies). Kept last week's priorities."`
2. If `Notes/editorial-priorities.md` does NOT exist, write a minimal placeholder (frontmatter + the four section headers each followed by a single `_(insufficient signal this week — N_posts posts, N_replies substantive replies)_` line). Use the frontmatter shape from step 6.
3. In either case, return `NO_REPLY` AFTER calling `telegram_notify.py` (so the harness does not double-post). See step 7.

Do NOT fabricate patterns. The "insufficient signal" fallback exists precisely because early weeks have very little data.

## 6. Pattern analysis (only if signal is sufficient)

Cluster posts into rough categories using the `features` blob and the title — typical categories: tactical analysis, transfer rumor, match recap, refereeing/STJD, club governance, player quote, injury update, base/sub-20, opponent context, off-field/cultural.

For each category compute: `n_posts`, `n_replies`, `avg_reply_chars`, list of representative reply texts (substantive only — > 20 chars).

Identify:

- **What worked (3-6 bullets):** categories or concrete patterns that drew substantive replies. A pattern is something more specific than "transfer news" — it's "transfer news where we named a primary source and avoided 'pode interessar' speculation". Quote one representative reply per bullet (in quotes, attribute by username if not the agent owner).
- **What flopped (2-4 bullets):** posts with zero engagement OR with replies expressing dissatisfaction ("ficou raso", "não gostei", "fraco", "óbvio", "encheu linguiça"). Cite concrete titles or topic clusters.
- **Priorities for next week (3-6 bullets):** actionable bias rules derived from the above. Each rule should be a single declarative imperative — "Favor X when Y", "Deprioritize Z unless W". Keep them concrete and curation-actionable (the consumers are the curation LLM steps of feed-v2, pos-jogo-v2, video-v2).
- **Excluded topics (0-N bullets):** anything the audience explicitly pushed back on this week. Empty list is fine — write `_(none this week)_` if so.

Tone: terse, declarative, English, supporter-aware but editorial (not PT-BR slang). This is editorial guidance, not user-facing copy.

## 7. Write `Notes/editorial-priorities.md`

Overwrite `Notes/editorial-priorities.md` (NOT append — same week rerun must produce same file). Resolve the `created` date as follows: if the file already exists with a `created` field, preserve it; otherwise use today's date.

Frontmatter:

```yaml
---
title: Editorial Priorities (auto-generated)
description: Weekly-refreshed editorial heuristics derived from published-index and post-replies. Injected into the curation prompt of palmeiras-feed-v2, palmeiras-pos-jogo-v2, and palmeiras-video-v2 to bias topic selection toward what the audience engages with.
type: note
created: <preserved or today>
updated: <today YYYY-MM-DD>
tags: [note, parmeirense, editorial, learning, auto-generated]
generated_by: palmeiras-learn-weekly
window: "<WEEK_START> to <WEEK_END>"
---
```

Body sections (in order):

```markdown
## What worked

- ...

## What flopped

- ...

## Priorities for next week

- ...

## Excluded topics

- ...
```

Use the `Write` tool to overwrite the file.

## 8. Notify Telegram and return NO_REPLY

Send a single-line summary via:

```bash
python3 ~/claude-bot/scripts/telegram_notify.py --agent parmeirense --text "Editorial priorities refreshed (<WEEK_START> to <WEEK_END>): <ONE-LINE TAKEAWAY>"
```

Where `<ONE-LINE TAKEAWAY>` is the single most important bias for next week (one sentence, no markdown). For the insufficient-signal branch, use the message from step 5 instead.

Then respond with exactly `NO_REPLY` and nothing else — no preamble, no confirmation, no summary. The Telegram message is the user-visible output; any extra text here would be double-posted.

## Failure handling

- `published_index.py` returns no output or errors: treat as zero posts → insufficient signal branch.
- `post-replies.jsonl` missing or unreadable: treat as zero replies → likely insufficient signal branch.
- `telegram_notify.py` exits non-zero: log the error to stderr but still return `NO_REPLY` (the file write is the primary output; Telegram is best-effort).

## Example Output

```
NO_REPLY
```

(All user-visible content is delivered via `telegram_notify.py`. The file at `Notes/editorial-priorities.md` is consumed by curation steps of other pipelines.)
