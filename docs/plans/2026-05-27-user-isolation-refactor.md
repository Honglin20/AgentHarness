# User Isolation Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix user data isolation — every run, conversation, and event is scoped to the authenticated user with no silent "default" fallbacks.

**Architecture:** Four-phase approach: (1) eliminate default fallbacks and fix user_id断链, (2) add user ownership checks to all endpoints, (3) push user filtering down to the storage layer, (4) fix frontend user state management. Each phase is independently deployable.

**Tech Stack:** Python/FastAPI (backend), Zustand/React (frontend), file-based JSON storage (runs)

---

### Task 1: Add user_id parameter to RunStore.list_runs()

**Files:**
- Modify: `harness/run_store.py:62-76`
- Test: `tests/test_run_store.py`

**Step 1: Write the failing test**

Add to `tests/test_run_store.py`:

```python
def test_list_runs_filters_by_user():
    """RunStore.list_runs() filters by user_id when provided."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)

        store.save(
            run_id="run-alice",
            workflow_name="code_review",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
            user_id="alice",
        )
        store.save(
            run_id="run-bob",
            workflow_name="code_review",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
            user_id="bob",
        )
        store.save(
            run_id="run-no-user",
            workflow_name="code_review",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
            # user_id omitted → defaults to "default"
        )

        # alice sees only her run
        alice_runs = store.list_runs(user_id="alice")
        assert len(alice_runs) == 1
        assert alice_runs[0]["run_id"] == "run-alice"

        # bob sees only his run
        bob_runs = store.list_runs(user_id="bob")
        assert len(bob_runs) == 1
        assert bob_runs[0]["run_id"] == "run-bob"

        # None returns all (admin)
        all_runs = store.list_runs()
        assert len(all_runs) == 3


def test_list_runs_combines_user_and_workflow_filter():
    """RunStore.list_runs() can filter by both user_id and workflow_name."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = RunStore(runs_dir=tmpdir)

        store.save(
            run_id="run-1",
            workflow_name="code_review",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
            user_id="alice",
        )
        store.save(
            run_id="run-2",
            workflow_name="research",
            agents_snapshot=[],
            status="completed",
            inputs={},
            result=None,
            user_id="alice",
        )

        alice_cr = store.list_runs(user_id="alice", workflow_name="code_review")
        assert len(alice_cr) == 1
        assert alice_cr[0]["run_id"] == "run-1"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_run_store.py::test_list_runs_filters_by_user tests/test_run_store.py::test_list_runs_combines_user_and_workflow_filter -v`
Expected: FAIL — `list_runs() got an unexpected keyword argument 'user_id'`

**Step 3: Write minimal implementation**

In `harness/run_store.py`, change `list_runs` signature and add user filtering:

```python
def list_runs(
    self,
    workflow_name: str | None = None,
    user_id: str | None = None,
    include_batch: bool = False,
) -> list[dict]:
    runs = []
    for f in self._dir.glob("*.json"):
        try:
            data = json.loads(f.read_text())
            if workflow_name and data.get("workflow_name") != workflow_name:
                continue
            if not include_batch and data.get("batch_id"):
                continue
            if user_id is not None and data.get("user_id", "default") != user_id:
                continue
            runs.append(data)
        except (json.JSONDecodeError, KeyError):
            continue
    runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return runs
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_run_store.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add harness/run_store.py tests/test_run_store.py
git commit -m "feat: add user_id filtering to RunStore.list_runs()"
```

---

### Task 2: Update routes.py list_runs to use RunStore user filtering

**Files:**
- Modify: `server/routes.py:506-510`

**Step 1: Write the failing test**

No new test needed — existing `list_runs` endpoint is tested via integration. We'll verify manually.

**Step 2: Update the route**

In `server/routes.py`, replace lines 506-510:

Before:
```python
persisted = RunStore().list_runs(workflow_name=workflow_name, include_batch=False)
# Filter by user (unless admin)
# Treat missing user_id as "default" for backward compatibility
if not is_admin:
    persisted = [r for r in persisted if r.get("user_id", "default") == user.user_id]
```

