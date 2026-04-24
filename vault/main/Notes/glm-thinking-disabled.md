---
title: "glm-thinking-disabled"
description: "Always pass `thinking: {type: "disabled"}` via `extra_body` for glm-5.1 to avoid burning tokens on reasoning_content"
type: note
created: 2026-04-16
updated: 2026-04-16
tags: [note, auto-extracted, main]
---

[[agent-notes]]

Always pass `thinking: {type: "disabled"}` via `extra_body` for glm-5.1 to avoid burning tokens on reasoning_content

## Update 2026-04-17

GLM 5.1 and GLM 4.5-flash reason by default; always pass `{"thinking":{"type":"disabled"}}` via `extra_body` to suppress reasoning_content token burn.

## Update 2026-04-17

Always pass `thinking: {type: "disabled"}` via `extra_body` when using `zai/glm-5.1` to avoid burning tokens on `reasoning_content`

## Update 2026-04-17

Sempre passar `thinking:{type:"disabled"}` via extra_body para GLM 5.1 e glm-4.5-flash
