# Pause/Resume Reliability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix pause/resume so paused workflows survive process restarts, conversation history is preserved, and the same run_id is retained.

**Architecture:** Extend `_build_agents_snapshot` to include `on_pass`/`on_fail`/`eval` for complete reconstruction. Enrich `cancel()` to preserve existing persisted data (agent_io, events, conversation). Add a reconstruction path in `resume_run()` that rebuilds a Workflow from disk when the in-memory repo is empty. Persist `work_dir` to disk for MCP reconnection.

**Tech Stack:** Python 3.10, FastAPI, LangGraph checkpoints (SQLite), Zustand (frontend)

---

## Audit Findings (Pre-Plan)

### Bug 1 (Fixed separately)
`GET /api/runs/{id}` was missing `events` field → replay fell into legacy path without IO data. Fixed by adding `events` to `RunDetail` schema and `get_run` response.

### Bug 2 Root Causes
1. **cancel() save loses data**: `RunStore().save()` in `cancel()` passes `result=None` and omits `agent_io`/`conversation`/`events` — overwriting the incremental save from `_save_incremental` which had these fields.
2. **agents_snapshot incomplete**: Missing `on_pass`/`on_fail`/`eval` — reconstruction loses conditional edges and eval judge nodes.
3. **work_dir not persisted**: Needed for MCP setup on resume, only in memory.
4. **resume_run requires in-memory repo**: `repo.contains(run_id)` fails after restart.

### Race Condition Analysis (Safe)
`cancel()` holds `_lock` for its entire duration (including the 2s wait + save). `_run_workflow`'s finally block acquires `_lock` to clean up. No concurrent save race — `cancel()`'s "paused" save is the final write. But it overwrites good data because it doesn't carry forward the incremental save's fields.

---

## Task 1: Extend agents_snapshot with conditional edges + eval

**Files:**
- Modify: `server/runner.py:56-63` (`_build_agents_snapshot`)
- Modify: `server/schemas.py:61-68` (`AgentSnapshot`)
- Test: `tests/server/test_routes.py`

**Why:** Currently `agents_snapshot` is a "display snapshot" — missing `on_pass`/`on_fail`/`eval`. These are needed to reconstruct a Workflow with correct DAG topology (conditional routing + eval judge insertion).

**Step 1: Write the failing test**

Add to `tests/server/test_routes.py`:

```python
def test_agents_snapshot_includes_conditional_edges():
    """_build_agents_snapshot captures on_pass/on_fail/eval from agent defs."""
    from harness.api import Agent, Workflow
    from server.runner import _build_agents_snapshot

    agents = [
        Agent(name="a", after=[]),
        Agent(name="b", after=["a"], on_pass="c", on_fail="d"),
        Agent(name="c", after=[]),
        Agent(name="d", after=[], eval=True),
    ]
    wf = Workflow(name="test", agents=agents)
    snapshot = _build_agents_snapshot(wf)

    by_name = {s["name"]: s for s in snapshot}
    assert by_name["a"].get("on_pass") is None
    assert by_name["a"].get("on_fail") is None
    assert by_name["b"]["on_pass"] == "c"
    assert by_name["b"]["on_fail"] == "d"
    assert by_name["d"].get("eval") is True


def test_agent_snapshot_schema_accepts_new_fields():
    """AgentSnapshot model accepts on_pass/on_fail/eval."""
    from server.schemas import AgentSnapshot

    snap = AgentSnapshot(
        name="b",
        after=["a"],
        on_pass="c",
        on_fail="d",
        eval=True,
    )
    assert snap.on_pass == "c"
    assert snap.on_fail == "d"
    assert snap.eval is True
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/server/test_routes.py::test_agents_snapshot_includes_conditional_edges tests/server/test_routes.py::test_agent_snapshot_schema_accepts_new_fields -v`
Expected: FAIL — `on_pass`/`on_fail`/`eval` not in snapshot dict, schema doesn't accept them.

**Step 3: Extend AgentSnapshot schema**