After:
```python
persisted = RunStore().list_runs(
    workflow_name=workflow_name,
    include_batch=False,
    user_id=None if is_admin else user.user_id,
)
```

**Step 3: Run existing tests**

Run: `pytest tests/server/test_routes.py -v`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add server/routes.py
git commit -m "refactor: use RunStore user_id filter instead of post-hoc filtering"
```

---

### Task 3: Add user ownership checks to get_run, update_conversation, update_charts

**Files:**
- Modify: `server/routes.py:541-633`

**Step 1: Write the failing test**

No dedicated test file for these endpoints yet. We'll add inline ownership checks and verify with manual testing. The pattern is already established in `delete_run()` (line 452-483).

**Step 2: Add ownership check to get_run**

In `server/routes.py`, modify `get_run` (line 541). Add `request: Request` parameter and user check:

```python
@router.get("/runs/{run_id}", response_model=RunDetail)
async def get_run(run_id: str, request: Request) -> RunDetail:
    """Get a run by id — persisted disk record or live in-memory workflow."""
    from harness.run_store import RunStore
    from harness.user_manager import get_user_manager

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    run = RunStore().get_run(run_id)
    if run:
        if not is_admin and run.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        return {
            "run_id": run.get("run_id"),
            "workflow_name": run.get("workflow_name"),
            "agents_snapshot": run.get("agents_snapshot", []),
            "status": run.get("status"),
            "inputs": run.get("inputs", {}),
            "result": run.get("result"),
            "conversation": run.get("conversation", []),
            "created_at": run.get("created_at", ""),
            "dag": run.get("dag"),
            "chart_groups": run.get("chart_groups"),
            "agent_io": run.get("agent_io"),
            "batch_id": run.get("batch_id"),
            "user_id": run.get("user_id"),
        }

    # Fall back to in-memory live workflow
    repo = get_repository()
    data = repo.get(run_id)
    if data is not None:
        if not is_admin and data.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        workflow = data["workflow"]
        return {
            "run_id": run_id,
            "workflow_name": workflow.name,
            "agents_snapshot": data.get("agents_snapshot", []),
            "status": data["status"],
            "inputs": data.get("inputs", {}),
            "result": data.get("result"),
            "conversation": data.get("conversation", []),
            "created_at": data.get("created_at", ""),
            "dag": repo.get_dag(run_id),
            "chart_groups": None,
            "agent_io": None,
            "batch_id": data.get("batch_id"),
            "user_id": data.get("user_id"),
        }

    raise HTTPException(status_code=404, detail="Run not found")
```

**Step 3: Add ownership check to update_run_conversation**

In `server/routes.py`, modify `update_run_conversation` (line 588):

```python
@router.patch("/runs/{run_id}/conversation")
async def update_run_conversation(run_id: str, request: Request) -> dict:
    """Update conversation messages for a run — persisted or in-memory."""
    from harness.run_store import RunStore
    from harness.user_manager import get_user_manager

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    body = await request.json()
    conversation = body.get("conversation", [])

    store = RunStore()
    run = store.get_run(run_id)
    if run:
        if not is_admin and run.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        run["conversation"] = conversation
        path = store._safe_path(run_id)
        if not path:
            raise HTTPException(status_code=400, detail="Invalid run_id")
        import json
        path.write_text(json.dumps(run, indent=2, ensure_ascii=False))
        return {"status": "ok"}

    repo = get_repository()
    data = repo.get(run_id)
    if data is not None:
        if not is_admin and data.get("user_id", "default") != user.user_id:
            raise HTTPException(status_code=403, detail="Not your run")
        data["conversation"] = conversation
        return {"status": "ok"}

    raise HTTPException(status_code=404, detail="Run not found")
