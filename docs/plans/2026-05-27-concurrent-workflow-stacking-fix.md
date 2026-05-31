# Concurrent Workflow Conversation Stacking Fix

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make backend the single source of truth by saving incrementally per-node, so switching between concurrent running workflows always shows correct isolated conversation data.

**Architecture:** After each node completes, flush accumulated `agent_io` to disk via `RunStore.save(status="running")`. When frontend switches to a running workflow, clear messages and fetch from backend (which now has incremental data). No Context Architecture re-enablement needed.

**Tech Stack:** Python (FastAPI, LangGraph), RunStore JSON persistence, React/TypeScript (Zustand stores)

---

## Design Principles

1. **Backend owns all data.** Frontend is a read-only display layer.
2. **Persist per-node, not per-workflow.** Each completed node flushes to disk. Crashes only lose the in-progress node.
3. **Running workflow switch = backend fetch.** Don't trust in-memory cache for running workflows.
4. **Best-effort incremental save.** If `_save_incremental` fails, the workflow keeps running. Final save on completion is the authoritative record.

---

### Task 1: Add `created_at` parameter to `RunStore.save()`

**Files:**
- Modify: `harness/run_store.py:28-51`
- Test: `tests/test_run_store.py`

**Why:** Each incremental save overwrites the same JSON file. Without preserving `created_at`, the timestamp resets to "now" on every node completion, breaking `list_runs` sort order and sidebar display.

**Step 1: Write the failing test**

Add to `tests/test_run_store.py`:

```python
def test_save_preserves_created_at():
    """save() with created_at parameter preserves the original timestamp."""
    store = RunStore()
    original_ts = "2026-01-01T00:00:00+00:00"
    store.save(
        "inc-test", "wf", [], "running", {}, None,
        created_at=original_ts,
    )
    r1 = store.get_run("inc-test")
    assert r1["created_at"] == original_ts

    # Overwrite with more data — created_at should stay the same
    store.save(
        "inc-test", "wf", [], "running", {}, None,
        agent_io={"node_a": {"output": "hello"}},
        created_at=original_ts,
    )
    r2 = store.get_run("inc-test")
    assert r2["created_at"] == original_ts
    assert r2["agent_io"] == {"node_a": {"output": "hello"}}
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_store.py::test_save_preserves_created_at -v`
Expected: FAIL — `save() got an unexpected keyword argument 'created_at'`

**Step 3: Implement the change**

In `harness/run_store.py`, add `created_at` parameter to `save()` signature (line 28):

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
        created_at: str | None = None,
    ) -> Path:
```

Change line 51 from:

```python
            "created_at": datetime.now(timezone.utc).isoformat(),
```

to:

```python
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_store.py::test_save_preserves_created_at -v`
Expected: PASS

**Step 5: Run existing tests for regression**

Run: `pytest tests/test_run_store.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add harness/run_store.py tests/test_run_store.py
git commit -m "feat: add created_at parameter to RunStore.save for incremental persistence"
```

---

### Task 2: Add `_save_incremental()` helper and wire into macro_graph

**Files:**
- Modify: `harness/engine/macro_graph.py:66` (add function), `:624` (call it)

**Step 1: Add `_save_incremental()` function**

In `harness/engine/macro_graph.py`, after `clear_stop_regen` (line 66), add:

```python
def _save_incremental(builder, event_bus):
    """Best-effort incremental save after each node completes.

    Persists agent_io + derived conversation to disk so that switching
    to a running workflow always fetches authoritative data from backend.
    Never raises — if save fails, the workflow continues normally.
    """
    try:
        from harness.run_store import RunStore
        from harness.extensions.collectors import build_conversation, ChartCollector
        from server.repository import get_repository

        wid = builder.workflow_id
        if not wid:
            return

        repo = get_repository()
        data = repo.get(wid)
        if not data or not data.get("workflow"):
            return

        conversation = build_conversation(dict(builder.agent_io))

        chart_groups = None
        if event_bus:
            cc = ChartCollector(event_bus)
            cg = cc.get_chart_groups()
            if cg.get("groupOrder"):
                chart_groups = cg

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
        )
    except Exception:
        pass