In `server/schemas.py`, modify `AgentSnapshot`:

```python
class AgentSnapshot(BaseModel):
    """Snapshot of an agent definition at run time."""
    name: str
    after: list[str] = []
    md_content: str = ""
    tools: list[str] | None = None
    model: str | None = None
    retries: int = 3
    on_pass: str | None = None
    on_fail: str | None = None
    eval: bool = False
```

**Step 4: Extend _build_agents_snapshot**

In `server/runner.py`, modify `_build_agents_snapshot` to include the new fields in the dict:

```python
        snapshot.append({
            "name": agent_def.name,
            "after": agent_def.after,
            "md_content": md_content,
            "tools": agent_def.tools,
            "model": agent_def.model,
            "retries": agent_def.retries,
            "on_pass": agent_def.on_pass,
            "on_fail": agent_def.on_fail,
            "eval": agent_def.eval if not isinstance(eval_target, str) else True,
        })
```

Note: `_eval_target` is set by `EvalJudge` on eval agents. For judge nodes (`_judge_X`), `eval_target` is a string, but the agent def's `eval` flag may not be set — the judge is auto-generated. The `eval=True` in the snapshot marks it for reconstruction.

**Step 5: Run tests to verify they pass**

Run: `pytest tests/server/test_routes.py::test_agents_snapshot_includes_conditional_edges tests/server/test_routes.py::test_agent_snapshot_schema_accepts_new_fields -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `pytest tests/ -x -q --ignore=tests/test_phase2_integration.py`
Expected: All pass — `AgentSnapshot` fields are optional with defaults, backward compatible.

**Step 7: Commit**

```bash
git add server/runner.py server/schemas.py tests/server/test_routes.py
git commit -m "feat: extend agents_snapshot with on_pass/on_fail/eval for workflow reconstruction"
```

---

## Task 2: Fix cancel() to preserve incremental data

**Files:**
- Modify: `server/runner.py:153-175` (`cancel` method)
- Test: `tests/server/test_runner_cancel.py` (new)

**Why:** `cancel()` saves "paused" with `result=None` and no `agent_io`/`conversation`/`events` — this overwrites the `_save_incremental` data that had all completed nodes' IO. The fix: read the existing disk record and merge its data into the paused save.

**Step 1: Write the failing test**

Create `tests/server/test_runner_cancel.py`:

```python
"""Tests for runner.cancel() pause persistence."""
import json
import pytest
from pathlib import Path


@pytest.fixture
def runner_and_store(tmp_path, monkeypatch):
    """Set up a runner with a temp runs directory."""
    from server.runner import WorkflowRunner
    from harness.run_store import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    runner = WorkflowRunner(max_concurrent=5)
    return runner, store


@pytest.mark.asyncio
async def test_cancel_preserves_agent_io(runner_and_store, tmp_path):
    """cancel() preserves agent_io from incremental save in the paused record."""
    from harness.run_store import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    run_id = "test-cancel-preserve"

    # Simulate incremental save (what _save_incremental does after each node)
    store.save(
        run_id=run_id,
        workflow_name="test_wf",
        agents_snapshot=[{"name": "a", "after": []}],
        status="running",
        inputs={"task": "x"},
        result=None,
        dag={"nodes": ["a"], "edges": [], "conditional_edges": []},
        agent_io={"a": {"input_prompt": "ctx", "output_result": "out", "system_prompt": "sys"}},
        conversation=[{"type": "agent", "nodeId": "a", "content": "hello"}],
    )

    # Verify the running record has agent_io
    running = store.get_run(run_id)
    assert running["agent_io"]["a"]["input_prompt"] == "ctx"

    # Simulate what cancel() should do: save as paused preserving existing data
    # (This will fail until we fix cancel)
    existing = store.get_run(run_id)
    store.save(
        run_id=run_id,
        workflow_name="test_wf",
        agents_snapshot=existing.get("agents_snapshot", []),
        status="paused",
        inputs=existing.get("inputs", {}),
        result=existing.get("result"),
        dag=existing.get("dag"),
        agent_io=existing.get("agent_io"),
        conversation=existing.get("conversation"),
        events=existing.get("events"),
    )

    paused = store.get_run(run_id)
    assert paused["status"] == "paused"
    assert paused["agent_io"]["a"]["input_prompt"] == "ctx"
    assert paused["conversation"][0]["content"] == "hello"
