---
title: "hermes-threat-patterns"
description: "NousResearch/hermes-agent `tools/threat_patterns.py` has 100+ regex patterns (prompt injection, role hijack, C2/exfiltration) worth porting;"
type: note
created: 2026-06-02
updated: 2026-06-02
tags: [note, auto-extracted, main]
---

[[main/Notes/agent-notes|Notes]]

NousResearch/hermes-agent `tools/threat_patterns.py` has 100+ regex patterns (prompt injection, role hijack, C2/exfiltration) worth porting; integration point is `_handle_text` gated on secondary chats
