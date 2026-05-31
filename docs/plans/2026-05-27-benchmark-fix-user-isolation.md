# Benchmark Fix + User Isolation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the broken benchmark frontend so it works with the scoped-stores architecture, and add user isolation so different users' benchmarks and results are invisible to each other.

**Architecture:** Benchmark is a dispatcher + result collector layered on top of the existing parallel workflow execution. Backend `run_benchmark` already creates one workflow run per task via `WorkflowRunner.submit()` with a shared `batch_id`. Frontend needs to (1) stop using deprecated global stores, (2) wire into the scoped-store `WorkflowManager` for batch mode, (3) filter all benchmark data by `user_id`. User isolation follows the same pattern as `RunStore.list_runs(user_id=...)` — store `user_id` in the record, filter on read, admin sees all.

**Tech Stack:** Python / FastAPI / Pydantic (backend), React / Zustand / WebSocket (frontend)

---

## Task 1: Backend — Add user_id to BenchmarkStore

**Files:**
- Modify: `harness/benchmark_store.py`

**Why:** Currently `benchmark.json` and result JSON files have no `user_id` field. We need to store it so we can filter on read.

**Step 1: Add user_id to save_benchmark**

In `harness/benchmark_store.py`, modify `save_benchmark()` to accept and persist `user_id`:

```python
def save_benchmark(
    self,
    name: str,
    tasks: list[dict],
    description: str = "",
    user_id: str | None = None,
) -> Path:
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(f"Invalid benchmark name: {name}")
    bdir = self._benchmark_dir(name)
    bdir.mkdir(parents=True, exist_ok=True)
    self._results_dir(name).mkdir(exist_ok=True)

    for i, t in enumerate(tasks):
        if not t.get("id"):
            t["id"] = f"task_{i + 1}"

    record = {
        "name": name,
        "description": description,
        "tasks": tasks,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if user_id:
        record["user_id"] = user_id
    path = self._benchmark_path(name)
    path.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return path
```

**Step 2: Add user_id filter to list_benchmarks**

```python
def list_benchmarks(self, user_id: str | None = None) -> list[dict]:
    if not self._dir.exists():
        return []
    results = []
    for bdir in sorted(self._dir.iterdir()):
        if not bdir.is_dir():
            continue
        bfile = bdir / "benchmark.json"
        if bfile.exists():
            try:
                data = json.loads(bfile.read_text())
                if user_id is not None:
                    bm_uid = data.get("user_id", "default")
                    if bm_uid != user_id:
                        continue
                results.append(data)
            except (json.JSONDecodeError, KeyError):
                continue
    return results
```

**Step 3: Add user_id to save_result**

In `save_result()`, ensure the result dict carries `user_id`:

```python
def save_result(self, benchmark_name: str, result: dict) -> Path:
    rdir = self._results_dir(benchmark_name)
    rdir.mkdir(parents=True, exist_ok=True)
    run_id = result.get("run_id", "")
    path = rdir / f"{run_id}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return path
```