```

**Step 4: Add ownership check to update_run_charts**

In `server/routes.py`, modify `update_run_charts` (line 617):

```python
@router.patch("/runs/{run_id}/charts")
async def update_run_charts(run_id: str, request: Request) -> dict:
    """Update chart_groups snapshot for a persisted run (so Results tab replays)."""
    from harness.run_store import RunStore
    from harness.user_manager import get_user_manager

    user = get_current_user(request)
    user_mgr = get_user_manager()
    is_admin = user_mgr.is_admin(user)

    body = await request.json()
    chart_groups = body.get("chart_groups")
    store = RunStore()
    run = store.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if not is_admin and run.get("user_id", "default") != user.user_id:
        raise HTTPException(status_code=403, detail="Not your run")
    run["chart_groups"] = chart_groups
    path = store._safe_path(run_id)
    if not path:
        raise HTTPException(status_code=400, detail="Invalid run_id")
    import json
    path.write_text(json.dumps(run, indent=2, ensure_ascii=False))
    return {"status": "ok"}
```

**Step 5: Run tests**

Run: `pytest tests/server/test_routes.py -v`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add server/routes.py
git commit -m "fix: add user ownership checks to get_run, update_conversation, update_charts"
```

---

### Task 4: Fix resume_run — pass user_id to runner.submit()

**Files:**
- Modify: `server/routes.py:1224-1284`

**Step 1: Identify the bug**

`resume_run()` (line 1224) never calls `get_current_user(request)` and never passes `user_id` to `runner.submit()` (line 1275-1278). The resumed run's events will lack user_id, and the persisted record will have `user_id="default"`.

**Step 2: Fix resume_run**

In `server/routes.py`, modify `resume_run` to add user context:

```python
@router.post("/runs/{run_id}/resume")
async def resume_run(
    run_id: str,
    request: ResumeRequest,
    http_request: Request,  # rename the FastAPI Request param to avoid shadowing
) -> dict:
```

Wait — the parameter `request` is already the `ResumeRequest` body, and FastAPI injects `Request` separately. Let me check the actual signature.

Actually, looking at line 1224-1228:
```python
async def resume_run(
    run_id: str,
    request: ResumeRequest,
) -> dict:
```

