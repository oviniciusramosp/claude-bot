---
title: "zai-thinking-disabled"
description: "GLM 5.1 must always receive `{"thinking":{"type":"disabled"}}` via `extra_body` or it burns tokens on reasoning_content."
type: note
created: 2026-04-16
updated: 2026-04-16
tags: [note, auto-extracted, main]
---

[[main/Notes/agent-notes|Notes]]
GLM 5.1 must always receive `{"thinking":{"type":"disabled"}}` via `extra_body` or it burns tokens on reasoning_content.

## Update 2026-04-16

`glm-5.1` must always receive `thinking: {type: "disabled"}` via `extra_body` or it burns tokens on reasoning_content

## Update 2026-04-16

GLM 5.1 and GLM 4.5-flash reason by default; always pass `{"thinking":{"type":"disabled"}}` via `extra_body` to suppress token burn

## Update 2026-04-17

Sempre passar `{"thinking": {"type": "disabled"}}` via `extra_body` para glm-5.1 e glm-4.5-flash
