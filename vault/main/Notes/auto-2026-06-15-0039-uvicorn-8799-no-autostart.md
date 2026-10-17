---
title: Uvicorn port 8799 doesn't auto-start after reboot
description: Crypto analysis backend (uvicorn :8799) does not auto-restart on system reboot; requires manual startup.
type: note
created: 2026-06-15
updated: 2026-06-15
tags: [auto, system, startup, uvicorn, crypto-analysis]
---

[[agent-notes]]

The uvicorn process on port 8799 (crypto analysis backend) does not auto-restart after a system reboot. Unlike Claude Bot, PM2 processes, and Ollama (which all come back up automatically), this service requires manual startup.

To start: `(command for uvicorn :8799 — check launchd config or direct startup method)`

**Action:** Consider adding uvicorn to launchd startup config or documented startup routine if this service is critical to daily operation.
