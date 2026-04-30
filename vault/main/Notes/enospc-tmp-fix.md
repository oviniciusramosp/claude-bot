---
title: "enospc-tmp-fix"
description: "Claude Code temp output lives in `/private/tmp/claude-501/`; delete it to recover from ENOSPC on `/tmp`"
type: note
created: 2026-04-16
updated: 2026-04-16
tags: [note, auto-extracted, main]
---

[[main/Notes/agent-notes|Notes]]
Claude Code temp output lives in `/private/tmp/claude-501/`; delete it to recover from ENOSPC on `/tmp`

## Update 2026-04-17

When Bash tool fails with ENOSPC, delete `/private/tmp/claude-501/` to restore it.
