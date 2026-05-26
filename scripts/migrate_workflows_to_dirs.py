"""One-time migration: workflows/*.json + agents/*.md → workflows/<name>/{workflow.json, agents/, scripts/}

Usage:
    python scripts/migrate_workflows_to_dirs.py --dry-run    # preview
    python scripts/migrate_workflows_to_dirs.py              # execute
    python scripts/migrate_workflows_to_dirs.py --root path  # alternate project root

Behavior:
    - For each old workflows/<name>.json:
        * mkdir workflows/<name>/agents and workflows/<name>/scripts
        * copy each referenced agents/<x>.md into workflows/<name>/agents/
          (each workflow gets its own copy — independent evolution after migration)
        * write a new workflow.json without the legacy `agents_dir` field
    - Agents in agents/ not referenced by any workflow → backed up under
      .backup_pre_migration/orphan_agents/
    - Old agents/ directory and old workflows/*.json are MOVED into
      .backup_pre_migration/ (recoverable, not deleted)
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _plan(root: Path) -> tuple[list[Path], dict[str, list[str]], Path, Path, Path]:
    """Inspect root and return the immutable inputs we need to compute actions."""
    old_workflows = sorted((root / "workflows").glob("*.json"))
    old_agents_dir = root / "agents"
    new_root = root / "workflows"
    backup = root / ".backup_pre_migration"

    refs: dict[str, list[str]] = {}
    for wf_json in old_workflows:
        try:
            data = json.loads(wf_json.read_text())
        except json.JSONDecodeError:
            continue
        refs[data.get("name", wf_json.stem)] = [
            a["name"] for a in data.get("agents", []) if "name" in a
        ]
    return old_workflows, refs, old_agents_dir, new_root, backup


def migrate(root: Path, dry_run: bool = False) -> None:
    """Run (or preview) the migration. Idempotent if old layout absent."""
    old_workflows, refs, old_agents_dir, new_root, backup = _plan(root)
    used = {n for names in refs.values() for n in names}

    actions: list[str] = []
    for wf_json in old_workflows:
        try:
            data = json.loads(wf_json.read_text())
        except json.JSONDecodeError:
            actions.append(f"skip {wf_json} (invalid JSON)")
            continue
        wf_name = data.get("name", wf_json.stem)
        wf_dir = new_root / wf_name
        actions.append(f"mkdir {wf_dir}/agents, {wf_dir}/scripts")
        for a in data.get("agents", []):
            src = old_agents_dir / f"{a['name']}.md"
            if src.exists():
                actions.append(f"copy {src} → {wf_dir}/agents/{a['name']}.md")
            else:
                actions.append(f"skip {a['name']} (no MD in agents/)")
        actions.append(f"write {wf_dir}/workflow.json (without agents_dir)")

    if old_agents_dir.exists():
        for md in sorted(old_agents_dir.glob("*.md")):
            if md.stem not in used:
                actions.append(f"move {md} → {backup}/orphan_agents/{md.name}")
        actions.append(f"move {old_agents_dir} → {backup}/agents")
    for wf_json in old_workflows:
        actions.append(f"move {wf_json} → {backup}/workflows/{wf_json.name}")

    if dry_run:
        print("DRY RUN — planned actions:")
        for a in actions:
            print(f"  {a}")
        return

    # --- Execute ---
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "workflows").mkdir(exist_ok=True)
    (backup / "orphan_agents").mkdir(exist_ok=True)

    # 1. New per-workflow directories + copy referenced agents + new workflow.json
    for wf_json in old_workflows:
        try:
            data = json.loads(wf_json.read_text())
        except json.JSONDecodeError:
            print(f"!! Skipping invalid JSON: {wf_json}")
            continue
        wf_name = data.get("name", wf_json.stem)
        wf_dir = new_root / wf_name
        (wf_dir / "agents").mkdir(parents=True, exist_ok=True)
        (wf_dir / "scripts").mkdir(exist_ok=True)
        for a in data.get("agents", []):
            src = old_agents_dir / f"{a['name']}.md"
            if src.exists():
                dst = wf_dir / "agents" / f"{a['name']}.md"
                shutil.copy2(src, dst)
        new_data = {"name": wf_name, "agents": data.get("agents", [])}
        (wf_dir / "workflow.json").write_text(
            json.dumps(new_data, indent=2, ensure_ascii=False)
        )

    # 2. Orphan agents → backup
    if old_agents_dir.exists():
        for md in sorted(old_agents_dir.glob("*.md")):
            if md.stem not in used:
                shutil.move(str(md), backup / "orphan_agents" / md.name)
        # Move the (now possibly only containing referenced .md) directory itself.
        shutil.move(str(old_agents_dir), backup / "agents")

    # 3. Old workflow JSONs → backup
    for wf_json in old_workflows:
        if wf_json.exists():
            shutil.move(str(wf_json), backup / "workflows" / wf_json.name)

    print(f"✓ Migration complete. Originals backed up to {backup}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=".", type=Path)
    args = parser.parse_args()
    migrate(args.root, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
