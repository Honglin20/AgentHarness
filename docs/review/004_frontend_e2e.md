# Frontend E2E Review

**Date**: 2026-05-27
**Scope**: Frontend-initiated flows, data completeness, user switching, replay mode

---

## Test Results

### 1. Data Completeness (19 runs for default user)

| Field | Present | Rate |
|-------|---------|------|
| run_id | 19/19 | 100% |
| workflow_name | 19/19 | 100% |
| status | 19/19 | 100% |
| inputs | 19/19 | 100% |
| dag | 19/19 | 100% |
| result | 15/15 completed | 100% |
| **conversation** | **2/15 completed** | **13%** |
| **chart_groups** | **2/15 completed** | **13%** |
| agents_snapshot | 19/19 | 100% |
| user_id | 13/19 | 68% |

### 2. Conversation/Charts Persistence Gap

**Root Cause**: Conversation and charts are built from live WebSocket events in the frontend. They are only saved to the backend when:
1. `workflow.completed` event is received by the frontend
2. The frontend calls `_saveConversation()` / `_saveCharts()`

**Impact**:
- If the frontend was NOT connected during a run → no conversation/charts saved
- If the WebSocket disconnected → incomplete conversation/charts
- If the run was started via API without frontend → no conversation/charts

**13/15 completed runs have no conversation** — these were likely started without the frontend watching.

This is a design limitation, not a bug. But it means the "Replay" feature (viewing completed runs) will show empty conversations for 87% of runs.

### 3. User Switching Flow

Code path (`userStore.switchUser()`):
1. `resetAllStores()` → clears workflowStore, conversationStore, outputStore, chartStore, runHistoryStore, chatStore, toolCallStore, agentIOStore
2. `setUserId(newId)` → updates localStorage
3. `initUser()` → fetches `/api/me` to validate
4. Components re-mount → fetch with new auth headers

✅ **Complete store reset on switch** — prevents cross-user contamination
⚠️ **No cleanup of WebSocket connections** — if a WS is connected to a running workflow, it may not be properly closed on user switch

### 4. Replay Mode

When clicking a completed run:
1. `handleClickRun()` → `selectRun()` + `fetchRun()`
2. `showReplay(run)` → sets `activeView = { type: 'replay', run }`
3. CenterPanel reads `run.conversation` directly (no store involvement)
4. Charts read from `run.chart_groups` directly

✅ **No stacking risk** — replay reads from run record, not from store
⚠️ **Empty replay for 87% of runs** — no conversation was saved

### 5. Live Mode Architecture

**Context Mode** (WorkflowScope):
- Each workflow gets isolated stores via `manager.getOrCreate(workflowId)`
- Events route to correct stores via `routeEventToStores()`
- Batch mode: `selectedRunId` changes `effectiveWorkflowId`
- ✅ Full isolation between concurrent workflows

**Legacy Mode** (global stores + cache):
- Single global stores with per-workflow cache
- `setActiveWorkflowId()` handles save/restore/switch
- ✅ Cache management prevents stacking

### 6. WebSocket Connection

Frontend connects to `/ws/workflows/{workflowId}?user_id={userId}`:
- user_id from `getUserId()` → `getUserFromApiKey()` → warning
- Events filtered by user_id on server side
- ✅ User isolation in WebSocket events

### 7. Benchmark UI

- ✅ Fetches benchmarks via authenticated API
- ✅ Runner component starts batch with user context
- ✅ Compare shows results with scores/charts/history tabs
- ⚠️ All users see all benchmark results (no isolation — see 003_benchmark_e2e.md)
- ✅ Auto-refreshes on batch completion

---

## Issues Found

### High Priority
1. **⚠️ Conversation persistence gap**: 87% of completed runs have no conversation data
   - Conversations only saved when frontend is connected during the run
   - Consider: backend-side conversation capture from workflow events (not just frontend)

### Medium Priority
2. **⚠️ Missing user_id in older runs**: 6/19 runs have `user_id: N/A`
   - Runs created before user isolation refactor don't have user_id
   - These runs fall through to "default" ownership checks

3. **⚠️ No WebSocket cleanup on user switch**
   - If user switches while a workflow is running, the old WebSocket may stay connected
   - Old events could still arrive and be processed

### Low Priority
4. **ℹ️ Chart persistence same gap as conversation** — 87% of runs have no charts
5. **ℹ️ Benchmark compare shows all users' results** — no user filtering

---

## Frontend Architecture Assessment

| Feature | Status |
|---------|--------|
| User authentication | ✅ Working |
| User switching | ✅ Working with store reset |
| Run history isolation | ✅ Working (backend filters) |
| Replay mode | ✅ Working (reads from run record) |
| Live mode isolation | ✅ Working (Context: scoped stores) |
| Batch mode switching | ✅ Working (cache + restore) |
| Conversation stacking | ✅ No issue (replay bypasses store) |
| Conversation persistence | ⚠️ Only when frontend connected |
| Benchmark comparison | ✅ Working (but no user isolation) |

---

**Test completed**: 2026-05-27
