---
title: "oc-telegram-polling-conflict"
description: "Only one process can call Telegram `getUpdates` per bot token; `claude-fallback-bot.py` and OC gateway share the same token, causing 409 err"
type: note
created: 2026-04-16
updated: 2026-04-16
tags: [note, auto-extracted, main]
---

[[agent-notes]]

Only one process can call Telegram `getUpdates` per bot token; `claude-fallback-bot.py` and OC gateway share the same token, causing 409 errors
