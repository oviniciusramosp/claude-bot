---
title: macOS /tmp cleanup breaks daemon temporary directories
description: macOS periodically cleans /tmp of empty/inactive directories. Daemons must create temp dirs at write-time (mkdir exist_ok=True), not assume they persist from startup. Bit claude-bot file downloads.
type: lesson
status: recorded
created: 2026-07-20
updated: 2026-07-20
tags: [macos, daemon, temp-directories, file-operations]
---

## The problem

macOS runs periodic cleanup on `/tmp`, removing empty or inactive subdirectories. A daemon that creates temporary directories at startup and expects them to persist will fail when those directories are later cleaned up by the system.

**Where this bit us:** claude-bot created `/tmp/claude-bot-files/` at startup to cache downloaded files. Since downloads were infrequent, the directory remained mostly empty. After macOS cleanup, subsequent file downloads failed with `[Errno 2] No such file or directory` when attempting to write to the now-nonexistent directory.

## Fix

Create temporary directories at write-time, not startup:

```python
output_dir = output_file.parent
output_dir.mkdir(parents=True, exist_ok=True)  # Create at write-time
# ... write file
```

Use `mkdir(exist_ok=True)` to safely handle the case where the directory already exists (idempotent).

## Detect next time

If a daemon's file operations fail with `[Errno 2] No such file or directory` on `/tmp` subdirectories that were supposedly created at startup:
1. Check if the directory still exists: `ls -la /tmp/<dirname>`
2. If it doesn't exist, macOS cleanup is the culprit
3. Refactor to create the directory at write-time instead

**Platform note:** This is specific to macOS. Linux systems typically don't clean `/tmp` as aggressively unless explicitly configured to do so.
