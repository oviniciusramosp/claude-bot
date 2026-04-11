#!/usr/bin/env python3
"""
migrate_vault_per_agent.py — one-shot vault migration to the v3.1 flat per-agent layout.

## Target layout (v3.1)

    vault/
    ├── README.md
    ├── CLAUDE.md           # universal vault rules (shared)
    ├── Tooling.md          # shared tool preferences
    ├── .graphs/, .obsidian/, Images/, .env
    ├── main/
    │   ├── agent-info.md   # frontmatter: metadata (name, icon, model, …)
    │   │                   # body:        wikilinks to Skills/Routines/Journal/…
    │   ├── CLAUDE.md       # personality / instructions (not a graph node)
    │   ├── Skills/ … Skills.md
    │   ├── Routines/ … Routines.md
    │   ├── Journal/ … Journal.md
    │   ├── Reactions/ … Reactions.md
    │   ├── Lessons/ … Lessons.md
    │   ├── Notes/ … Notes.md
    │   └── .workspace/   # v3.5: dot-prefixed so Obsidian hides it
    ├── crypto-bro/   (same structure, private)
    └── parmeirense/  (same structure, private)

## Source layouts detected

1. **Pre-v3 (legacy)** — flat `vault/Skills/`, `vault/Routines/`, `vault/Journal/`,
   `vault/Notes/`, `vault/Lessons/`, `vault/Reactions/` plus `vault/Agents/<id>/`
   for named agents. Main content lives at the top level.

2. **v3.0 intermediate** — `vault/Agents/<id>/Skills/`, etc., with the Main agent
   already extracted into `vault/Agents/main/`. Hub file is `<id>.md` and
   metadata lives in a separate `agent.md`.

3. **v3.1 (target)** — agents directly at `vault/<id>/` with a unified
   `agent-info.md`. No more wrapper, no more `agent.md`.

The script auto-detects the starting layout and picks the right migration path.

## Guard rails

- Aborts if `vault/` is missing
- Aborts if target `main/` already exists AND contains `agent-info.md` (already
  migrated). Orphan `main/` directories from failed runs are handled gracefully.
- Creates a timestamped backup at `vault.backup-YYYYMMDD-HHMMSS/` first.
- `--dry-run` prints the plan without touching disk.

## Fresh install

When no legacy content is detected, the script seeds `main/` from
`templates/main/` so new users get the same starter skills/routines the repo ships.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from vault_frontmatter import parse_frontmatter  # noqa: E402


SUBDIRS = ("Skills", "Routines", "Journal", "Reactions", "Lessons", "Notes", ".workspace")
# v3.5: pre-v3.5 vaults used "workspace/" as a plain-name directory. We detect
# it during migration and rename to ".workspace/" so Obsidian's dotfile filter
# hides pipeline runtime data from the graph view automatically.
LEGACY_WORKSPACE_NAME = "workspace"
NEW_WORKSPACE_NAME = ".workspace"
# v3.3 sub-index naming: each folder has one `agent-<lowername>.md` index.
INDEX_FOLDERS_WITH_TEMPLATE = ("Skills", "Routines", "Journal", "Reactions", "Lessons", "Notes")
SUB_INDEX_FILENAMES = {
    "Skills":    "agent-skills.md",
    "Routines":  "agent-routines.md",
    "Journal":   "agent-journal.md",
    "Reactions": "agent-reactions.md",
    "Lessons":   "agent-lessons.md",
    "Notes":     "agent-notes.md",
}
SUB_INDEX_FILENAMES_SET = frozenset(SUB_INDEX_FILENAMES.values())
REPO_ROOT = Path(__file__).resolve().parent.parent


def _agent_hub_filename(agent_id: str) -> str:
    """v3.4: per-agent hub file is `agent-<id>.md`, not the legacy `agent-info.md`."""
    return f"agent-{agent_id}.md"


# ---------------------------------------------------------------------------
# File content templates
# ---------------------------------------------------------------------------


def _agent_info_template(agent_id: str, today: str,
                          *, name: Optional[str] = None,
                          description: Optional[str] = None,
                          icon: str = "🤖",
                          model: str = "sonnet",
                          color: str = "grey",
                          default: bool = False,
                          extra_meta: Optional[Dict[str, object]] = None,
                          extra_body: str = "") -> str:
    """Compose an agent-info.md file with metadata in frontmatter and
    path-qualified wikilinks to the per-agent sub-indexes in the body.

    The body uses the v3.3 parent → child convention: agent-info points DOWN
    to its sub-indexes (Skills, Routines, …) plus the agent's CLAUDE.md.
    The links are path-qualified so Obsidian doesn't pick the wrong agent's
    file when multiple agents share the same basename.
    """
    name = name or agent_id
    description = description or f"Index and metadata for the {agent_id} agent."
    meta_lines = [
        "---",
        f"title: {name}",
        f"description: {description}",
        "type: agent",
        f"created: {today}",
        f"updated: {today}",
        "tags: [agent, hub]",
        f"name: {name}",
        f"model: {model}",
        f'icon: "{icon}"',
        f"color: {color}",
        f"default: {'true' if default else 'false'}",
    ]
    if extra_meta:
        for k, v in extra_meta.items():
            if v is None or v == "":
                continue
            if isinstance(v, str) and any(c in v for c in ":#"):
                meta_lines.append(f'{k}: "{v}"')
            else:
                meta_lines.append(f"{k}: {v}")
    meta_lines.append("---")
    body_lines = [
        "",
        f"- [[{agent_id}/Skills/agent-skills|Skills]]",
        f"- [[{agent_id}/Routines/agent-routines|Routines]]",
        f"- [[{agent_id}/Journal/agent-journal|Journal]]",
        f"- [[{agent_id}/Reactions/agent-reactions|Reactions]]",
        f"- [[{agent_id}/Lessons/agent-lessons|Lessons]]",
        f"- [[{agent_id}/Notes/agent-notes|Notes]]",
        "- [[CLAUDE|CLAUDE]]",
        "",
    ]
    body = "\n".join(body_lines)
    if extra_body:
        body += extra_body.rstrip() + "\n"
    return "\n".join(meta_lines) + body


MAIN_CLAUDE_MD_BOOTSTRAP = """\
# Main 🧠