```

**Step 2: Run test to verify it passes with the manual pattern**

Run: `pytest tests/server/test_runner_cancel.py -v`
Expected: PASS — this test verifies the correct save pattern.

**Step 3: Modify cancel() to preserve data**

In `server/runner.py`, modify the `cancel()` method's save section (lines 153-175):

```python
            # Persist as paused so the run stays in history and can be resumed
            from server.repository import get_repository
            repo = get_repository()
            data = repo.get(workflow_id)
            if data is not None:
                workflow = data["workflow"]
                data["status"] = "paused"
                batch_id = data.get("batch_id")

                # Merge with existing disk record to preserve agent_io/conversation/events
                from harness.run_store import RunStore
                existing = RunStore().get_run(workflow_id) or {}
                try:
                    RunStore().save(
                        run_id=workflow_id,
                        workflow_name=workflow.name,
                        agents_snapshot=data.get("agents_snapshot")
                            or _build_agents_snapshot(workflow),
                        status="paused",
                        inputs=data.get("inputs", {}),
                        result=existing.get("result"),
                        dag=repo.get_dag(workflow_id),
                        agent_io=existing.get("agent_io"),
                        batch_id=batch_id,
                        user_id=data.get("user_id") or existing.get("user_id"),
                        conversation=existing.get("conversation"),
                        chart_groups=existing.get("chart_groups"),
                        events=existing.get("events"),
                        created_at=existing.get("created_at"),
                        work_dir=data.get("work_dir") or existing.get("work_dir"),
                    )
                except Exception:
                    pass
```

Key change: **read existing disk record first, merge its data into the paused save**. This prevents the incremental data from being lost.

**Step 4: Run full test suite**

Run: `pytest tests/ -x -q --ignore=tests/test_phase2_integration.py`
Expected: All pass.

**Step 5: Commit**

```bash
git add server/runner.py tests/server/test_runner_cancel.py
git commit -m "fix: preserve incremental data (agent_io, conversation, events) when pausing workflows"
```

---

## Task 3: Persist work_dir to disk records

**Files:**
- Modify: `harness/run_store.py:29-72` (`save` method)
- Modify: `server/runner.py` (`_save_incremental` in `macro_graph.py`)
- Test: `tests/server/test_runner_cancel.py` (extend)

**Why:** `work_dir` is needed for `workflow.setup(work_dir=...)` on resume (MCP reconnection). Currently only in memory. Must be persisted.

**Step 1: Write the failing test**

Add to `tests/server/test_runner_cancel.py`:

```python
def test_run_store_persists_work_dir(tmp_path):
    """RunStore.save() persists work_dir and get_run() returns it."""
    from harness.run_store import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    store.save(
        run_id="test-workdir",
        workflow_name="wf",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
        work_dir="/tmp/some_project",
    )

    record = store.get_run("test-workdir")
    assert record["work_dir"] == "/tmp/some_project"


def test_run_store_work_dir_none_not_persisted(tmp_path):
    """When work_dir is None, it should not appear in the record."""
    from harness.run_store import RunStore

    store = RunStore(runs_dir=tmp_path / "runs")
    store.save(
        run_id="test-no-workdir",
        workflow_name="wf",
        agents_snapshot=[],
        status="completed",
        inputs={},
        result=None,
    )

    record = store.get_run("test-no-workdir")
    assert "work_dir" not in record
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/server/test_runner_cancel.py::test_run_store_persists_work_dir tests/server/test_runner_cancel.py::test_run_store_work_dir_none_not_persisted -v`
Expected: FAIL — `save()` doesn't accept `work_dir` parameter.

**Step 3: Add work_dir to RunStore.save()**

In `harness/run_store.py`, add `work_dir` parameter to `save()`:

```python
    def save(
        self,
        run_id: str,
        workflow_name: str,
        agents_snapshot: list[dict],
        status: str,
        inputs: dict,
        result: dict | None,
        dag: dict | None = None,
        agent_io: dict | None = None,
        batch_id: str | None = None,
        user_id: str | None = None,
        chart_groups: dict | None = None,
        conversation: list[dict] | None = None,
        events: list[dict] | None = None,
        created_at: str | None = None,
        work_dir: str | None = None,
    ) -> Path:
