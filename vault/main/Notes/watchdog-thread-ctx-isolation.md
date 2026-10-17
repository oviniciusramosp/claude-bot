---
title: "watchdog-thread-ctx-isolation"
description: "`_watchdog` runs in its own thread; `self._ctx` (threading.local) is never set there, so chat_id must be captured at spawn time and passed a"
type: note
created: 2026-06-09
updated: 2026-06-09
tags: [note, auto-extracted, main]
---

[[main/Notes/agent-notes|Notes]]

`_watchdog` runs in its own thread; `self._ctx` (threading.local) is never set there, so chat_id must be captured at spawn time and passed as explicit args
