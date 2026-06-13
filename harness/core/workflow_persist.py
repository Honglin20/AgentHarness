"""Workflow persistence — save/load/list_saved + (de)serialization.

Free functions; the ``Workflow`` class methods are thin wrappers around
these. Extracted from ``harness/api.py`` for readability.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from harness.agent import Agent, _extract_description

if TYPE_CHECKING:
    from harness.workflow import Workflow

logger = logging.getLogger(__name__)


def save_workflow(workflow: "Workflow") -> Path:
    """Save workflow definition to ``workflows/<name>/workflow.json``.

    Creates the per-workflow directory plus its ``agents/`` and ``scripts/``
    subdirectories if they don't exist.

    Strict: if any agent still has ``eval=True``, raises
    ``EvalNotCompiledError``. Call ``compile()`` first so EvalJudge
    materializes the judge nodes into the DAG.
    """
    from harness.extensions.eval.errors import EvalNotCompiledError

    uncompiled = [a.name for a in workflow.agents if getattr(a, "eval", False)]
    if uncompiled:
        raise EvalNotCompiledError(
            f"Cannot save workflow '{workflow.name}': agents {uncompiled} have eval=True "
            f"but compile() has not run. Call workflow.compile() before save() so "
            f"EvalJudge can materialize judge nodes into workflow.json."
        )

    workflow.workflow_dir.mkdir(parents=True, exist_ok=True)
    (workflow.workflow_dir / "agents").mkdir(exist_ok=True)
    (workflow.workflow_dir / "scripts").mkdir(exist_ok=True)
    path = workflow.workflow_dir / "workflow.json"
    path.write_text(json.dumps(workflow_to_dict(workflow), indent=2, ensure_ascii=False))
    print(f"[Workflow] saved → {path.resolve()}")
    return path


def load_workflow(name: str, agents_dir: str | None = None) -> "Workflow":
    """Load a saved workflow definition from ``workflows/<name>/workflow.json``.

    Resolution order:
      1. Registry (builtin + project + extra registrations)
      2. Legacy ``_WORKFLOWS_DIR`` fallback

    ``agents_dir`` is retained for back-compat; new layout derives it from
    ``workflows/<name>/agents``.
    """
    # Use _get_workflows_dir() so tests that monkeypatch either
    # harness.api._WORKFLOWS_DIR (legacy) or harness.workflow._WORKFLOWS_DIR
    # (new) both see the override.
    import harness.workflow as _wf_mod
    from harness.registry import get_registry

    try:
        meta = get_registry().resolve_workflow(name)
        wf_dir = meta.resource_dir
    except FileNotFoundError:
        wf_dir = _wf_mod._get_workflows_dir() / name

    path = wf_dir / "workflow.json"
    if not path.exists():
        raise FileNotFoundError(f"Workflow '{name}' not found at {path}")
    data = json.loads(path.read_text())
    return _wf_mod.Workflow.from_dict(data, workflow_dir=wf_dir, agents_dir=agents_dir)


def list_saved_workflows(user_id: str | None = None) -> list[dict]:
    """List all saved workflow definitions with their DAG structure.

    Returns:
        - Shared workflows (from workflows/_shared/workflows/) — always returned
        - Private workflows for the given user — if user_id provided
        - Legacy workflows (from workflows/ root) — only for default user or no user_id

    Args:
        user_id: User ID for filtering private workflows.
                 - None or "default": returns shared + legacy (backward compatibility)
                 - Other values: returns shared + user's private (legacy hidden)
    """
    from harness.compiler.dag_builder import build_dag
    import harness.workflow as _wf_mod

    _WORKFLOWS_DIR = _wf_mod._get_workflows_dir()

    result = []

    def _emit(name: str, agents, scope: str, wf_dir: Path, data: dict, *, description: str | None = None) -> None:
        node_order = build_dag(agents)
        edges = []
        conditional_edges = []
        for a in agents:
            for dep in a.after or []:
                edges.append([dep, a.name])
            if a.on_pass is not None:
                conditional_edges.append({"from": a.name, "to": a.on_pass, "label": "pass"})
            if a.on_fail is not None:
                conditional_edges.append({"from": a.name, "to": a.on_fail, "label": "fail"})
        agent_dicts = [a.to_dict() for a in agents]
        for ad in agent_dicts:
            ad["description"] = _extract_description(ad["name"], wf_dir)
        entry: dict = {
            "name": name,
            "agents": agent_dicts,
            "dag": {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges},
            "workflow_dir": str(wf_dir),
            "scope": scope,
        }
        if description is not None:
            entry["description"] = description
        result.append(entry)

    # 1. Shared workflows
    shared_root = _WORKFLOWS_DIR / "_shared" / "workflows"
    if shared_root.exists():
        for f in sorted(shared_root.glob("*/workflow.json")):
            data = json.loads(f.read_text())
            agents = [Agent.from_dict(a) for a in data.get("agents", [])]
            _emit(data["name"], agents, "shared", f.parent, data)

    # 2. Private workflows (if user_id provided)
    if user_id:
        private_root = _WORKFLOWS_DIR / "users" / user_id / "workflows"
        if private_root.exists():
            for f in sorted(private_root.glob("*/workflow.json")):
                data = json.loads(f.read_text())
                agents = [Agent.from_dict(a) for a in data.get("agents", [])]
                _emit(data["name"], agents, "private", f.parent, data)

    # 3. Legacy workflows (workflows/ root — always included)
    for f in sorted(_WORKFLOWS_DIR.glob("*/workflow.json")):
        if f.parent.name == "_shared":
            continue
        data = json.loads(f.read_text())
        agents = [Agent.from_dict(a) for a in data.get("agents", [])]
        _emit(data["name"], agents, "legacy", f.parent, data)

    # 4. Merge registry resources (project + builtin; deduped against sections 1-3)
    from harness.registry import get_registry
    registry = get_registry()
    existing_names = {r["name"] for r in result}
    for meta in registry.list_workflows():
        if meta.name in existing_names:
            continue
        wf_dir = meta.resource_dir
        wf_json = wf_dir / "workflow.json"
        if not wf_json.exists():
            continue
        try:
            data = json.loads(wf_json.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        agents = [Agent.from_dict(a) for a in data.get("agents", [])]
        _emit(data["name"], agents, meta.scope, wf_dir, data, description=meta.description)

    return result


def workflow_to_dict(workflow: "Workflow") -> dict:
    return {
        "name": workflow.name,
        "agents": [a.to_dict() for a in workflow.agents],
        "max_iterations": workflow.max_iterations,
    }


def workflow_from_dict(
    data: dict,
    workflow_dir: Path | None = None,
    agents_dir: str | None = None,
    checkpointer: object | None = None,
) -> "Workflow":
    import harness.workflow as _wf_mod

    agents = [Agent.from_dict(a) for a in data.get("agents", [])]
    return _wf_mod.Workflow(
        name=data["name"],
        agents=agents,
        workflow_dir=workflow_dir,
        agents_dir=agents_dir,
        checkpointer=checkpointer,
        max_iterations=data.get("max_iterations", 3),
    )
