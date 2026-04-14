---
paths:
  - "scripts/migrate_vault_per_agent.py"
  - "templates/**"
---

# Migration to v3.1 (flat per-agent layout)

Existing users upgrading from any earlier version (pre-v3 legacy or the v3.0 `Agents/` wrapper) run the same one-shot migration script:

```bash
python3 scripts/migrate_vault_per_agent.py --dry-run   # preview
python3 scripts/migrate_vault_per_agent.py             # live
```

The live run creates a timestamped backup at `vault.backup-YYYYMMDD-HHMMSS/`, auto-detects the starting layout (`legacy`, `v30`, `v31`, or `fresh`), and applies the right transform:

- **legacy**: moves `vault/Skills/*`, `vault/Routines/*`, `vault/Journal/*`, `vault/Reactions/*`, `vault/Lessons/*`, `vault/Notes/*` into `vault/main/`. Routines with `agent: <X>` in frontmatter go to `vault/<X>/Routines/`. Old `Agents/<id>/` wrappers (if present) are unwrapped to `<id>/`.
- **v30**: unwraps `Agents/<id>/` to `<id>/` and merges `agent.md` + `<id>.md` into `agent-<id>.md`.
- **fresh**: seeds `vault/main/` from `templates/main/` (the starter skill/routine set the repo ships).

The script is idempotent: re-running after a successful migration aborts with "vault is already in v3.1 layout". To re-run after a failure, restore from the backup first.
