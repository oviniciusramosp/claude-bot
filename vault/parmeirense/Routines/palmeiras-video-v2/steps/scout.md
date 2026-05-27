Mechanical scout step — executed as a `script` type step. The harness
runs `scripts/scout.py` directly; this file is purely informational and
documents the contract for future readers.

INPUT (env vars set by the harness):
  PIPELINE_DATA_DIR          — workspace directory for this run
  PIPELINE_STEP_OUTPUT_FILE  — harness's output tracker

OUTPUT (written by the script):
  $PIPELINE_DATA_DIR/selected.json — JSON with one of two shapes:

      {"selected": null, "reason": "no new videos", "stats": {...}}
      OR
      {
        "selected": {
          "video_id":      "11-char-id",
          "title":         "...",
          "link":          "https://www.youtube.com/watch?v=...",
          "thumbnail_url": "https://i.ytimg.com/vi/.../hqdefault.jpg",
          "description":   "...",
          "published_at":  "ISO-8601"
        },
        "reason": "selected <id> from N fresh candidate(s)",
        "stats":  {...}
      }

LOGIC:
  1. Call scripts/youtube_rss.py fetch --channel-id UCBKc-rPDivvwFiWdG-81wxw
     --fallback-pinchtab. Parse JSONL stdout.
  2. Live-filter: drop entries where is_live_hint=true UNLESS the title
     (case+accent insensitive) matches
     (coletiva|anuncio|apresentacao|homenagem).
  3. Dedup against the unified parmeirense published_index — drop any
     candidate whose topic_key 'yt:<video_id>' already exists.
  4. If nothing remains, emit selected=null. The downstream gate cascade-
     skips writer/cover/publish for this tick (silent on Telegram).
  5. Otherwise pick the most-recent surviving candidate by published_at
     (single selection per 30-min tick).
