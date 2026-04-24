---
title: "dashboard-launchagent"
description: "LaunchAgent at `~/Library/LaunchAgents/com.jarvis.dashboard.plist` keeps server alive; always use `launchctl stop/start` to restart"
type: note
created: 2026-04-16
updated: 2026-04-16
tags: [note, auto-extracted, main]
---

[[agent-notes]]

LaunchAgent at `~/Library/LaunchAgents/com.jarvis.dashboard.plist` keeps server alive; always use `launchctl stop/start` to restart

## Update 2026-04-16

Server managed by `~/Library/LaunchAgents/com.jarvis.dashboard.plist` with `KeepAlive: true`; use `launchctl stop/start` for restarts

## Update 2026-04-17

LaunchAgent `com.jarvis.dashboard` manages `server.js` with KeepAlive; use `launchctl stop/start` not manual Node.
