---
title: Tooling Preferences
description: Tool preference map by task type. Check before choosing an approach.
type: reference
created: 2026-04-07
updated: 2026-04-09
tags: [reference, tooling]
---

# Tooling Preferences

Which tool to use for each type of task. Check before choosing an approach.

## Web browsing

- **PinchTab** — Web browsing CLI with logged-in sessions (X, Threads). Prefer over urllib to avoid bot fingerprinting.
- Repo/docs: https://github.com/pinchtab/pinchtab
- Default port: `9870`
- Requires `PINCHTAB_ALLOW_EVALUATE=1` for JavaScript form submission (X and other sites)

Commands:
```
pinchtab nav <url> --port 9870       # navigate
pinchtab text --port 9870            # extract text
pinchtab snap -i -c --port 9870      # interactive snapshot
pinchtab click <ref> --port 9870     # click element
pinchtab fill <ref> "text" --port 9870  # fill form field
```
