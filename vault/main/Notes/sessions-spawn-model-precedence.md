---
title: "sessions-spawn-model-precedence"
description: "spawn-level model > cron payload model > agent model > agents.defaults — most granular wins"
type: note
created: 2026-04-16
updated: 2026-04-16
tags: [note, auto-extracted, main]
---

[[main/Notes/agent-notes|Notes]]
spawn-level model > cron payload model > agent model > agents.defaults — most granular wins

## Update 2026-04-16

Model declared in sessions_spawn overrides cron payload and agent config defaults in OpenClaw.

## Update 2026-04-17

sessions_spawn model > cron payload model > agent config model > agents.defaults
