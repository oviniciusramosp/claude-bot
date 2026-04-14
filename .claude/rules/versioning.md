---
paths:
  - "claude-fallback-bot.py"
  - "claude-bot-menubar.py"
  - "ClaudeBotManager/Sources/App/Info.plist"
---

# Versioning and Commits — claude-bot

## Semantic Versioning

The project follows **[Semantic Versioning 2.0.0](https://semver.org/)** (MAJOR.MINOR.PATCH). The version lives in two places — **always update both together**:

1. `claude-fallback-bot.py`, line `BOT_VERSION = "X.Y.Z"` — with a descriptive comment of the change
2. `ClaudeBotManager/Sources/App/Info.plist`, field `CFBundleShortVersionString`

## When to bump (golden rule)

**Every change that affects bot runtime behavior MUST bump the version.** This includes bug fixes, new commands, prompt changes, constant changes, and refactoring that changes behavior. The version identifies what's running — without a bump, there's no way to distinguish builds.

**DO NOT bump** for purely documentation changes (CLAUDE.md, README, code comments) or vault files (skills, routines, journal) that don't alter bot code.

## How to decide the bump type

| Type | When to use | Examples |
|------|------------|----------|
| **PATCH** (+0.0.1) | Bug fix, behavior adjustment, config/constant change, prompt tweak | fix: timeout correction, adjust `STREAM_EDIT_INTERVAL` |
| **MINOR** (+0.1.0) | New feature, new command, user-visible behavior change, structural refactoring | feat: add `/voice`, new inline keyboard handler |
| **MAJOR** (+1.0.0) | Breaking change — alters `sessions.json` format, changes existing command API incompatibly, architecture redesign | SessionManager redesign, data format migration |

**Practical tip:** If in doubt between PATCH and MINOR, ask: "will the user notice the difference?" If yes → MINOR. If no → PATCH.

## Proactive version bump

**Bump the version IN THE SAME commit as the change** — never in a separate commit. The bump is part of the change, not a separate task.

Mandatory sequence for changes to `claude-fallback-bot.py`:
```bash
# 1. Make the code change
# 2. Bump version in both files (same commit)
# 3. Verify syntax
python3 -m py_compile claude-fallback-bot.py
# 4. Commit everything together
git add claude-fallback-bot.py ClaudeBotManager/Sources/App/Info.plist
git commit -m "feat: add /foo command"
```

## Conventional Commits

Follow **[Conventional Commits](https://www.conventionalcommits.org/)** for commit messages:

| Prefix | Use | Implied bump |
|--------|-----|--------------|
| `feat:` | New feature | MINOR |
| `fix:` | Bug fix | PATCH |
| `refactor:` | Code change without external behavior change | PATCH (if runtime) or none |
| `docs:` | Documentation only | none |
| `chore:` | Maintenance, tooling, configs without runtime impact | none |

The commit prefix **implies** the bump type — `feat:` → MINOR, `fix:` → PATCH. Don't use `chore: bump version` as a standalone commit.

## When to commit

**Commit proactively** after each coherent change — don't accumulate unrelated changes in a single commit.

Commit immediately after:
- Any change to `claude-fallback-bot.py` (with version bump)
- Creating or editing a skill, routine, or agent in the vault
- Changes to CLAUDE.md (root or vault)
- Changes to configuration (`.env`, plist, `settings.local.json`)
