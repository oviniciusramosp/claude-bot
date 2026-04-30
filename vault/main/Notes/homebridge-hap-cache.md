---
title: "homebridge-hap-cache"
description: "`/api/accessories` returns `[]` until HAP scan runs; use `/api/accessories/layout` as immediate fallback"
type: note
created: 2026-04-16
updated: 2026-04-16
tags: [note, auto-extracted, main]
---

[[main/Notes/agent-notes|Notes]]
`/api/accessories` returns `[]` until HAP scan runs; use `/api/accessories/layout` as immediate fallback

## Update 2026-04-16

`/api/accessories` returns `[]` until HomeBridge completes HAP scan after a valid SmartThings token is in place

## Update 2026-04-16

`/api/accessories` returns `[]` until HAP scan populates cache; `/api/accessories/layout` always works (metadata only, no live values)

## Update 2026-04-17

`/api/accessories` returns `[]` until HAP scan runs; needs valid SmartThings token to populate.