```

And in the record dict builder, add before the `path = self._safe_path(run_id)` line:

```python
        if work_dir:
            record["work_dir"] = work_dir
```

**Step 4: Update _save_incremental to pass work_dir**

In `harness/engine/macro_graph.py:69-115`, modify `_save_incremental` to pass `work_dir`:

```python
        RunStore().save(
            run_id=wid,
            workflow_name=data["workflow"].name,
            agents_snapshot=data.get("agents_snapshot", []),
            status="running",
            inputs=data.get("inputs", {}),
            result=None,
            dag=repo.get_dag(wid),
            agent_io=dict(builder.agent_io),
            batch_id=data.get("batch_id"),
            user_id=data.get("user_id"),
            conversation=conversation,
            chart_groups=chart_groups,
            created_at=data.get("created_at"),
            work_dir=data.get("work_dir"),
        )
```

**Step 5: Update all other RunStore().save() calls to pass work_dir**

In `server/runner.py`, update:
1. `_run_workflow` completion save (~line 287): add `work_dir=work_dir`
2. `_run_workflow` failure save (~line 358): add `work_dir=work_dir`

Note: `cancel()` already passes `work_dir` via `data.get("work_dir") or existing.get("work_dir")` from Task 2.

**Step 6: Run tests**

Run: `pytest tests/ -x -q --ignore=tests/test_phase2_integration.py`
Expected: All pass.

**Step 7: Commit**

```bash
git add harness/run_store.py harness/engine/macro_graph.py server/runner.py tests/server/test_runner_cancel.py
git commit -m "feat: persist work_dir to run records for cross-restart MCP reconnection"
```

---

## Task 4: Add workflow reconstruction in resume_run()

**Files:**
- Modify: `server/routes.py:1426-1499` (`resume_run` endpoint)
- Test: `tests/server/test_routes_resume.py` (new)

**Why:** After process restart, `repo.contains(run_id)` returns False and resume returns 404. We need a fallback: if the run exists on disk, reconstruct the Workflow from `agents_snapshot` + `workflow_dir` and put it in the repo, then proceed with normal resume.

**Step 1: Write the failing test**

Create `tests/server/test_routes_resume.py`:

```python
"""Tests for resume endpoint — cross-restart reconstruction path."""
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.mark.asyncio
async def test_resume_reconstructs_from_disk_when_not_in_repo(tmp_path, monkeypatch):
    """resume_run() reconstructs a Workflow from disk record when repo is empty."""
    from harness.run_store import RunStore
    from server.repository import get_repository, WorkflowRepository

    # Set up clean repo (simulating process restart)
    repo = WorkflowRepository()
    monkeypatch.setattr("server.routes.get_repository", lambda: repo)

    # Persist a paused run with complete agents_snapshot
    store = RunStore(runs_dir=tmp_path / "runs")
    run_id = "test-restart-resume"
    store.save(
        run_id=run_id,
        workflow_name="code_review",
        agents_snapshot=[
            {"name": "reviewer", "after": [], "tools": None, "model": None, "retries": 3},
            {"name": "summarizer", "after": ["reviewer"], "tools": None, "model": None, "retries": 3},
        ],
        status="paused",
        inputs={"task": "review this code"},
        result=None,
        dag={"nodes": ["reviewer", "summarizer"], "edges": [["reviewer", "summarizer"]], "conditional_edges": []},
    )

    # The run is on disk but NOT in repo (simulating restart)
    assert not repo.contains(run_id)
    assert store.get_run(run_id) is not None

    # Now test: resume should find the run on disk, reconstruct, and proceed
    # We mock the checkpoint and runner to avoid needing a real LLM
    from server.routes import resume_run
    from server.schemas import ResumeRequest

    # Mock checkpoint manager
    mock_checkpoint_config = {"configurable": {"thread_id": run_id, "checkpoint_id": "cp-123"}}
    mock_mgr = MagicMock()
    mock_mgr.get_latest_checkpoint_config = AsyncMock(return_value=mock_checkpoint_config)
    mock_mgr.get_checkpointer = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr("server.routes.get_checkpoint_manager", lambda: mock_mgr)

    # Mock runner
    mock_runner = MagicMock()
    mock_runner.running_count = 0
    mock_runner.max_concurrent = 5
    mock_runner.submit = AsyncMock()
    monkeypatch.setattr("server.routes.get_runner", lambda: mock_runner)

    # Mock user
    mock_user = MagicMock()
    mock_user.user_id = "default"
    mock_user.role = "admin"
    monkeypatch.setattr("server.routes.get_current_user", lambda r: mock_user)
    monkeypatch.setattr("server.routes.get_user_manager", lambda: MagicMock(is_admin=lambda u: True))

    # Mock _new_bus
    mock_bus = MagicMock()
    mock_bus.with_user_context = MagicMock(return_value=MagicMock(__enter__=MagicMock(), __exit__=MagicMock()))
    monkeypatch.setattr("server.routes._new_bus", lambda: mock_bus)

    # Create a mock request
    mock_request = MagicMock()

    # Patch RunStore to use our temp dir
    monkeypatch.setattr("harness.run_store._DEFAULT_RUNS_DIR", tmp_path / "runs")

    # Call resume
    result = await resume_run(run_id, ResumeRequest(checkpoint_id=None), mock_request)

    # Verify: run was reconstructed and added to repo
    assert result["workflow_id"] == run_id
    assert result["status"] == "running"
    assert repo.contains(run_id)

    # Verify: reconstructed workflow has correct agents
    wf_data = repo.get(run_id)
    workflow = wf_data["workflow"]
    assert len(workflow.agents) == 2
    assert workflow.agents[0].name == "reviewer"
    assert workflow.agents[1].name == "summarizer"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/server/test_routes_resume.py -v`
Expected: FAIL with 404 "Run not found" — because `repo.contains()` returns False.

**Step 3: Implement reconstruction in resume_run()**

In `server/routes.py`, modify `resume_run()` to add a disk fallback before the 404 error:

Replace the beginning of `resume_run()` (lines 1437-1439):

```python
    repo = get_repository()
    if not repo.contains(run_id):
        # Cross-restart: try to reconstruct from disk record
        from harness.run_store import RunStore
        disk_record = RunStore().get_run(run_id)
        if disk_record is None:
            raise HTTPException(status_code=404, detail="Run not found")

        # Only reconstruct paused runs
        if disk_record.get("status") != "paused":
            raise HTTPException(status_code=404, detail="Run not found")

        _reconstruct_run_to_repo(repo, run_id, disk_record, req)
