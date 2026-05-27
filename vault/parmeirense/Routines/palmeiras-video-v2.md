---
title: "Palmeiras Vídeo — Posts do canal oficial (v2)"
description: "Detect new uploads on the official Palmeiras YouTube channel every 30 minutes. Filter out non-event lives, dedup against published_index, pick the most recent fresh video, and publish a Parmeirense-voice post to Telegram with the thumbnail as preview."
type: pipeline
pipeline_version: 2
created: 2026-05-26
updated: 2026-05-26
tags: [pipeline, parmeirense, youtube, video, v2]
schedule:
  times: ["*/30 * * * *"]
  days: ["*"]
model: sonnet
enabled: true
agent: parmeirense
notify: final
context: minimal
---

[[parmeirense/Routines/agent-routines|Routines]]

```pipeline
steps:
  - id: scout
    type: script
    name: "Scout YouTube channel — RSS+PinchTab fetch, live-filter, dedup"
    command: python3 /Users/viniciusramos/claude-bot/vault/parmeirense/Routines/palmeiras-video-v2/scripts/scout.py
    output_file: selected.json
    timeout: 120
    retry: 1

  - id: writer
    type: llm
    name: "Write the Parmeirense post (creative narrative)"
    model: opus
    depends_on: [scout]
    prompt_file: steps/writer.md
    output_file: post.json
    timeout: 420
    inactivity_timeout: 180

  - id: cover
    type: llm
    name: "Visual review of the YouTube thumbnail (single candidate)"
    model: sonnet
    depends_on: [writer]
    prompt_file: steps/cover.md
    output_file: post-reviewed.json
    timeout: 180
    inactivity_timeout: 90

  - id: build-message
    type: script
    name: "Render the Telegram message + record in published_index"
    depends_on: [cover]
    command: python3 /Users/viniciusramos/claude-bot/vault/parmeirense/Routines/palmeiras-video-v2/scripts/build_message.py
    output_file: message.md
    timeout: 60

  - id: notify-telegram
    type: publish
    name: "Send the formatted message to the parmeirense Telegram thread"
    depends_on: [build-message]
    publishes: build-message
    sink: telegram
    sink_config:
      silent: false
```

## Steps

- [[palmeiras-video-v2/steps/scout|scout]]
- [[palmeiras-video-v2/steps/writer|writer]]
- [[palmeiras-video-v2/steps/cover|cover]]

## Scripts (in `palmeiras-video-v2/scripts/`)

- `scout.py` — invokes `scripts/youtube_rss.py` (RSS+PinchTab fallback), applies the live-broadcast filter (keep coletiva/anúncio/apresentação/homenagem; drop other lives), dedupes against the unified `published_index.jsonl` via `topic_key=yt:<video_id>`, and emits the most-recent surviving candidate to `selected.json`. Emits `selected=null` when nothing new — downstream steps see that and emit `NO_REPLY` so the cascade ends silently (no Telegram notification on no-op).
- `build_message.py` — reads `post-reviewed.json`, renders a Telegram-ready markdown message, and records the publish in `vault/parmeirense/.workspace/published-index.jsonl` (topic_key=`yt:<video_id>`) BEFORE the telegram sink runs so message_id can be backfilled later via `published_index.py update-telegram-message-id`.

## Notes

- **Channel ID:** `UCBKc-rPDivvwFiWdG-81wxw` (official Palmeiras).
- **Event-driven:** runs `*/30 * * * *` — most ticks find nothing new and exit silently. `notify: final` + `NO_REPLY` cascade prevents Telegram noise.
- **Dedup:** `topic_key = "yt:<11-char-video-id>"`. Once a video is published, it never re-publishes — even if its RSS entry resurfaces.
- **Live filter:** lives (`is_live_hint=true` in the RSS reader) are dropped UNLESS the title (case+accent insensitive) matches `(coletiva|anuncio|apresentacao|homenagem)`. Regular non-live uploads are always kept.
- **Notion sink:** TODO — videos already live on YouTube so a Notion mirror is lower-value than for news; the publish step currently sends Telegram only. Add a `publish` step with `sink: notion` if a video archive in Notion is wanted later (database id would mirror `palmeiras-feed-v2`'s).
