---
title: "telegram-polling-exclusivity"
description: "Only one process can call `getUpdates` per bot token; concurrent pollers cause 409 Conflict"
type: note
created: 2026-04-16
updated: 2026-04-16
tags: [note, auto-extracted, main]
---

[[main/Notes/agent-notes|Notes]]
Only one process can call `getUpdates` per bot token; concurrent pollers cause 409 Conflict

## Update 2026-04-16

Only one process can call Telegram getUpdates per bot token; concurrent pollers cause 409 Conflict