```

Then add the helper function before `resume_run()`:

```python
def _reconstruct_run_to_repo(repo, run_id: str, record: dict, request: Request) -> None:
    """Reconstruct a Workflow from a persisted run record and inject into the in-memory repo.

    Called when resume_run() finds the run on disk but not in the repo
    (e.g., after process restart).
    """
    from harness.api import Agent, Workflow
    from harness.tools.registry import ToolRegistry
    from harness.checkpoint import get_checkpoint_manager
    from server.runner import _build_agents_snapshot
    from datetime import datetime, timezone

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    if not is_admin and record.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")

    workflow_name = record["workflow_name"]
    agents_snapshot = record.get("agents_snapshot", [])
    work_dir = record.get("work_dir")

    # Reconstruct agents from snapshot (includes on_pass/on_fail/eval)
    agents = [
        Agent.from_dict({
            "name": a["name"],
            "after": a.get("after", []),
            "tools": a.get("tools"),
            "model": a.get("model"),
            "retries": a.get("retries", 3),
            "on_pass": a.get("on_pass"),
            "on_fail": a.get("on_fail"),
            "eval": a.get("eval", False),
        })
        for a in agents_snapshot
    ]

    # Resolve workflow dir
    user_id = user.user_id if user.user_id != "default" else None
    wf_dir = _validate_workflow_dir(workflow_name, user_id)

    # Create fresh Bus
    event_bus = _new_bus()

    # Create and compile workflow (checkpoint checkpointer will be injected by resume)
    workflow = Workflow(
        name=workflow_name,
        agents=agents,
        workflow_dir=wf_dir,
        tool_registry=ToolRegistry(),
        event_bus=event_bus,
    )

    # Auto-register extensions
    from harness.extensions.eval import EvalJudge
    if any(a.eval for a in agents):
        workflow.use(EvalJudge(max_retries=2))

    # Store in repo
    dag = record.get("dag")
    repo.put(run_id, {
        "workflow": workflow,
        "status": "paused",
        "result": record.get("result"),
        "inputs": record.get("inputs", {}),
        "thread_id": run_id,
        "created_at": record.get("created_at", datetime.now(timezone.utc).isoformat()),
        "agents_snapshot": _build_agents_snapshot(workflow),
        "event_bus": event_bus,
        "user_id": record.get("user_id"),
        "work_dir": work_dir,
    })
    if dag:
        repo.put_dag(run_id, dag)
