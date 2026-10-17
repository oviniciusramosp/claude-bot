---
title: HMAC secrets are server-only
description: HMAC keys must never appear in front-end code; if found in bundles, rotate immediately.
type: note
created: 2026-07-21
updated: 2026-07-21
tags: [auto, security, hmac, architecture]
---

HMAC secrets (keys used to sign and verify authenticity in webhooks, API requests, or widget identity verification) must live exclusively on the backend. If a HMAC key appears in a JavaScript bundle, the key is compromised and must be rotated immediately. The correct pattern: client sends data to server → server signs with the HMAC secret → server returns the signature to the client (never the key itself).
