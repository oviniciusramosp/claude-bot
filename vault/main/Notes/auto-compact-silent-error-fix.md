---
title: "auto-compact-silent-error-fix"
description: "`_auto_compact._worker()` must call `self.send_message()` on exception, not just `logger.error()` — asymmetry with `cmd_compact` was a bug"
type: note
created: 2026-04-24
updated: 2026-04-24
tags: [note, auto-extracted, main]
---

[[main/Notes/agent-notes|Notes]]
`_auto_compact._worker()` must call `self.send_message()` on exception, not just `logger.error()` — asymmetry with `cmd_compact` was a bug