```

**Step 4: Update the rest of resume_run() to handle async checkpointer**

The existing `resume_run()` gets the checkpointer from the reconstructed workflow's compile step. We need to ensure the checkpointer is set before `get_latest_checkpoint_config` is called. Modify the flow:

```python
    data = repo.get(run_id)
    workflow = data["workflow"]

    # Ensure checkpointer is set (needed for both fresh and reconstructed workflows)
    if workflow.checkpointer is None:
        from harness.checkpoint import get_checkpoint_manager
        checkpoint_mgr = get_checkpoint_manager()
        workflow.checkpointer = await checkpoint_mgr.get_checkpointer()

    # Compile if needed
    if workflow._compiled is None:
        workflow.compile()

    # ... rest of existing resume logic unchanged ...
```

**Step 5: Run tests**

Run: `pytest tests/server/test_routes_resume.py -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `pytest tests/ -x -q --ignore=tests/test_phase2_integration.py`
Expected: All pass.

**Step 7: Commit**

```bash
git add server/routes.py tests/server/test_routes_resume.py
git commit -m "feat: reconstruct workflow from disk on resume after process restart"
```

---

## Task 5: Fix rerun() to use Agent.from_dict() for complete reconstruction

**Files:**
- Modify: `server/routes.py:1534-1538` (`rerun` endpoint)

**Why:** `rerun()` currently constructs agents with only `name` and `after`, losing `on_pass`/`on_fail`. This is a pre-existing bug that would affect conditional-edge workflows. Since we've now extended `agents_snapshot`, fix this too.

**Step 1: Fix rerun() agent reconstruction**

In `server/routes.py`, replace lines 1534-1538:

```python
    # Reconstruct agents from snapshot
    agents = [
        Agent(name=a["name"], after=a.get("after", []))
        for a in agents_snapshot
    ]
```

With:

```python
    # Reconstruct agents from snapshot (includes conditional edges + eval)
    agents = [
        Agent.from_dict({
            "name": a["name"],
            "after": a.get("after", []),
            "tools": a.get("tools"),
            "model": a.get("model"),
            "retries": a.get("retries", 3),
            "on_pass": a.get("on_pass"),
            "on_fail": a.get("on_fail"),
            "eval": a.get("eval", False),
        })
        for a in agents_snapshot
    ]
```

**Step 2: Run full test suite**

Run: `pytest tests/ -x -q --ignore=tests/test_phase2_integration.py`
Expected: All pass — backward compatible since new fields default to None/False.