```

**Step 2: Wire the call after agent_io collection**

At line 624, after `builder_self.agent_io[agent_def.name] = io_data`, add:

```python
                builder_self.agent_io[agent_def.name] = io_data
                # Incremental save: persist completed node data to disk
                _save_incremental(builder_self, bus)
```

**Step 3: Run existing tests**

Run: `pytest tests/test_run_store.py tests/harness/extensions/test_collectors.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add harness/engine/macro_graph.py
git commit -m "feat: add per-node incremental save to RunStore during execution"
```

---

### Task 3: Frontend — Add `forceReplace` to `_restoreConversation`

**Files:**
- Modify: `frontend/src/hooks/useWorkflowEvents.ts:102-129`

**Step 1: Modify `_restoreConversation`**

Change the function signature from:

```typescript
async function _restoreConversation(workflowId: string): Promise<void> {
```

to:

```typescript
async function _restoreConversation(workflowId: string, forceReplace: boolean = false): Promise<void> {
```

Change the inner condition from:

```typescript
      const current = useConversationStore.getState().messages;
      if (current.length === 0) {
```

to:

```typescript
      const current = useConversationStore.getState().messages;
      if (forceReplace || current.length === 0) {
```

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/hooks/useWorkflowEvents.ts
git commit -m "feat: add forceReplace option to _restoreConversation"
```

---

### Task 4: Frontend — Rewrite `setActiveWorkflowId` to fetch from backend for running workflows

**Files:**
- Modify: `frontend/src/hooks/useWorkflowEvents.ts:314-349`

**Step 1: Add import**

At the top of the file, add:

```typescript
import { useRunHistoryStore } from "@/stores/runHistoryStore";
```

**Step 2: Replace `setActiveWorkflowId` function**

Replace lines 314-349 with:

```typescript
export function setActiveWorkflowId(id: string | null) {
  const currentId = useWorkflowStore.getState().activeWorkflowId;

  // Check if in Context architecture mode
  // When in Context mode, WorkflowScope handles the switch
  const isInContextMode = typeof window !== "undefined" && (window as unknown as { __useContextArchitecture?: boolean }).__useContextArchitecture;

  if (isInContextMode) {
    // Context mode: just update the global state (WorkflowScope reads from batchStore)
    useWorkflowStore.getState().setActiveWorkflowId(id);
    useWorkflowStore.getState().setActiveWid(id);
    return;
  }

  // Legacy mode: use cache
  if (currentId && currentId !== id) {
    // Save current run's state to cache
    useConversationStore.getState().saveToCache(currentId);
    useOutputStore.getState().saveToCache(currentId);
  }
  useWorkflowStore.getState().setActiveWorkflowId(id);
  // Also switch workflowStore's cache (for node states, dag, etc.)
  if (id !== currentId) {
    useWorkflowStore.getState().setActiveWid(id);
  }
  if (id && id !== currentId) {
    // Determine if target is a running workflow
    const runHistory = useRunHistoryStore.getState().runs;
    const targetRun = runHistory.find(r => r.run_id === id);
    const isRunning = targetRun?.status === "running";

    // Always clear messages immediately to prevent stacking
    useConversationStore.setState({ messages: [], pendingQuestionId: null, pendingQuestionAgent: null });
    useOutputStore.getState().restoreFromCache(id);

    if (isRunning) {
      // Running workflow: backend has incremental data, always fetch from it
      _restoreConversation(id, true);
    } else {
      // Not running: try cache first, then backend
      const convStore = useConversationStore.getState();
      const restored = convStore.restoreFromCache(id);
      if (!restored) {
        _restoreConversation(id);
      }
    }
  }
}
```

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/hooks/useWorkflowEvents.ts
git commit -m "fix: always fetch from backend when switching to running workflow"
```

---

### Task 5: End-to-end smoke test

**Files:**
- No code changes

**Step 1: Build frontend**

```bash
cd frontend && npm run build && cd ..
```

**Step 2: Start backend**

```bash
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

**Step 3: Launch two concurrent workflows**

```bash
# Workflow A: 3-agent pipeline (takes longer)
curl -s -X POST http://localhost:8000/api/workflows \
  -H "X-User-Id: alice" -H "Content-Type: application/json" \
  -d '{"name":"demo_pipeline","workflow":"demo_pipeline","agents":[{"name":"analyzer","after":[]},{"name":"planner","after":["analyzer"]},{"name":"reviewer","after":["planner"]}],"inputs":{"task":"Analyze web server performance"}}' | python3 -c "import sys,json; d=json.load(sys.stdin); print('WF_A:', d['workflow_id'])"

# Workflow B: single-agent (completes faster)
curl -s -X POST http://localhost:8000/api/workflows \
  -H "X-User-Id: alice" -H "Content-Type: application/json" \
  -d '{"name":"chart_demo","workflow":"chart_demo","agents":[{"name":"runner","after":[],"tools":["bash"],"retries":3}],"inputs":{"task":"echo hello"}}' | python3 -c "import sys,json; d=json.load(sys.stdin); print('WF_B:', d['workflow_id'])"
```

**Step 4: While both running, verify incremental data on disk**

```bash
# Check that running workflow has conversation + agent_io
curl -s http://localhost:8000/api/runs -H "X-User-Id: alice" | python3 -c "
import sys,json
for r in json.load(sys.stdin):
    if r['status'] == 'running':
        print(f'RUNNING {r[\"run_id\"][:12]}: conv={len(r.get(\"conversation\",[]))} aio={bool(r.get(\"agent_io\"))}')
"
```

Expected: Running workflows show `conv > 0` and `aio=True` (incremental save worked).

**Step 5: After completion, verify final data is correct**

```bash
# Check latest completed runs
curl -s http://localhost:8000/api/runs -H "X-User-Id: alice" | python3 -c "
import sys,json
for r in json.load(sys.stdin)[:4]:
    conv = r.get('conversation', [])
    aio = r.get('agent_io', {})
    print(f'{r[\"run_id\"][:12]}... st={r[\"status\"]:10s} conv={len(conv):3d} aio_agents={list(aio.keys())} user={r.get(\"user_id\",\"?\")}')
"
```

Expected: Both completed runs have conversation data, correct agent_io, no cross-contamination.

**Step 6: Frontend browser test**

1. Open http://localhost:3000 in browser
2. Start two workflows (demo_pipeline + chart_demo)
3. While both running, click between them in the sidebar
4. Verify: no message stacking, each workflow shows its own conversation
5. Click a completed run — verify replay shows correct data
6. Switch users (HeaderBar user selector) — verify run history is isolated

---

## Files Modified Summary

| File | Change |
|------|--------|
| `harness/run_store.py` | Add `created_at` param to `save()` |
| `harness/engine/macro_graph.py` | Add `_save_incremental()` + call after line 624 |
| `frontend/src/hooks/useWorkflowEvents.ts` | Add `forceReplace` param, rewrite `setActiveWorkflowId` |
| `tests/test_run_store.py` | Add `created_at` preservation test |

---

## Why This Works

1. **No stacking**: Each switch to a running workflow clears messages and fetches from backend (authoritative per-run data)
2. **Crash safe**: Per-node save means at most the in-progress node's data is lost on crash
3. **No Context Architecture needed**: Global store is just a display buffer for the active workflow
4. **Minimal changes**: ~30 lines backend, ~15 lines frontend
5. **Existing infra**: `build_conversation()`, `RunStore.save()`, `get_run` endpoint all already work correctly
