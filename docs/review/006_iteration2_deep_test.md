# Iteration 2: Deep E2E Testing

**Date**: 2026-05-27
**Scope**: Live workflow execution, user propagation, resume/rerun access control, WebSocket isolation

---

## Test Results

### 1. Live Workflow Execution with User Tracking

Started workflows for alice and bob, verified full pipeline:

| Step | alice | bob |
|------|-------|-----|
| POST /workflows (start) | ✅ 200 | ✅ 200 |
| Run persisted user_id | alice | bob |
| GET /runs/{id} (own) | ✅ 200 | ✅ 200 |
| GET /runs/{id} (cross) | ✅ 403 | ✅ 403 |
| GET /runs (own list) | 1 run | 1 run |
| Admin sees all | ✅ 24 runs | ✅ 24 runs |

**user_id propagation verified through:**
- `_create_and_start_workflow(user_id=user_id)` → stored in repository
- `runner.submit(user_id=user_id)` → passed to RunStore
- `event_bus.with_user_context(user_id)` → scoped events
- RunStore persistence → `user_id` field in JSON file

### 2. Resume/Rerun Access Control

| Endpoint | alice → alice | bob → alice | admin → alice |
|----------|---------------|-------------|---------------|
| POST /runs/{id}/rerun | ✅ 200 | ⚠️ **200 (BUG)** | ✅ 200 |
| POST /runs/{id}/resume | N/A | ⚠️ **No check** | N/A |
| POST /workflows/{id}/cancel | N/A | ⚠️ **No check** | N/A |

**CRITICAL BUG**: `/runs/{id}/rerun` has NO ownership check:
- Bob successfully reran Alice's run (200)
- Bob's rerun was created with `user_id=bob` but copied Alice's workflow_name, inputs, and agents_snapshot
- Bob can see Alice's workflow configuration and task inputs

**Missing checks also on:**
- `/runs/{id}/resume` — no ownership check (only checks repository existence)
- `/workflows/{id}/cancel` — no ownership check (any user can pause any workflow)

### 3. WebSocket Event Isolation (Code Review)

`ConnectionManager._forward_events_filtered()`:
- ✅ All workflow/node/chat events use `broadcast_rule = "self"`
- ✅ Event user_id compared against WS connection user_id
- ✅ Events from other users are filtered out (`continue`)
- ✅ Batch WebSocket uses same filtering logic
- ✅ Event user_id auto-injected from `event_bus.with_user_context(user_id)`

**Architecture**:
```
Workflow starts → event_bus.with_user_context(alice)
  → emit("node.started", {...}) → auto-inject user_id=alice
    → ConnectionManager checks: event_user_id == ws_user_id
      → alice's WS receives, bob's WS skips
```

### 4. Batch WebSocket Fan-In

`batch_websocket_endpoint`:
- ✅ Same BROADCAST_RULES filtering
- ✅ BatchFanIn aggregates events from multiple workflow runs
- ✅ Per-event user_id filtering prevents cross-user event leakage
- ✅ Batch existence check before accepting WS connection

---

## Issues Found

### Critical (New in Iteration 2)

1. **🔴 /runs/{id}/rerun — No ownership check**
   - **Impact**: Any user can rerun any other user's completed run
   - **Data exposed**: workflow_name, inputs, agents_snapshot, dag
   - **Fix**: Add ownership check before rerun:
     ```python
     run = RunStore().get_run(run_id)
     user = get_current_user(request)
     if not is_admin and run.get("user_id", "default") != user.user_id:
         raise HTTPException(status_code=403, detail="Not your run")
     ```

2. **🔴 /runs/{id}/resume — No ownership check**
   - **Impact**: Any user can resume any paused workflow
   - **Fix**: Check `data.get("user_id")` matches current user

3. **🔴 /workflows/{id}/cancel — No ownership check**
   - **Impact**: Any user can pause any running workflow
   - **Fix**: Check repository data user_id matches current user

### Issues from Iteration 1 (Unchanged)
- ⚠️ Conversation persistence gap (87% runs have no conversation)
- ⚠️ Benchmark user isolation (all users see all benchmarks)
- ⚠️ UserManager staleness (no hot-reload)

---

## Evidence

### Bob's unauthorized rerun
```
Bob → POST /api/runs/6736a384.../rerun
Response: {"workflow_id":"538ffb36...","status":"running","dag":{...}}
Result: user_id=bob, workflow_name=code_review, inputs={alice's task}
```

### alice/bob run isolation
```
alice runs: 1 [7c5ec257] (chart_demo)
bob runs: 1 [06049ad7] (chart_demo)
alice → bob's run: 403
bob → alice's run: 403
default → alice's run: 403
default → bob's run: 403
```

---

**Test completed**: 2026-05-27
