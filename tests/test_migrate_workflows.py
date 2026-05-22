"""Tests for migrate_workflows_to_dirs — one-time migration script."""

import json
import shutil
from pathlib import Path

from scripts.migrate_workflows_to_dirs import migrate


def _setup_old_layout(root: Path) -> None:
    """Create a project root with the old layout (agents/ + workflows/*.json)."""
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "a.md").write_text("---\nname: a\n---\nA")
    (root / "agents" / "b.md").write_text("---\nname: b\n---\nB")
    (root / "agents" / "orphan.md").write_text("---\nname: orphan\n---\nO")
    (root / "workflows").mkdir()
    (root / "workflows" / "wf1.json").write_text(json.dumps({
        "name": "wf1",
        "agents": [{"name": "a", "after": []}],
    }))
    (root / "workflows" / "wf2.json").write_text(json.dumps({
        "name": "wf2",
        "agents": [{"name": "a", "after": []}, {"name": "b", "after": ["a"]}],
    }))


def test_dry_run_writes_nothing(tmp_path):
    _setup_old_layout(tmp_path)
    snap = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    migrate(root=tmp_path, dry_run=True)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert snap == after


def test_creates_workflow_dirs(tmp_path):
    _setup_old_layout(tmp_path)
    migrate(root=tmp_path, dry_run=False)
    assert (tmp_path / "workflows" / "wf1" / "workflow.json").exists()
    assert (tmp_path / "workflows" / "wf1" / "agents" / "a.md").exists()
    assert (tmp_path / "workflows" / "wf2" / "agents" / "a.md").exists()  # copied
    assert (tmp_path / "workflows" / "wf2" / "agents" / "b.md").exists()
    assert (tmp_path / "workflows" / "wf1" / "scripts").is_dir()
    new_json = json.loads((tmp_path / "workflows" / "wf1" / "workflow.json").read_text())
    assert "agents_dir" not in new_json


def test_orphan_to_backup(tmp_path):
    _setup_old_layout(tmp_path)
    migrate(root=tmp_path, dry_run=False)
    assert (tmp_path / ".backup_pre_migration" / "orphan_agents" / "orphan.md").exists()


def test_originals_backed_up(tmp_path):
    _setup_old_layout(tmp_path)
    migrate(root=tmp_path, dry_run=False)
    assert (tmp_path / ".backup_pre_migration" / "agents" / "a.md").exists()
    assert (tmp_path / ".backup_pre_migration" / "workflows" / "wf1.json").exists()