## Personality
Helpful, concise, and grounded. Default voice of the bot when no specialized agent is active.

## Instructions
- Record conversations in the Main journal: `Journal/YYYY-MM-DD.md`
- Read `../Tooling.md` before choosing external tools
- Scan `Lessons/` before similar tasks — previous failures are drafted there
- Use `Skills/` for procedural tasks; `Routines/` for scheduled automation

## Specializations
- General-purpose reasoning, coding assistance, vault maintenance, routine orchestration
"""


# Map: folder → (frontmatter type filter, sort spec). Routines is special
# (two markers — pipelines first, then bare routines).
_INDEX_FILTER_SORT = {
    "Skills":    ("skill",    "title"),
    "Journal":   ("journal",  "-stem"),
    "Reactions": ("reaction", "title"),
    "Lessons":   ("lesson",   "title"),
    "Notes":     ("note",     "title"),
}


def _index_template(folder: str, agent_id: str, today: str) -> str:
    """Per-folder index file (`agent-<lower>.md`) with a vault-query marker.

    v3.3 parent → child convention: the index file lists its children via
    auto-generated wikilinks. It does NOT carry an `[[agent-info]]` parent
    link — the agent-info file points DOWN to this index, not the other way.
    """
    scope = f"{agent_id}/{folder}"
    header = (
        "---\n"
        f"title: {folder}\n"
        f"description: {folder} belonging to the {agent_id} agent.\n"
        "type: index\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"tags: [index, {folder.lower()}]\n"
        "---\n\n"
        f"# {folder} ({agent_id})\n\n"
    )
    if folder == "Routines":
        body = (
            "## Pipelines\n\n"
            '<!-- vault-query:start filter="type=pipeline" '
            f'scope="{scope}" sort="title" '
            'format="- [[{link}|{stem}]] — {description}" -->\n'
            "<!-- vault-query:end -->\n\n"
            "## Routines\n\n"
            '<!-- vault-query:start filter="type=routine" '
            f'scope="{scope}" sort="title" '
            'format="- [[{link}|{stem}]] — {description}" -->\n'
            "<!-- vault-query:end -->\n"
        )
    elif folder in _INDEX_FILTER_SORT:
        tflt, sort = _INDEX_FILTER_SORT[folder]
        body = (
            f'<!-- vault-query:start filter="type={tflt}" '
            f'scope="{scope}" sort="{sort}" '
            'format="- [[{link}|{stem}]] — {description}" -->\n'
            "<!-- vault-query:end -->\n"
        )
    else:
        body = ""
    return header + body


# ---------------------------------------------------------------------------
# Logging helpers
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(f"  ⚠ {msg}", flush=True)


def die(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Low-level filesystem helpers
# ---------------------------------------------------------------------------


def _move(src: Path, dst: Path, dry_run: bool) -> None:
    if dry_run:
        log(f"    move: {src} → {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


def _write_if_missing(path: Path, content: str, dry_run: bool) -> None:
    if path.exists():
        return
    if dry_run:
        log(f"    write:    {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _ensure_subdirs(agent_dir: Path, dry_run: bool) -> None:
    # v3.5: if a legacy plain-name ``workspace/`` directory exists (pre-v3.5
    # installs), rename it to ``.workspace/`` in place so Obsidian's dotfile
    # filter hides pipeline runtime data automatically. If both the legacy
    # and the dot-prefixed dirs exist, merge the legacy contents into the
    # dot-prefixed one and drop the empty legacy folder.
    legacy_ws = agent_dir / LEGACY_WORKSPACE_NAME
    new_ws = agent_dir / NEW_WORKSPACE_NAME
    if legacy_ws.is_dir():
        if new_ws.exists():
            if dry_run:
                log(f"    merge:    {legacy_ws} -> {new_ws}")
            else:
                _move_dir_contents(legacy_ws, new_ws, dry_run=False)
                _remove_empty_dir(legacy_ws, dry_run=False)
        else:
            if dry_run:
                log(f"    rename:   {legacy_ws} -> {new_ws}")
            else:
                legacy_ws.rename(new_ws)

    for sub in SUBDIRS:
        target = agent_dir / sub
        if target.exists():
            continue
        if dry_run:
            log(f"    mkdir:    {target}")
        else:
            target.mkdir(parents=True, exist_ok=True)
    activity = agent_dir / "Journal" / ".activity"
    if not activity.exists():
        if dry_run:
            log(f"    mkdir:    {activity}")
        else:
            activity.mkdir(parents=True, exist_ok=True)


def _move_dir_contents(src: Path, dst: Path, dry_run: bool) -> int:
    if not src.is_dir():
        return 0
    if not dry_run:
        dst.mkdir(parents=True, exist_ok=True)
    moved = 0
    for entry in sorted(src.iterdir()):
        if entry.name == ".gitkeep":
            continue
        target = dst / entry.name
        if target.exists():
            if entry.is_dir() and target.is_dir():
                _move_dir_contents(entry, target, dry_run)
                _remove_empty_dir(entry, dry_run)
                moved += 1
                continue
            warn(f"destination already exists, skipping: {target}")
            continue
        _move(entry, target, dry_run)
        moved += 1
    return moved


def _remove_empty_dir(path: Path, dry_run: bool) -> None:
    if not path.is_dir():
        return
    children = [c for c in path.iterdir() if c.name != ".gitkeep"]
    if children:
        return
    if dry_run:
        log(f"    rmdir:    {path}")
        return
    for c in path.iterdir():
        c.unlink()
    path.rmdir()


def _read_frontmatter(md_path: Path) -> Dict[str, object]:
    try:
        return parse_frontmatter(md_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_agent_field(md_path: Path) -> Optional[str]:
    fm = _read_frontmatter(md_path)
    agent = fm.get("agent")
    if isinstance(agent, str) and agent.strip():
        return agent.strip()
    return None


# ---------------------------------------------------------------------------
# Layout detection
# ---------------------------------------------------------------------------


def _detect_layout(vault_dir: Path) -> str:
    """Return one of: 'v31', 'v35_pending', 'v30', 'legacy', 'fresh'.

    ``legacy`` wins over ``v30`` when both patterns are present: that hybrid
    is what pre-v3 installs look like (top-level Skills/Routines/Journal with
    a few named agents already extracted under Agents/). The legacy path
    handles both at once.

    ``v35_pending`` is the case where the vault is already in the v3.1 flat
    per-agent layout but still has at least one legacy plain-name
    ``<agent>/workspace/`` directory that needs to be renamed to
    ``<agent>/.workspace/`` so Obsidian's dotfile filter hides it.
    """
    v31_agents = [
        p for p in vault_dir.iterdir()
        if p.is_dir()
        and not p.name.startswith(".")
        and (
            (p / _agent_hub_filename(p.name)).is_file()
            or (p / "agent-info.md").is_file()  # v3.1/v3.2 layout pre-rename
        )
    ]
    v30_agents_root = vault_dir / "Agents"
    has_v30 = v30_agents_root.is_dir() and any(
        (v30_agents_root / p.name / "agent.md").is_file()
        for p in v30_agents_root.iterdir()
        if p.is_dir() and not p.name.startswith(".")
    )
    has_legacy = any(
        (vault_dir / folder).is_dir()
        for folder in ("Skills", "Routines", "Journal", "Lessons", "Notes", "Reactions")
    )
    if v31_agents:
        # v3.1 vault — check whether any agent still has a legacy `workspace/`
        # that the v3.5 cleanup-rename must handle.
        for agent in v31_agents:
            if (agent / LEGACY_WORKSPACE_NAME).is_dir():
                return "v35_pending"
        return "v31"
    if has_legacy:
        return "legacy"
    if has_v30:
        return "v30"
    return "fresh"


# ---------------------------------------------------------------------------
# Routine unit enumeration
# ---------------------------------------------------------------------------


def _list_routine_units(routines_dir: Path) -> List[Tuple[Path, Optional[Path]]]:
    if not routines_dir.is_dir():
        return []
    units: List[Tuple[Path, Optional[Path]]] = []
    # Skip both v2 (`Routines.md`) and v3.3 (`agent-routines.md`) index names
    # plus their `.template` siblings.
    skipped_names = {"Routines.md", "Routines.md.template",
                     "agent-routines.md", "agent-routines.md.template"}
    for entry in sorted(routines_dir.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.name in skipped_names:
            continue
        if entry.is_file() and entry.suffix == ".md":
            sidecar = routines_dir / entry.stem
            units.append((entry, sidecar if sidecar.is_dir() else None))
    return units


# ---------------------------------------------------------------------------
# Agent bootstrapping
# ---------------------------------------------------------------------------


def _seed_from_template(template_dir: Path, agent_dir: Path, dry_run: bool) -> None:
    """Copy every file under template_dir into agent_dir, skipping existing files."""
    for src in template_dir.rglob("*"):
        rel = src.relative_to(template_dir)
        dst = agent_dir / rel
        if src.is_dir():
            if dry_run:
                log(f"    mkdir:    {dst}")
            else:
                dst.mkdir(parents=True, exist_ok=True)
            continue
        if dst.exists():
            continue
        if dry_run:
            log(f"    seed:     {rel}")
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _bootstrap_agent(agent_dir: Path, today: str, dry_run: bool,
                      *, is_main: bool = False,
                      existing_metadata: Optional[Dict[str, object]] = None) -> None:
    """Ensure the agent has its `agent-<id>.md` hub, CLAUDE.md, and all sub-index files."""
    _ensure_subdirs(agent_dir, dry_run)
    agent_id = agent_dir.name

    # v3.4: hub file is `<id>/agent-<id>.md`. Drop any legacy `agent-info.md`
    # left over from a previous v3.1/v3.2 install.
    legacy_info = agent_dir / "agent-info.md"
    if legacy_info.is_file() and not dry_run:
        legacy_info.unlink()

    info_path = agent_dir / _agent_hub_filename(agent_id)
    if not info_path.exists():
        meta = dict(existing_metadata or {})
        name = str(meta.pop("name", "") or ("Main" if is_main else agent_id))
        description = str(meta.pop("description", "") or "")
        icon = str(meta.pop("icon", "") or ("🧠" if is_main else "🤖"))
        model = str(meta.pop("model", "") or "sonnet")
        color = str(meta.pop("color", "") or ("grey" if is_main else "blue"))
        default_flag = bool(meta.pop("default", is_main))
        # Drop noisy keys that the template already covers.
        for k in ("title", "type", "created", "updated", "tags"):
            meta.pop(k, None)
        content = _agent_info_template(
            agent_id, today,
            name=name,
            description=description,
            icon=icon,
            model=model,
            color=color,
            default=default_flag,
            extra_meta=meta,
        )
        _write_if_missing(info_path, content, dry_run)

    if is_main:
        _write_if_missing(agent_dir / "CLAUDE.md", MAIN_CLAUDE_MD_BOOTSTRAP, dry_run)

    for sub in INDEX_FOLDERS_WITH_TEMPLATE:
        target = agent_dir / sub / SUB_INDEX_FILENAMES[sub]
        _write_if_missing(target, _index_template(sub, agent_id, today), dry_run)
    # Old layouts may have left legacy index filenames behind. Clean them up
    # so the agent ends up with only the new `agent-<folder>.md` files.
    legacy_index_names = ("Journal.md", "Skills.md", "Routines.md",
                          "Reactions.md", "Lessons.md", "Notes.md")
    for sub in INDEX_FOLDERS_WITH_TEMPLATE:
        for legacy in legacy_index_names:
            stale = agent_dir / sub / legacy
            if stale.is_file() and not dry_run:
                stale.unlink()


# ---------------------------------------------------------------------------
# v3.0 → v3.1: unwrap `Agents/` and merge hub files
# ---------------------------------------------------------------------------


def _merge_v30_agent(agents_dir: Path, vault_dir: Path, agent_id: str,
                      today: str, dry_run: bool) -> None:
    """Move ``Agents/<id>/`` → ``<id>/`` and merge ``agent.md`` + ``<id>.md``
    into a single ``agent-info.md`` at the target path."""
    src_agent = agents_dir / agent_id
    dst_agent = vault_dir / agent_id
    log(f"▶ Unwrapping Agents/{agent_id} → {agent_id}/")

    if dst_agent.exists():
        warn(f"{dst_agent} already exists — skipping unwrap")
        return

    # Read the old metadata + old hub body BEFORE moving (so the merged file
    # can be written with the combined content).
    old_agent_md = src_agent / "agent.md"
    old_hub_md = src_agent / f"{agent_id}.md"
    metadata: Dict[str, object] = {}
    hub_body = ""
    if old_agent_md.is_file():
        metadata = dict(_read_frontmatter(old_agent_md))
    if old_hub_md.is_file():
        try:
            text = old_hub_md.read_text(encoding="utf-8")
        except Exception:
            text = ""
        # Strip any frontmatter the old hub had (duplicates metadata).
        if text.startswith("---"):
            end = text.find("\n---", 3)
            if end != -1:
                text = text[end + 4 :]
        hub_body = text.strip()

    # Move the directory wholesale.
    _move(src_agent, dst_agent, dry_run)

    # Remove the legacy metadata + hub files now that they're inside dst_agent.
    if not dry_run:
        for stray in ("agent.md", f"{agent_id}.md"):
            leftover = dst_agent / stray
            if leftover.is_file():
                leftover.unlink()

    # Write the new agent-info.md with merged metadata + body. The body of
    # agent-info already includes wikilinks to sub-indexes via the template;
    # any non-trivial legacy hub body gets appended below those wikilinks,
    # but we strip its own copies of those wikilinks first to avoid duplicates.
    name = str(metadata.pop("name", "") or metadata.pop("title", "") or agent_id)
    description = str(metadata.pop("description", "") or "")
    icon = str(metadata.pop("icon", "") or "🤖")
    model = str(metadata.pop("model", "") or "sonnet")
    default_flag = bool(metadata.pop("default", agent_id == "main"))
    # `title` is covered by the template's explicit `title: {name}` line — if
    # it stayed in `metadata` the loop below would write a duplicate.
    for k in ("title", "type", "created", "updated", "tags"):
        metadata.pop(k, None)
    # Strip the standard sub-index wikilinks from any legacy hub body to
    # avoid the template prepending another copy of them.
    _stock_links = {
        "[[skills]]", "[[routines]]", "[[journal]]",
        "[[reactions]]", "[[lessons]]", "[[notes]]",
    }
    hub_body = "\n".join(
        line for line in hub_body.splitlines()
        if line.strip().lower() not in _stock_links
    ).strip()
    info_content = _agent_info_template(
        agent_id, today,
        name=name,
        description=description,
        icon=icon,
        model=model,
        default=default_flag,
        extra_meta=metadata,
        extra_body=hub_body,
    )
    _write_if_missing(dst_agent / _agent_hub_filename(agent_id), info_content, dry_run)


# ---------------------------------------------------------------------------
# Legacy (pre-v3) migration
# ---------------------------------------------------------------------------


def _migrate_legacy_main(vault_dir: Path, today: str,
                          dry_run: bool) -> Dict[str, int]:
    """Move vault/Skills, Routines, Journal, etc. into vault/main/."""
    counts = {
        "skills": 0, "routines_main": 0, "routines_agent": 0,
        "journal": 0, "reactions": 0, "lessons": 0, "notes": 0,
    }
    main_dir = vault_dir / "main"
    log("▶ Bootstrapping main/ at vault root")
    if dry_run:
        log(f"    mkdir:    {main_dir}")
    else:
        main_dir.mkdir(parents=True, exist_ok=True)
    _bootstrap_agent(main_dir, today, dry_run, is_main=True)

    simple_moves = [
        ("Skills", "skills"),
        ("Journal", "journal"),
        ("Reactions", "reactions"),
        ("Lessons", "lessons"),
        ("Notes", "notes"),
    ]
    for folder, counter_key in simple_moves:
        src = vault_dir / folder
        if not src.is_dir():
            continue
        log(f"▶ Moving {folder}/ → main/{folder}/")
        # The legacy `<folder>.md` index file is replaced by the v3.3
        # `agent-<folder>.md` template that _bootstrap_agent already wrote.
        # Drop the legacy file before the move so it doesn't pollute.
        legacy_index = src / f"{folder}.md"
        if legacy_index.is_file() and not dry_run:
            legacy_index.unlink()
        counts[counter_key] = _move_dir_contents(src, main_dir / folder, dry_run)
        _remove_empty_dir(src, dry_run)
        log(f"  moved {counts[counter_key]} item(s)")

    routines_src = vault_dir / "Routines"
    if routines_src.is_dir():
        log("▶ Routing Routines/ by agent: frontmatter")
        units = _list_routine_units(routines_src)
        for md_file, sidecar in units:
            agent_id = _read_agent_field(md_file)
            dest_agent = None
            if agent_id and (vault_dir / agent_id).is_dir():
                dest_agent = agent_id
            elif agent_id:
                warn(f"{md_file.name} has `agent: {agent_id}` but <root>/{agent_id}/ missing — routing to main")
            dest_agent = dest_agent or "main"
            dest_dir = vault_dir / dest_agent / "Routines"
            _move(md_file, dest_dir / md_file.name, dry_run)
            if sidecar is not None:
                _move(sidecar, dest_dir / sidecar.name, dry_run)
            if dest_agent == "main":
                counts["routines_main"] += 1
            else:
                counts["routines_agent"] += 1
        # Drop the legacy index file + template — the v3.3 bootstrap already
        # wrote a fresh `agent-routines.md` for every agent.
        for stray in ("Routines.md", "Routines.md.template"):
            path = routines_src / stray
            if path.is_file():
                if dry_run:
                    log(f"    unlink:   {path}")
                else:
                    path.unlink()
        _remove_empty_dir(routines_src, dry_run)

    return counts


# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------


def _list_v30_agents(agents_dir: Path) -> List[str]:
    return sorted(
        p.name for p in agents_dir.iterdir()
        if p.is_dir()
        and not p.name.startswith(".")
        and p.name not in ("Agents.md", "Agents.md.template")
        and (p / "agent.md").is_file()
    )


def migrate_vault(vault_dir: Path, dry_run: bool) -> Dict[str, int]:
    if not vault_dir.is_dir():
        die(f"vault directory not found: {vault_dir}")

    layout = _detect_layout(vault_dir)
    log(f"▶ Vault: {vault_dir}")
    log(f"▶ Mode:  {'DRY RUN' if dry_run else 'LIVE'}")
    log(f"▶ Layout detected: {layout}")
    log("")

    if layout == "v31":
        die(
            "vault is already in v3.1 layout — nothing to migrate. To re-run, "
            "restore from a `vault.backup-*` copy first."
        )

    if layout == "v35_pending":
        log("▶ v3.5 cleanup: renaming legacy `workspace/` → `.workspace/`")
        # Backup first so users can roll back just like a full migration.
        if not dry_run:
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_dir = vault_dir.parent / f"{vault_dir.name}.backup-{ts}"
            log(f"▶ Creating backup → {backup_dir}")
            shutil.copytree(vault_dir, backup_dir, ignore_dangling_symlinks=True)
            log("  ✓ backup complete")
            log("")
        renamed = 0
        for entry in sorted(vault_dir.iterdir()):
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            has_hub = (
                (entry / _agent_hub_filename(entry.name)).is_file()
                or (entry / "agent-info.md").is_file()
            )
            if not has_hub:
                continue
            legacy = entry / LEGACY_WORKSPACE_NAME
            if not legacy.is_dir():
                continue
            new_ws = entry / NEW_WORKSPACE_NAME
            if new_ws.exists():
                if dry_run:
                    log(f"    merge:    {legacy} -> {new_ws}")
                else:
                    _move_dir_contents(legacy, new_ws, dry_run=False)
                    _remove_empty_dir(legacy, dry_run=False)
            else:
                if dry_run:
                    log(f"    rename:   {legacy} -> {new_ws}")
                else:
                    legacy.rename(new_ws)
            renamed += 1
        log(f"▶ Renamed {renamed} agent workspace dir(s)")
        # Regenerate graph since paths changed.
        if not dry_run:
            scripts_dir = Path(__file__).resolve().parent
            graph_script = scripts_dir / "vault-graph-builder.py"
            if graph_script.is_file():
                try:
                    subprocess.run(
                        [sys.executable, str(graph_script), str(vault_dir)],
                        check=False, capture_output=True,
                    )
                except Exception as exc:
                    warn(f"graph regeneration failed: {exc}")
        return {"workspace_renamed": renamed}

    counts: Dict[str, int] = {
        "skills": 0, "routines_main": 0, "routines_agent": 0,
        "journal": 0, "reactions": 0, "lessons": 0, "notes": 0,
        "v30_agents_unwrapped": 0,
    }
    today = datetime.now().strftime("%Y-%m-%d")

    if not dry_run:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = vault_dir.parent / f"{vault_dir.name}.backup-{ts}"
        log(f"▶ Creating backup → {backup_dir}")
        shutil.copytree(vault_dir, backup_dir, ignore_dangling_symlinks=True)
        log("  ✓ backup complete")
        log("")

    if layout == "fresh":
        log("▶ Fresh install: seeding main/ from templates/main/")
        main_dir = vault_dir / "main"
        if dry_run:
            log(f"    mkdir:    {main_dir}")
        else:
            main_dir.mkdir(parents=True, exist_ok=True)
        template_dir = REPO_ROOT / "templates" / "main"
        if template_dir.is_dir():
            _seed_from_template(template_dir, main_dir, dry_run)
        _bootstrap_agent(main_dir, today, dry_run, is_main=True)

    elif layout == "legacy":
        # Pre-v3: top-level Skills/Routines/Journal/ etc. + optional Agents/<id>/
        agents_dir = vault_dir / "Agents"
        if agents_dir.is_dir():
            for agent_id in _list_v30_agents(agents_dir):
                _merge_v30_agent(agents_dir, vault_dir, agent_id, today, dry_run)
                counts["v30_agents_unwrapped"] += 1
                log("")
            # Clean up leftover Agents/ scaffolding (index file, templates).
            for stray in ("Agents.md", "Agents.md.template", ".gitkeep"):
                p = agents_dir / stray
                if p.is_file():
                    if dry_run:
                        log(f"    unlink:   {p}")
                    else:
                        p.unlink()
            _remove_empty_dir(agents_dir, dry_run)

        legacy_counts = _migrate_legacy_main(vault_dir, today, dry_run)
        counts.update(legacy_counts)
        log("")

    elif layout == "v30":
        # All content already under Agents/<id>/ — just unwrap + merge hubs.
        agents_dir = vault_dir / "Agents"
        for agent_id in _list_v30_agents(agents_dir):
            _merge_v30_agent(agents_dir, vault_dir, agent_id, today, dry_run)
            counts["v30_agents_unwrapped"] += 1
            log("")
        # If Main wasn't in Agents/ (edge case), bootstrap a fresh one.
        main_dir = vault_dir / "main"
        if not main_dir.exists():
            warn("Agents/main/ was missing — bootstrapping fresh main/")
            if dry_run:
                log(f"    mkdir:    {main_dir}")
            else:
                main_dir.mkdir(parents=True, exist_ok=True)
            template_dir = REPO_ROOT / "templates" / "main"
            if template_dir.is_dir():
                _seed_from_template(template_dir, main_dir, dry_run)
            _bootstrap_agent(main_dir, today, dry_run, is_main=True)
        # Cleanup leftover Agents/ scaffolding.
        for stray in ("Agents.md", "Agents.md.template", ".gitkeep"):
            p = agents_dir / stray
            if p.is_file():
                if dry_run:
                    log(f"    unlink:   {p}")
                else:
                    p.unlink()
        _remove_empty_dir(agents_dir, dry_run)

    # Final bootstrap pass to guarantee every agent has the required scaffolding.
    for entry in sorted(vault_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if entry.name in ("Agents", "Images", "__pycache__"):
            continue
        # An agent dir has either the new `agent-<id>.md` hub or the legacy
        # `agent-info.md` (which `_bootstrap_agent` will rename).
        has_new = (entry / _agent_hub_filename(entry.name)).is_file()
        has_legacy = (entry / "agent-info.md").is_file()
        if not (has_new or has_legacy):
            continue
        _bootstrap_agent(entry, today, dry_run, is_main=(entry.name == "main"))

    # Regenerate indexes + graph (best effort).
    if not dry_run:
        scripts_dir = Path(__file__).resolve().parent
        for script, label in (
            ("vault_indexes.py", "vault indexes"),
            ("vault-graph-builder.py", "vault graph"),
        ):
            path = scripts_dir / script
            if not path.is_file():
                continue
            log(f"▶ Regenerating {label} via {script}")
            try:
                subprocess.run(
                    [sys.executable, str(path), "--vault", str(vault_dir)],
                    check=True,
                )
            except subprocess.CalledProcessError as exc:
                warn(f"{script} exited with code {exc.returncode}")
            except Exception as exc:  # noqa: BLE001
                warn(f"{script} failed to run: {exc}")
        log("")

    log("▶ Summary")
    log(f"  Skills moved to main:     {counts['skills']}")
    log(f"  Routines moved to main:   {counts['routines_main']}")
    log(f"  Routines moved to agent:  {counts['routines_agent']}")
    log(f"  Journal files moved:      {counts['journal']}")
    log(f"  Reactions moved:          {counts['reactions']}")
    log(f"  Lessons moved:            {counts['lessons']}")
    log(f"  Notes moved:              {counts['notes']}")
    log(f"  v3.0 agents unwrapped:    {counts['v30_agents_unwrapped']}")
    log("")
    if dry_run:
        log("✓ Dry run complete. Re-run without --dry-run to apply.")
    else:
        log("✓ Migration complete.")
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate the vault to the v3.1 flat per-agent layout."
    )
    parser.add_argument(
        "--vault",
        default=str(REPO_ROOT / "vault"),
        help="Path to the vault directory (default: <repo>/vault)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan without touching disk (no backup created).",
    )
    args = parser.parse_args()
    migrate_vault(Path(args.vault).resolve(), args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