No change needed here — the result dict is already enriched with `user_id` by the caller (we'll fix that in Task 2).

**Step 4: Add user_id filter to list_results**

```python
def list_results(
    self, benchmark_name: str, workflow_name: str | None = None, user_id: str | None = None
) -> list[dict]:
    rdir = self._results_dir(benchmark_name)
    if not rdir.exists():
        return []
    results = []
    for f in rdir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if workflow_name and data.get("workflow_name") != workflow_name:
                continue
            if user_id is not None:
                r_uid = data.get("user_id", "default")
                if r_uid != user_id:
                    continue
            results.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    results.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return results
```

**Step 5: Run existing tests**

Run: `pytest tests/ -k benchmark -v`
Expected: All pass (new params are optional with defaults, backward-compatible)

**Step 6: Commit**

```
feat(benchmark): add user_id to BenchmarkStore for isolation
```

---

## Task 2: Backend — Add user filtering to benchmark API endpoints

**Files:**
- Modify: `server/routes.py` (lines 912–1157)

**Why:** All benchmark endpoints currently ignore user context. Need to pass `user_id` through from `get_current_user(request)` and filter accordingly.

**Step 1: Add auth + user filtering to `list_benchmarks`**

```python
@router.get("/benchmarks")
async def list_benchmarks(request: Request) -> list[dict]:
    """List benchmarks for the current user (admin sees all)."""
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    uid = None if is_admin else user.user_id
    return _get_benchmark_store().list_benchmarks(user_id=uid)
```

**Step 2: Add user_id to `create_benchmark`**

```python
@router.post("/benchmarks")
async def create_benchmark(body: BenchmarkDef, request: Request) -> dict:
    """Create a new benchmark."""
    user = get_current_user(request)
    user_id = user.user_id if user.user_id != "default" else None
    store = _get_benchmark_store()
    tasks = [t.model_dump() for t in body.tasks]
    path = store.save_benchmark(body.name, tasks, description=body.description, user_id=user_id)
    return {"name": body.name, "path": str(path)}
```

**Step 3: Add user_id to `get_benchmark` (ownership check)**

```python
@router.get("/benchmarks/{name}")
async def get_benchmark(name: str, request: Request) -> dict:
    """Get benchmark definition."""
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if not is_admin and bm.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    return bm
```

**Step 4: Add user_id to `run_benchmark` result record**

In the `run_benchmark` function, add `user_id` to the result dict that gets persisted:

```python
result = {
    "run_id": batch_id,
    "benchmark_name": name,
    "workflow_name": body.workflow,
    "status": "running",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "task_results": task_results,
}
if user_id:
    result["user_id"] = user_id
store.save_result(name, result)
```

**Step 5: Add user filtering to `list_benchmark_results`**

```python
@router.get("/benchmarks/{name}/results")
async def list_benchmark_results(name: str, request: Request) -> list[dict]:
    """List run results for a benchmark, enriched with live scores."""
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)
    store = _get_benchmark_store()

    # Ownership check on benchmark itself
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if not is_admin and bm.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    uid = None if is_admin else user.user_id
    results = store.list_results(name, user_id=uid)

    repo = get_repository()
    for result in results:
        _enrich_benchmark_result(result, repo, store, name)

    return results
```

**Step 6: Add ownership check to `get_benchmark_result`**

```python
@router.get("/benchmarks/{name}/results/{run_id}")
async def get_benchmark_result(name: str, run_id: str, request: Request) -> dict:
    """Get a specific benchmark run result."""
    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    store = _get_benchmark_store()
    bm = store.load_benchmark(name)
    if not bm:
        raise HTTPException(status_code=404, detail="Benchmark not found")
    if not is_admin and bm.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=404, detail="Benchmark not found")

    result = store.get_result(run_id, benchmark_name=name)
    if not result:
        raise HTTPException(status_code=404, detail="Result not found")

    repo = get_repository()
    _enrich_benchmark_result(result, repo, store, name)

    return result
```

**Step 7: Add ownership check to `delete_benchmark` and `update_benchmark`**

Same pattern — call `get_current_user`, check ownership, return 404 if not owned.

**Step 8: Run tests**

Run: `pytest tests/ -v`
Expected: All pass

**Step 9: Commit**

```
feat(benchmark): enforce user isolation on all API endpoints
```

---

## Task 3: Backend tests — benchmark user isolation

**Files:**
- Create: `tests/test_benchmark_isolation.py`

**Why:** Verify that user isolation works correctly — user A can't see user B's benchmarks or results.

**Step 1: Write the test**

```python
"""Tests for benchmark user isolation."""
import json
import pytest
from pathlib import Path
from harness.benchmark_store import BenchmarkStore


@pytest.fixture
def store(tmp_path):
    return BenchmarkStore(benchmarks_dir=str(tmp_path))


class TestBenchmarkStoreIsolation:
    def test_save_and_list_with_user_id(self, store):
        store.save_benchmark("bm-a", [{"label": "Task A"}], user_id="user_a")
        store.save_benchmark("bm-b", [{"label": "Task B"}], user_id="user_b")
        store.save_benchmark("bm-shared", [{"label": "Shared"}])  # no user_id

        assert len(store.list_benchmarks(user_id="user_a")) == 2  # bm-a + bm-shared
        assert len(store.list_benchmarks(user_id="user_b")) == 2  # bm-b + bm-shared
        assert len(store.list_benchmarks()) == 3  # no filter → all

    def test_list_results_filtered_by_user(self, store):
        store.save_benchmark("test-bm", [{"label": "T"}])
        store.save_result("test-bm", {"run_id": "r1", "user_id": "user_a", "status": "completed"})
        store.save_result("test-bm", {"run_id": "r2", "user_id": "user_b", "status": "completed"})
        store.save_result("test-bm", {"run_id": "r3", "status": "completed"})  # no user_id

        results = store.list_results("test-bm", user_id="user_a")
        assert len(results) == 2  # r1 + r3 (default)
        run_ids = {r["run_id"] for r in results}
        assert run_ids == {"r1", "r3"}

    def test_benchmark_record_carries_user_id(self, store):
        store.save_benchmark("my-bm", [{"label": "T"}], user_id="user_x")
        bm = store.load_benchmark("my-bm")
        assert bm["user_id"] == "user_x"

    def test_benchmark_without_user_id_is_default(self, store):
        store.save_benchmark("legacy-bm", [{"label": "T"}])
        bm = store.load_benchmark("legacy-bm")
        assert "user_id" not in bm  # backward compat
        # Should be visible to any user (defaults to "default" on read)
        assert len(store.list_benchmarks(user_id="anyone")) == 1

    def test_delete_benchmark_removes_all_results(self, store):
        store.save_benchmark("del-me", [{"label": "T"}], user_id="user_a")
        store.save_result("del-me", {"run_id": "r1", "status": "completed"})
        assert store.delete_benchmark("del-me")
        assert store.load_benchmark("del-me") is None
```

**Step 2: Run tests**

Run: `pytest tests/test_benchmark_isolation.py -v`
Expected: All pass

**Step 3: Commit**

```
test(benchmark): add user isolation tests for BenchmarkStore
```

---

## Task 4: Frontend — Fix BenchmarkRunner to use scoped stores

**Files:**
- Modify: `frontend/src/components/benchmark/BenchmarkRunner.tsx`

**Why:** `BenchmarkRunner` currently imports deprecated global stores (`useWorkflowStore`, `useOutputStore`, `useChatStore`, etc.) and calls their `reset()`/`saveToCache()` methods. In the scoped-stores architecture, each workflow gets its own isolated stores via `WorkflowManager`, so no manual reset/cache is needed.

**Step 1: Rewrite BenchmarkRunner imports**

Remove all global store imports. Replace with:

```typescript
"use client";

import { useState, useEffect, useCallback } from "react";
import { Play, Loader2, CheckCircle, XCircle, Circle, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useBatchStore, type BatchRun } from "@/stores/batchStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { fetchWithAuth } from "@/lib/api";
```

**Step 2: Remove the global store reset/cache logic from `runBenchmark`**

Delete these lines from `runBenchmark`:
```typescript
// DELETE ALL OF THIS:
const currentWid = useWorkflowStore.getState().workflowId;
if (currentWid) {
  useConversationStore.getState().saveToCache(currentWid);
  useOutputStore.getState().saveToCache(currentWid);
}
useOutputStore.getState().reset();
useChatStore.getState().reset();
useChartStore.getState().reset();
useConversationStore.getState().reset();
```

Replace with: pre-creating scoped store entries for each workflow in the batch, so `eventRouter` can find them:

```typescript
const runBenchmark = useCallback(async () => {
  if (!selectedWf) return;
  setRunning(true);
  setError("");

  try {
    const r = await fetchWithAuth(
      `${API_BASE}/api/benchmarks/${encodeURIComponent(benchmark.name)}/run`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workflow: selectedWf }),
      },
    );

    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();

    // Fetch batch details to get workflow_ids
    const batchR = await fetchWithAuth(`${API_BASE}/api/batch/${data.run_id}`);
    if (!batchR.ok) throw new Error("Failed to fetch batch status");
    const batchData = await batchR.json();

    // Pre-create scoped store entries for each run so events can route to them
    const manager = getWorkflowManager();
    for (const run of batchData.runs) {
      if (run.workflow_id) {
        manager.getOrCreate(run.workflow_id);
      }
    }

    createBatch(
      batchData.batch_id,
      batchData.runs.map((run: { workflow_id: string; label: string; status: string }) => ({
        workflowId: run.workflow_id,
        taskId: "",
        label: run.label,
        status: run.status as BatchRun["status"],
      })),
      benchmark.name,
      selectedWf,
    );

    // Refresh sidebar to show the new batch runs
    useRunHistoryStore.getState().fetchRuns();
  } catch (e: unknown) {
    setError(e instanceof Error ? e.message : "Failed to start benchmark");
  } finally {
    setRunning(false);
  }
}, [selectedWf, benchmark.name, createBatch]);
```

**Step 3: Fix handleSelectRun to use WorkflowManager**

```typescript
const handleSelectRun = useCallback(
  (wid: string) => {
    const manager = getWorkflowManager();
    manager.setActiveWorkflowId(wid);
    useBatchStore.getState().selectRun(wid);
  },
  [],
);
```

**Step 4: Remove useBatchWorkflowEvents import**

The `useBatchWorkflowEvents` call in `BenchmarkRunner` can be removed. Batch WS lifecycle is handled by `useWorkflowWS.ts` which lives in the parent `WorkflowCenterPanel` — it detects batch mode via `useBatchStore.activeBatchId` and auto-connects the batch WS.

Delete:
```typescript
const { isConnected } = useBatchWorkflowEvents(activeBatchId);
```

Replace the connection indicator section with a simpler check using the batch WS status from `useWorkflowWS` context (already wired up at the parent level), or just remove the indicator entirely since the parent `ScopedCenterPanel` already has the connection managed.

Actually — let's keep the indicator but read it from a simpler source. The `useBatchWebSocket` hook is standalone and works fine; the issue was that `BenchmarkRunner` imported it via `useWorkflowEvents.ts` which also had legacy dispatch logic. We can import it directly:

```typescript
import { useBatchWebSocket } from "@/hooks/useBatchWebSocket";
import { dispatchBatchEvent } from "@/contexts/workflow-context/eventRouter";
```

Then in the component:
```typescript
const { isConnected } = useBatchWebSocket({
  batchId: activeBatchId,
  onEvent: useCallback((event: WSEvent) => {
    dispatchBatchEvent(event);
  }, []),
});
```

**Step 5: Use `fetchWithAuth` for the workflow definitions fetch**

Replace the bare `fetch` calls with `fetchWithAuth` to send auth headers:

```typescript
useEffect(() => {
  fetchWithAuth(`${API_BASE}/api/workflows/definitions`)
    .then((r) => r.json())
    .then((data: WorkflowOption[]) => setWorkflows(data))
    .catch(() => {});
}, []);
```

**Step 6: Verify the full component compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 7: Commit**

```
fix(benchmark): rewrite BenchmarkRunner to use scoped stores
```

---

## Task 5: Frontend — Fix Sidebar benchmark fetch with auth

**Files:**
- Modify: `frontend/src/components/sidebar/Sidebar.tsx`

**Why:** The sidebar fetches benchmarks with bare `fetch("/api/benchmarks")` without auth headers. Backend now filters by user, so we need `fetchWithAuth`.

**Step 1: Replace bare fetch with fetchWithAuth**

Find the benchmark fetch `useEffect` in `Sidebar.tsx` and change:

```typescript
// Before
fetch("/api/benchmarks")

// After
import { fetchWithAuth } from "@/lib/api";
// ...
fetchWithAuth("/api/benchmarks")
```

**Step 2: Verify compile**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Commit**

```
fix(benchmark): add auth headers to sidebar benchmark fetch
```

---

## Task 6: Frontend — Fix BenchmarkCompare and BenchmarkEditor auth

**Files:**
- Modify: `frontend/src/components/benchmark/BenchmarkCompare.tsx`
- Modify: `frontend/src/components/benchmark/BenchmarkEditor.tsx`
- Modify: `frontend/src/components/layout/ScopedCenterPanel.tsx`

**Why:** All `fetch()` calls to benchmark API endpoints need auth headers for user isolation to work.

**Step 1: In BenchmarkCompare.tsx**

Replace all bare `fetch` with `fetchWithAuth`:

```typescript
import { fetchWithAuth } from "@/lib/api";
// Replace all: fetch(`/api/benchmarks/...`) → fetchWithAuth(`/api/benchmarks/...`)
```

**Step 2: In BenchmarkEditor.tsx**

Replace bare `fetch` with `fetchWithAuth`:

```typescript
import { fetchWithAuth } from "@/lib/api";
// Replace all: fetch("/api/benchmarks", ...) → fetchWithAuth("/api/benchmarks", ...)
```

**Step 3: In ScopedCenterPanel.tsx**

Replace bare `fetch` for benchmark endpoints with `fetchWithAuth`:

```typescript
import { fetchWithAuth } from "@/lib/api";
// Replace: fetch(`/api/benchmarks/${...}`) → fetchWithAuth(`/api/benchmarks/${...}`)
// Replace: fetch("/api/benchmarks", ...) → fetchWithAuth("/api/benchmarks", ...)
```

**Step 4: Verify compile**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 5: Commit**

```
fix(benchmark): add auth headers to all benchmark fetch calls
```

---

## Task 7: Frontend — Clean up legacy batch code in useWorkflowEvents.ts

**Files:**
- Modify: `frontend/src/hooks/useWorkflowEvents.ts`

**Why:** This file contains a legacy `dispatchBatchEvent` function (around line 470-497) that duplicates the one in `eventRouter.ts` but uses global stores instead of scoped stores. Having two functions with the same name but different behavior is a bug magnet. The `switchBatchRun` and `setActiveWorkflowId` exports also operate on global stores.

**Step 1: Remove the legacy `dispatchBatchEvent` function** (around lines 470-497)

This function is superseded by `dispatchBatchEvent` in `eventRouter.ts`.

**Step 2: Remove `useBatchWorkflowEvents` export** (around lines 499-510)

This hook is no longer used — `BenchmarkRunner` now imports `useBatchWebSocket` directly and calls `dispatchBatchEvent` from `eventRouter.ts`.

**Step 3: Remove `switchBatchRun` export** (around lines 357-378)

This function operated on global stores. Benchmark run switching now uses `WorkflowManager.setActiveWorkflowId()` + `batchStore.selectRun()`.

**Step 4: Remove `setActiveWorkflowId` export** (around lines 318-354)

This function operated on global stores with cache logic. The scoped-stores architecture uses `WorkflowManager.setActiveWorkflowId()` directly.

**Step 5: Clean up unused imports**

Remove imports that were only used by the deleted functions (e.g., `useBatchStore`, `useConversationStore`, `useRunHistoryStore` if they were only imported for `switchBatchRun`).

**Step 6: Verify compile**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors (verify nothing else imports the removed exports)

**Step 7: Commit**

```
refactor: remove legacy batch dispatch code from useWorkflowEvents
```

---

## Task 8: Integration test — run a benchmark end-to-end

**Files:**
- No new files (manual verification)

**Why:** Ensure the full flow works: create benchmark → run → WS events flow to scoped stores → results collected → comparison view shows data.

**Step 1: Start the backend**

Run: `python -m uvicorn server.app:app --host 0.0.0.0 --port 8000`

**Step 2: Start frontend dev server**

Run: `cd frontend && npm run dev`

**Step 3: Manual test flow**

1. Open `http://localhost:3000`
2. In the sidebar, verify benchmarks section shows user's benchmarks only
3. Click a benchmark → Runner view appears
4. Select a workflow → Click "Run Benchmark"
5. Verify: progress table shows tasks, status indicators update in real-time
6. Verify: clicking a task shows its conversation/results in the scoped tabs
7. Wait for all tasks to complete
8. Switch to "Compare" tab → verify scores/charts render
9. Switch to "History" tab → verify run history shows

**Step 4: Verify user isolation**

1. With a different user (different API key), verify the other user's benchmarks don't appear
2. Verify the other user's results are not accessible

**Step 5: Build frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors

**Step 6: Commit any remaining fixes**

```
fix(benchmark): integration fixes from end-to-end testing
```

---

## Summary of changes

| Layer | What changes | Risk |
|-------|-------------|------|
| `harness/benchmark_store.py` | Add `user_id` param to `save_benchmark`, `list_benchmarks`, `list_results` | Low — optional params, backward-compatible |
| `server/routes.py` (6 endpoints) | Add `get_current_user()` + ownership checks + pass `user_id` | Low — follows existing pattern from `/runs` |
| `tests/test_benchmark_isolation.py` | New test file | None |
| `BenchmarkRunner.tsx` | Remove global stores, use `WorkflowManager` + `fetchWithAuth` | Medium — core UI change |
| `Sidebar.tsx` | `fetch` → `fetchWithAuth` | Low |
| `BenchmarkCompare.tsx` | `fetch` → `fetchWithAuth` | Low |
| `BenchmarkEditor.tsx` | `fetch` → `fetchWithAuth` | Low |
| `ScopedCenterPanel.tsx` | `fetch` → `fetchWithAuth` | Low |
| `useWorkflowEvents.ts` | Remove legacy `dispatchBatchEvent`, `switchBatchRun`, `setActiveWorkflowId`, `useBatchWorkflowEvents` | Medium — verify no other consumers |
