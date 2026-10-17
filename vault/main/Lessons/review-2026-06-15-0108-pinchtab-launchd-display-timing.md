---
title: PintchTab/Chrome launchd startup fails post-reboot (exit 78)
description: Display session unavailable when launchd starts Chrome CDP; requires delay or wrapper script
type: lesson
status: recorded
created: 2026-06-15
updated: 2026-06-15
tags: [auto, review, pinchtab, launchd, macos, startup]
---

[[agent-lessons]]

## Problem

PintchTab launchd plist fails post-reboot with exit code 78 (display unavailable). The Chrome subprocess can't start because the macOS display session isn't ready yet when launchd tries to spawn it.

## Root cause

launchd runs early in the boot sequence. Chrome CDP tries to initialize the X11/Quartz display server before the user session display is fully online. Result: `exit 78` (display not available).

## Detection next time

- Exit code 78 = display unavailable
- `launchd-stderr.log` or `launchd-stdout.log` will show the exit code
- PintchTab doesn't appear in `ps aux`; port :9869 (Chrome CDP) is unreachable

## Solution

Add delay or wrapper script in the plist:
1. Delay in plist: `<integer>5</integer>` before Chrome spawn (fragile, but simple)
2. Wrapper script: check `launchctl print-disabled gui/$(id -u) | grep -q "com.apple.Aqua"` (display session ready) in a loop before starting Chrome
3. Current workaround: start both PintchTab and Chrome manually via terminal after each reboot

## Notes

- PintchTab server (:9867) is separate from Chrome CDP (:9869) — the server alone starts fine
- Once running manually post-reboot, both stay stable
- Consider adding to bot startup checklist