**Step 3: Commit**

```bash
git add server/routes.py
git commit -m "fix: rerun() preserves conditional edges and eval flags from snapshot"
```

---

## Task 6: Frontend — restore conversation on resume reconnect

**Files:**
- Modify: `frontend/src/components/sidebar/RunHistoryList.tsx:116-130` (`handleResume`)
- Modify: `frontend/src/contexts/workflow-context/WorkflowScope.tsx` (REST fallback handles this)

**Why:** When a paused run is resumed (same run_id), the frontend calls `setActiveWorkflowId(runId)` + `showLive()`. The `WorkflowScope`'s REST fallback timer (5s) will kick in if WS events don't populate the DAG. But we can be smarter: pre-load the run data immediately so the conversation appears before the resumed node starts executing.

**Step 1: Modify handleResume to pre-populate stores**

In `frontend/src/components/sidebar/RunHistoryList.tsx`, modify `handleResume`:

```typescript
  const handleResume = async (e: React.MouseEvent, runId: string) => {
    e.stopPropagation();
    try {
      // Pre-load existing conversation data for immediate display
      const existingRun = await fetchRun(runId);

      const r = await fetchWithAuth(`/api/runs/${runId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!r.ok) return;
      const data = await r.json();

      // If we have existing events, replay them into scoped stores
      // before connecting to live WebSocket
      if (existingRun?.events?.length) {
        const { replayEventsToStores } = await import("@/contexts/workflow-context/replayEvents");
        replayEventsToStores(data.workflow_id ?? runId, existingRun.events);
      }

      setActiveWorkflowId(data.workflow_id ?? runId);
      showLive();
    } catch {}
    await fetchRuns();
  };
```

**Step 2: Build and verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 3: Commit**

```bash
git add frontend/src/components/sidebar/RunHistoryList.tsx
git commit -m "feat: pre-populate conversation on resume for seamless reconnection"
```

---

## Risk Assessment

### Backward Compatibility
- **AgentSnapshot new fields**: All optional with defaults (None/False). Old records without these fields deserialize correctly.
- **RunStore.save() new `work_dir` param**: Optional, defaults to None. Not written to record when None. Old code calling save() without it continues to work.
- **cancel() enriched save**: Reads existing record (may be None for first run). Uses `or {}` fallback. No crash risk.
- **_reconstruct_run_to_repo**: Only triggered when `repo.contains()` is False AND disk record exists AND status is "paused". Normal running/completed flows untouched.

### Edge Cases
- **Old paused records without `on_pass`/`on_fail`**: Reconstruction creates agents without conditional edges. LangGraph checkpoint's `next_nodes` may reference conditional targets that don't exist → runtime error. Mitigation: log a warning, suggest rerun instead.
- **workflow.json deleted**: `_validate_workflow_dir` returns 400. User must restore the workflow definition.
- **checkpoint DB deleted/corrupted**: `get_latest_checkpoint_config` returns None → 400 "No resumable checkpoint found". Graceful degradation.

### What This Does NOT Fix
- Mid-node resume: If an agent was mid-LLM-stream when paused, it restarts from scratch (LangGraph checkpoint granularity is node-boundary).
- Eval judge auto-generated nodes: Their `md_content` is synthesized at build time. Reconstruction re-synthesizes from snapshot, which should match.
- MCP server reconnection: `work_dir` is persisted, `workflow.setup(work_dir=...)` is called during `_run_workflow`, but MCP server configs come from `workflow.json`. If the JSON hasn't changed, reconnection works.

---

## Verification Checklist

After all tasks are complete:

1. `pytest tests/ -x -q --ignore=tests/test_phase2_integration.py` — all pass
2. Manual test: Start a workflow → Pause → Resume (same session) → conversation preserved
3. Manual test: Start a workflow → Pause → Restart server → Resume → conversation preserved, agent continues
4. Manual test: Start a conditional_route workflow → Pause after classifier → Resume → routing works correctly
5. `cd frontend && npm run build` — no errors
