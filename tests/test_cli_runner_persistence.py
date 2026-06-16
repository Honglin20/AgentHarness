"""Tests for ``harness.cli_runner`` — the persistence wrapper that lets
``harness run`` write run records to the same location the server uses,
so the frontend ``GET /api/runs`` discovers CLI-run history.

The contract being locked:
  1. After ``run_with_persistence`` returns, ``runs/{run_id}.json`` exists
     with the fields the frontend needs (run_id, workflow_name, status,
     agents_snapshot, created_at, etc.).
  2. ``RunStore.list_runs()`` (called by server's GET /api/runs) finds it.
  3. ``RunStore.get_events(run_id)`` returns the captured event stream.
  4. A failed workflow run still produces a record with status="failed".

If any of these break, the "frontend can replay CLI history" guarantee
breaks silently — that's why each is a separate test.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def temp_runs_dir(tmp_path, monkeypatch):
    """Redirect HARNESS_RUNS_DIR to an isolated temp dir.

    RunStore caches the directory in TWO places: (1) the module-level
    ``_DEFAULT_RUNS_DIR`` resolved at import time (env-var changes after
    import are silently ignored), and (2) the ``_run_store_singleton``
    that holds a RunStore constructed against that default at first
    ``get_run_store()`` call. Both must be reset, or one test's
    CWD-relative default leaks into the next test's env-var override
    and writes pollute the real ``CWD/runs/``.
    """
    runs_dir = tmp_path / "runs"
    monkeypatch.setenv("HARNESS_RUNS_DIR", str(runs_dir))
    import harness.persistence.run_store as rs_mod
    rs_mod._run_store_singleton = None
    monkeypatch.setattr(rs_mod, "_DEFAULT_RUNS_DIR", runs_dir)
    yield runs_dir
    rs_mod._run_store_singleton = None


def _make_minimal_workflow(tmp_path: Path):
    """Build a Workflow with one agent and no MCP servers.

    We don't run the agent's LLM — the test mocks ``Workflow.arun`` — so
    the workflow doesn't need a real MD file or model. The persistence
    wrapper is what's under test, not LangGraph execution.
    """
    from harness.core.agent import Agent
    from harness.core.workflow import Workflow

    wf_dir = tmp_path / "wf"
    (wf_dir / "agents").mkdir(parents=True)
    (wf_dir / "agents" / "alpha.md").write_text(
        "---\nname: alpha\n---\n\nYou are a test agent.\n",
        encoding="utf-8",
    )
    return Workflow(
        name="test_wf",
        agents=[Agent(name="alpha", after=[])],
        workflow_dir=wf_dir,
        enable_filesystem_mcp=False,
        enable_codegraph_mcp=False,
    )


# ---------------------------------------------------------------------------
# Persistence wrapper — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_persistence_writes_run_record(temp_runs_dir, tmp_path):
    """CLI run writes runs/{run_id}.json with the minimum fields the
    frontend needs to list and replay."""
    from harness.cli_runner import run_with_persistence

    wf = _make_minimal_workflow(tmp_path)

    fake_result = MagicMock()
    fake_result.outputs = {"alpha": {"summary": "done"}}
    fake_result.errors = {}
    fake_result.trace = []

    with (
        patch.object(wf, "arun", new=AsyncMock(return_value=fake_result)),
        patch.object(wf, "setup", new=AsyncMock()),
        patch.object(wf, "cleanup", new=AsyncMock()),
    ):
        run_id, result = await run_with_persistence(
            wf, inputs={"task": "test"}, output_hook=None,
        )

    record_path = temp_runs_dir / f"{run_id}.json"
    assert record_path.exists(), f"Run record not written: {record_path}"

    record = json.loads(record_path.read_text())
    assert record["run_id"] == run_id
    assert record["workflow_name"] == "test_wf"
    assert record["status"] == "completed"
    assert record["inputs"] == {"task": "test"}
    assert "agents_snapshot" in record
    assert "created_at" in record
    assert isinstance(record["agents_snapshot"], list)
    # The agent that ran must be in the snapshot for frontend replay.
    assert any(a["name"] == "alpha" for a in record["agents_snapshot"])


@pytest.mark.asyncio
async def test_run_record_discoverable_by_server(temp_runs_dir, tmp_path):
    """After CLI writes a record, ``RunStore.list_runs()`` (the function
    server's GET /api/runs calls) must find it. This is THE test that
    locks the "frontend can replay CLI history" contract.
    """
    from harness.cli_runner import run_with_persistence
    from harness.run_store import get_run_store

    wf = _make_minimal_workflow(tmp_path)

    fake_result = MagicMock()
    fake_result.outputs = {}
    fake_result.errors = {}
    fake_result.trace = []

    with (
        patch.object(wf, "arun", new=AsyncMock(return_value=fake_result)),
        patch.object(wf, "setup", new=AsyncMock()),
        patch.object(wf, "cleanup", new=AsyncMock()),
    ):
        run_id, _ = await run_with_persistence(wf, inputs={"task": "x"})

    store = get_run_store()
    result = store.list_runs(summary_only=True)
    # list_runs returns {"runs": [...], "total": int, "has_more": bool}
    # (summary_only path) — server's GET /api/runs unwraps this for the
    # frontend. Test against the wrapped shape so we don't drift from the
    # actual contract.
    runs = result["runs"] if isinstance(result, dict) else result
    run_ids = [r["run_id"] for r in runs]
    assert run_id in run_ids, (
        f"CLI run {run_id} not discoverable by RunStore.list_runs; "
        f"server's GET /api/runs would not show it."
    )


@pytest.mark.asyncio
async def test_run_record_events_replayable(temp_runs_dir, tmp_path):
    """``RunStore.get_events(run_id)`` returns the captured event stream —
    without this, frontend replay shows nothing."""
    from harness.cli_runner import run_with_persistence
    from harness.run_store import get_run_store

    wf = _make_minimal_workflow(tmp_path)

    fake_result = MagicMock()
    fake_result.outputs = {}
    fake_result.errors = {}
    fake_result.trace = []

    with (
        patch.object(wf, "arun", new=AsyncMock(return_value=fake_result)),
        patch.object(wf, "setup", new=AsyncMock()),
        patch.object(wf, "cleanup", new=AsyncMock()),
    ):
        # Bypass workflow.arun's emit by injecting events directly into the
        # bus before the persistence layer collects. The wrapper must
        # preserve them.
        original_arun = wf.arun

        async def fake_arun(*args, **kwargs):
            wf._event_bus.emit("workflow.started", {
                "workflow_id": "fake", "name": "test_wf",
            })
            wf._event_bus.emit("workflow.completed", {
                "workflow_id": "fake", "outputs": {},
            })
            return await original_arun(*args, **kwargs)

        # Replace with a simpler version — original_arun is itself mocked,
        # so just emit events and return the fake result directly.
        async def emitting_arun(*args, **kwargs):
            wf._event_bus.emit("workflow.started", {
                "workflow_id": "fake", "name": "test_wf",
            })
            wf._event_bus.emit("workflow.completed", {
                "workflow_id": "fake", "outputs": {},
            })
            return fake_result

        with patch.object(wf, "arun", new=AsyncMock(side_effect=emitting_arun)):
            run_id, _ = await run_with_persistence(wf, inputs={"task": "x"})

    store = get_run_store()
    events = store.get_events(run_id)
    assert isinstance(events, list)
    assert len(events) >= 2, f"Expected captured events, got {len(events)}"
    event_types = [e.get("type") for e in events]
    assert "workflow.started" in event_types
    assert "workflow.completed" in event_types


# ---------------------------------------------------------------------------
# Failure path — record still written so failed runs are visible
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_run_writes_failed_record(temp_runs_dir, tmp_path):
    """When workflow.arun raises, a record with status='failed' must still
    be written so the user can see the failure in the history list."""
    from harness.cli_runner import run_with_persistence

    wf = _make_minimal_workflow(tmp_path)

    with (
        patch.object(wf, "arun", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch.object(wf, "setup", new=AsyncMock()),
        patch.object(wf, "cleanup", new=AsyncMock()),
    ):
        # The wrapper re-raises after persisting — caller decides exit code.
        with pytest.raises(RuntimeError, match="boom"):
            await run_with_persistence(wf, inputs={"task": "x"})

    records = list(temp_runs_dir.glob("*.json"))
    # Filter out sidecar files (*.json matches both main record and sidecars
    # like {run_id}+events.json — main record has no + in the name).
    main_records = [p for p in records if "+" not in p.name]
    assert len(main_records) == 1, f"Expected 1 main record, got {main_records}"

    record = json.loads(main_records[0].read_text())
    assert record["status"] == "failed"
    assert record["workflow_name"] == "test_wf"


# ---------------------------------------------------------------------------
# workflow_id / thread_id wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_with_persistence_passes_thread_id_to_arun(temp_runs_dir, tmp_path):
    """The generated run_id must flow into LangGraph's thread_id via config
    so checkpointer state is unique per CLI run, not shared across runs of
    the same workflow name."""
    from harness.cli_runner import run_with_persistence

    wf = _make_minimal_workflow(tmp_path)

    fake_result = MagicMock()
    fake_result.outputs = {}
    fake_result.errors = {}
    fake_result.trace = []

    captured_config = {}

    async def capturing_arun(inputs, config=None, **kwargs):
        captured_config["config"] = config
        return fake_result

    with (
        patch.object(wf, "arun", new=capturing_arun),
        patch.object(wf, "setup", new=AsyncMock()),
        patch.object(wf, "cleanup", new=AsyncMock()),
    ):
        run_id, _ = await run_with_persistence(wf, inputs={})

    config = captured_config["config"]
    assert config is not None, "arun was called without config"
    assert config["configurable"]["thread_id"] == run_id, (
        "thread_id must equal run_id so checkpoint state is per-run"
    )