We need to add `req: Request` (FastAPI's Request) as a parameter. Change to:

```python
async def resume_run(
    run_id: str,
    body: ResumeRequest,
    req: Request,
) -> dict:
```

Then inside the function, add user resolution and pass user_id:

After the `repo.get(run_id)` line, add:
```python
    user = get_current_user(req)
    run_user_id = data.get("user_id", user.user_id)
```

And change the `runner.submit()` call (line 1275-1278) to:
```python
    await runner.submit(
        run_id, workflow, data.get("inputs", {}), event_bus,
        config=config, resume=True, user_id=run_user_id,
    )
```

Also update the `workflow.started` emit (line 1266-1272) to include user context:
```python
    with event_bus.with_user_context(run_user_id):
        event_bus.emit("workflow.started", {
            "workflow_id": run_id,
            "name": workflow.name,
            "inputs": data.get("inputs", {}),
            "dag": get_repository().get_dag(run_id),
            "resumed_from": config["configurable"].get("checkpoint_id"),
        })
```

**Step 3: Run tests**

Run: `pytest tests/ -v --ignore=tests/harness/engine/ -m "not slow"`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add server/routes.py
git commit -m "fix: pass user_id in resume_run to prevent default fallback"
```

---

### Task 5: Fix rerun — pass user_id to runner.submit() and repo.put()

**Files:**
- Modify: `server/routes.py:1287-1383`

**Step 1: Identify the bug**

`rerun()` (line 1287) gets the user at line 1309 but:
- `repo.put()` (line 1350-1359) does NOT store `user_id`
- `runner.submit()` (line 1377) does NOT pass `user_id`
- `workflow.started` event (line 1368-1374) does NOT use user context

**Step 2: Fix repo.put to store user_id**

In `server/routes.py`, add `"user_id": user.user_id` to the `repo.put()` dict (after line 1358):

```python
    repo.put(new_id, {
        "workflow": workflow,
        "status": "running",
        "result": None,
        "inputs": inputs,
        "thread_id": new_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "agents_snapshot": _build_agents_snapshot(workflow),
        "event_bus": event_bus,
        "user_id": user.user_id,
    })
```

**Step 3: Fix runner.submit to pass user_id**

Change line 1377:
```python
    await runner.submit(new_id, workflow, inputs, event_bus, config=run_config, user_id=user.user_id)
```

**Step 4: Fix workflow.started emit to use user context**

Wrap the emit (lines 1368-1374):
```python
    with event_bus.with_user_context(user.user_id):
        event_bus.emit("workflow.started", {
            "workflow_id": new_id,
            "name": workflow_name,
            "inputs": inputs,
            "dag": dag_struct,
            "workflow": workflow_name,
        })
```

**Step 5: Run tests**

Run: `pytest tests/ -v --ignore=tests/harness/engine/ -m "not slow"`
Expected: ALL PASS

**Step 6: Commit**

```bash
git add server/routes.py
git commit -m "fix: pass user_id in rerun to repo.put and runner.submit"
```

---

### Task 6: Eliminate "default" fallback in runner._run_workflow()

**Files:**
- Modify: `server/runner.py:241,244`

**Step 1: Identify the bug**

Lines 241 and 244 use `user_id or "default"`, meaning if `user_id` is None (which shouldn't happen after Tasks 4 and 5), events get tagged as "default".

**Step 2: Fix the fallback**

Change lines 241-244 in `server/runner.py`:

Before:
```python
                if resume and config:
                    with event_bus.with_user_context(user_id or "default"):
                        result = await workflow.arun(inputs=None, config=config)
                else:
                    with event_bus.with_user_context(user_id or "default"):
                        result = await workflow.arun(inputs, config=config)
```

After:
```python
                if user_id:
                    _ctx = event_bus.with_user_context(user_id)
                    _ctx.__enter__()

                try:
                    if resume and config:
                        result = await workflow.arun(inputs=None, config=config)
                    else:
                        result = await workflow.arun(inputs, config=config)
                finally:
                    if user_id:
                        _ctx.__exit__(None, None, None)
```

Actually, simpler approach — just remove the `"default"` string and let it be None:

```python
                effective_user = user_id or None
                if effective_user:
                    with event_bus.with_user_context(effective_user):
                        if resume and config:
                            result = await workflow.arun(inputs=None, config=config)
                        else:
                            result = await workflow.arun(inputs, config=config)
                else:
                    if resume and config:
                        result = await workflow.arun(inputs=None, config=config)
                    else:
                        result = await workflow.arun(inputs, config=config)
```

Hmm, that's getting complex. Simpler: just use `user_id` directly (it's already Optional[str]):

```python
                if user_id:
                    ctx = event_bus.with_user_context(user_id)
                    ctx.__enter__()

                try:
                    if resume and config:
                        result = await workflow.arun(inputs=None, config=config)
                    else:
                        result = await workflow.arun(inputs, config=config)
                finally:
                    if user_id:
                        ctx.__exit__(None, None, None)
```

Actually, the simplest correct approach: use `with` but with a guard:

```python
                # Use user context if available; no-op context otherwise
                from contextlib import nullcontext
                ctx = event_bus.with_user_context(user_id) if user_id else nullcontext()
                with ctx:
                    if resume and config:
                        result = await workflow.arun(inputs=None, config=config)
                    else:
                        result = await workflow.arun(inputs, config=config)
```

**Step 3: Run tests**

Run: `pytest tests/ -v --ignore=tests/harness/engine/ -m "not slow"`
Expected: ALL PASS

**Step 4: Commit**

```bash
git add server/runner.py
git commit -m "fix: eliminate default user fallback in runner, use nullcontext when no user"
```

---

### Task 7: Eliminate "default" fallback in WebSocket handler

**Files:**
- Modify: `server/ws_handler.py:153,202,213`

**Step 1: Identify the bug**

Three places in `ws_handler.py` fall back to `"default"`:
- Line 153: `event.get("user_id") or "default"` in `_forward_events_filtered`
- Line 202: `return "default"` in `_resolve_user_id` when no identifier
- Line 213: `return user.user_id if user else "default"` in `_resolve_user_id`

**Step 2: Fix _forward_events_filtered**

In `_forward_events_filtered` (line 150-154), change the event_user_id resolution:

Before:
```python
                event_user_id = (
                    event.get("payload", {}).get("user_id") or
                    event.get("user_id") or
                    "default"
                )
```

After:
```python
                event_user_id = (
                    event.get("payload", {}).get("user_id") or
                    event.get("user_id")
                )
```

Then update the comparison logic. When event has no user_id and the rule is "self", we should NOT deliver (it's an event from before user isolation was fixed — safest to drop):

```python
                if broadcast_rule == "self":
                    if not event_user_id or event_user_id != user_id:
                        continue
```

**Step 3: Fix _resolve_user_id**

Change `_resolve_user_id` to return `None` instead of `"default"`:

```python
    def _resolve_user_id(self, identifier: str | None) -> str | None:
        """从 API Key 或 user_id 解析 user_id. Returns None if unresolvable."""
        if not identifier:
            return None

        from harness.user_manager import get_user_manager
        user_mgr = get_user_manager()
        user = user_mgr.get_user_by_id(identifier)
        if user:
            return user.user_id

        user = user_mgr.get_user(identifier)
        return user.user_id if user else None
```

**Step 4: Update connect() to handle None user_id**

In `connect()` (line 93), when `ws_user_id` is None, use a generated placeholder for connection tracking:

```python
        # If user_id could not be resolved, use a unique anonymous ID
        if not ws_user_id:
            import uuid
            ws_user_id = f"anon-{uuid.uuid4().hex[:8]}"
```

**Step 5: Update batch_websocket_endpoint similarly**

In `batch_websocket_endpoint` (line 288-293), apply the same fix:

```python
    ws_user_id = user_id
    if not ws_user_id:
        ws_user_id = websocket.query_params.get("user_id")
    if not ws_user_id:
        api_key = websocket.headers.get("x-api-key", websocket.headers.get("X-API-Key"))
        ws_user_id = get_connection_manager()._resolve_user_id(api_key)
    if not ws_user_id:
        import uuid as _uuid
        ws_user_id = f"anon-{_uuid.uuid4().hex[:8]}"
```

And update the event_user_id resolution (line 312-316):
```python
            event_user_id = (
                event.get("payload", {}).get("user_id") or
                event.get("user_id")
            )
```

And update the self rule (line 320-321):
```python
            if broadcast_rule == "self":
                if not event_user_id or event_user_id != ws_user_id:
                    continue
```

**Step 6: Run tests**

Run: `pytest tests/server/test_ws_handler.py -v`
Expected: ALL PASS

**Step 7: Commit**

```bash
git add server/ws_handler.py
git commit -m "fix: eliminate default user fallback in WebSocket handler"
```

---

### Task 8: Fix frontend userStore — remove silent default fallback

**Files:**
- Modify: `frontend/src/stores/userStore.ts:48-62`

**Step 1: Identify the bug**

When `initUser()` fails to validate (line 58-60), it silently sets `userId: "default"`. This means the frontend operates as "default" user without the user knowing.

**Step 2: Fix initUser**

Replace lines 48-62 in `frontend/src/stores/userStore.ts`:

Before:
```typescript
  initUser: async () => {
    const storedId = getUserId();
    if (storedId) {
      // Validate against backend
      const user = await getCurrentUser();
      if (user) {
        set({ userId: user.user_id, name: user.name, role: user.role, loaded: true });
        useRunHistoryStore.getState().fetchRuns();
        return;
      }
    }
    // Default state
    set({ userId: "default", name: "Default", role: "developer", loaded: true });
    useRunHistoryStore.getState().fetchRuns();
  },
```

After:
```typescript
  initUser: async () => {
    const storedId = getUserId();
    if (storedId) {
      const user = await getCurrentUser();
      if (user) {
        set({ userId: user.user_id, name: user.name, role: user.role, loaded: true });
        useRunHistoryStore.getState().fetchRuns();
        return;
      }
      // Stored user_id is invalid — clear it so user must re-select
      setUserId("");
    }
    // No valid user — mark loaded but don't set a fake user
    set({ userId: "", name: "", role: "", loaded: true });
    // Don't fetch runs until user is selected
  },
```

**Step 3: Update HeaderBar to show user selector when no user**

The HeaderBar already has a user switcher. When `userId` is empty and `loaded` is true, the existing code should show "Guest" (line 203-211 in HeaderBar.tsx). The user can then select a valid user from the UserSwitcher dialog.

Verify `frontend/src/components/layout/HeaderBar.tsx` handles the empty userId case gracefully (it should show "Guest" or a "Select User" prompt).

**Step 4: Commit**

```bash
git add frontend/src/stores/userStore.ts
git commit -m "fix: remove silent default user fallback in frontend userStore"
```

---

### Task 9: Fix frontend WebSocket — remove default fallback

**Files:**
- Modify: `frontend/src/hooks/useWebSocket.ts:62-64`
- Modify: `frontend/src/hooks/useBatchWebSocket.ts:61-63`

**Step 1: Identify the bug**

Both WebSocket hooks fall back to `"default"` when no userId or apiKey is available:

```typescript
const userId = storedUserId || (apiKey ? getUserFromApiKey(apiKey) : "default");
```

**Step 2: Fix useWebSocket.ts**

Change the userId resolution (around line 62-64):

Before:
```typescript
const userId = storedUserId || (apiKey ? getUserFromApiKey(apiKey) : "default");
```

After:
```typescript
const storedUserId = getUserId();
const apiKey = getApiKey();
let userId = storedUserId;
if (!userId && apiKey) {
  userId = getUserFromApiKey(apiKey);
}
if (!userId) {
  console.warn("[WebSocket] No user context — waiting for authentication");
  return;
}
```

**Step 3: Fix useBatchWebSocket.ts**

Apply the same pattern:

Before:
```typescript
const userId = storedUserId || (apiKey ? getUserFromApiKey(apiKey) : "default");
```

After:
```typescript
let userId = storedUserId;
if (!userId && apiKey) {
  userId = getUserFromApiKey(apiKey);
}
if (!userId) {
  console.warn("[BatchWebSocket] No user context — waiting for authentication");
  return;
}
```

**Step 4: Commit**

```bash
git add frontend/src/hooks/useWebSocket.ts frontend/src/hooks/useBatchWebSocket.ts
git commit -m "fix: remove default user fallback in frontend WebSocket hooks"
```

---

### Task 10: Eliminate default fallback in run_store.save()

**Files:**
- Modify: `harness/run_store.py:55`

**Step 1: Identify the bug**

Line 55: `record["user_id"] = user_id or "default"` — silently assigns "default" when user_id is None.

**Step 2: Fix**

Change line 55:

Before:
```python
        record["user_id"] = user_id or "default"
```

After:
```python
        if user_id:
            record["user_id"] = user_id
```

This means runs without a user_id won't have the field at all (matching old data before user isolation was added). The `list_runs()` filter from Task 1 uses `data.get("user_id", "default")` for backward compat.

**Step 3: Update test**

In `tests/test_run_store.py`, update `test_save_and_list_runs` — the existing runs created without `user_id` should NOT have the field. Update the test assertion in `test_list_runs_filters_by_user` if needed (the `run-no-user` case).

**Step 4: Run tests**

Run: `pytest tests/test_run_store.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add harness/run_store.py tests/test_run_store.py
git commit -m "fix: don't assign default user_id in RunStore.save()"
```

---

### Task 11: End-to-end smoke test

**Files:**
- No code changes

**Step 1: Start the backend**

Run: `python -m uvicorn server.app:app --host 0.0.0.0 --port 8000`

**Step 2: Start the frontend**

Run: `cd frontend && npm run dev`

**Step 3: Verify in browser**

1. Open http://localhost:3000
2. User should NOT be auto-set to "default" — should see "Guest" or user selector
3. Select a user from the user switcher
4. Start a workflow run
5. Verify run appears in sidebar under the selected user
6. Switch to a different user
7. Verify the first user's runs are NOT visible
8. Switch back — verify runs reappear
9. Check browser console for any WebSocket errors

**Step 4: If issues found, add a Task N+1 to fix them**
