---
paths:
  - "ClaudeBotManager/**/*.swift"
  - "ClaudeBotManager/**/*.plist"
  - "ClaudeBotManager/build-app.sh"
  - "ClaudeBotManager/Package.swift"
---

# ClaudeBotManager — macOS app

Native macOS app (SwiftUI) in `ClaudeBotManager/`. Menu bar app for managing the bot:
- Dashboard with bot status and sessions
- Agent, routine, and skill management (redesigned UI v2.3)
- Pipeline creation and editing with expandable step editor
- Delete via macOS Trash (recoverable from Finder)
- Minimal context toggle for routines
- Settings editing (.env)
- Log viewer with filters and search

## Build and deploy

The app is distributed as an `.app` bundle (required to preserve macOS permissions between builds):

```bash
# Build + assemble .app + restart — normal usage
cd ClaudeBotManager && bash build-app.sh
```

The `build-app.sh` script:
1. Compiles with `swift build -c release` using Xcode 26 toolchain
2. Assembles `ClaudeBotManager.app/Contents/` with the binary and `Info.plist`
3. Signs with ad-hoc identity (`codesign --sign -`)
4. Kills the previous process and opens the new bundle

**Why .app bundle?** Without a bundle, macOS has no stable identity (`Info.plist=not bound`) and asks for permissions (TCC) on every new build. With the bundle, permissions are bound to `CFBundleIdentifier=com.claudebot.manager`.

The `.app` is generated at `ClaudeBotManager/ClaudeBotManager.app` (gitignored — build artifact).

## Design System (LiquidGlassTheme.swift)

Shared components:

| Component | Description |
|-----------|-------------|
| `GlassCard` | Main container with `.ultraThinMaterial` + 0.5pt border |
| `SectionCard` | GlassCard with header (title + SF Symbol) |
| `SettingRow` | `.callout` label + right-aligned control |
| `ModelBadge` | Color-coded badge by model (opus=purple, haiku=green, others=blue) |
| `StatusDot` | Circle with pulse animation when `isRunning` |
| `UsageBar` | Progress bar colored by percentage |
| `EmptyStateView` | Centered empty state with 48pt icon |
| `FlowLayout` | Wrapping layout for chips and pipeline dependencies |

Spacing scale: `Spacing.xs(4) sm(8) md(12) lg(16) xl(20) xxl(24)`

## Sidebar

Collapsible. Grouped in 3 sections:
- **Overview** — Dashboard
- **Manage** — Agents, Routines, Skills
- **System** — Sessions, Logs, Settings, Changelog

Each item shows a badge with count (Agents, Routines, Skills) or status (Dashboard: "Running", Logs: "⚠ N"). Changelog shows the version (vX.Y.Z).

## Agents

The **Main Agent** is the bot's default agent (no own workspace). It counts as an agent in sidebar counts and Dashboard stat chips. Total agent count is always `appState.agents.count + 1` (custom agents + Main).

## Version bump

**Changes to ClaudeBotManager Swift code require a version bump** in both places (same commit):
1. `claude-fallback-bot.py`, `BOT_VERSION = "X.Y.Z"`
2. `ClaudeBotManager/Sources/App/Info.plist`, `CFBundleShortVersionString`

See the main CLAUDE.md "Versioning and Commits" section for the full rules.
