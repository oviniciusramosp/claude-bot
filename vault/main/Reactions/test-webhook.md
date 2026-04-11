---
title: Test Webhook
description: Simple test reaction that forwards payloads to Telegram
type: reaction
created: 2026-04-10
updated: 2026-04-10
tags: [reaction, test]
enabled: true
auth:
  mode: token
action:
  forward: true
  forward_template: |
    🧪 Test webhook received!
    Message: {{message}}
    Timestamp: {{timestamp}}
---


Simple webhook test — forwards any POST payload to the default Telegram chat.
Use this to validate the full stack: Tailscale Funnel → webhook server → Telegram.
