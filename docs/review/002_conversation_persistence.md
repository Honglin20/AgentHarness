# Conversation Persistence & Isolation Review

**Date**: 2026-05-27
**Scope**: Conversation CRUD, isolation, stacking risk, batch mode switching

---

## Architecture Summary

### Two Modes

1. **Legacy Mode** (single global stores + per-workflow cache)
2. **Context Mode** (isolated stores per workflow via WorkflowManager)

### Conversation Data Flow

```
Live Run:
  WebSocket events → conversationStore (or scoped store) → UI renders
  On complete → _saveConversation() → PATCH /api/runs/{id}/conversation

Replay Run:
  Click history → fetchRun() → showReplay(run) → activeView.run.conversation → UI renders
  (Does NOT use conversationStore at all!)

Batch Switching:
  Legacy: saveToCache() → switchBatchRun() → restoreFromCache() or _restoreConversation()
  Context: WorkflowScope changes effectiveWorkflowId → new isolated stores auto-created
```

---

## Test Results

### 1. Conversation Save (backend)
- ✅ `PATCH /api/runs/{id}/conversation` with owner: 200
- ✅ `PATCH /api/runs/{id}/conversation` with non-owner: 403
- Verified in 001_backend_api_isolation.md

### 2. Conversation Stacking Risk
- ✅ **Replay mode**: Reads directly from `activeView.run.conversation` (CenterPanel:86-102, ScopedCenterPanel:115-130)
  - Does NOT involve conversationStore at all
  - No stacking possible
- ✅ **Live mode (Context)**: Uses isolated stores per workflow via WorkflowManager.getOrCreate()
  - Each workflow has its own store instance
  - Switching runs creates/switches to different store instances
  - No cross-contamination possible
- ✅ **Live mode (Legacy)**: Uses saveToCache/restoreFromCache with explicit message clearing
  - Line 360: `useConversationStore.setState({ messages: [], ... })` before async restore
  - Race condition protection in `_restoreConversation()`: only loads if `current.length === 0`

### 3. Conversation Persistence on Complete
- ✅ `_saveConversation()` called on `workflow.completed`, `workflow.error`, `workflow.cancelled`
- ✅ Context mode: `saveConversation()` in eventRouter.ts does same via scoped stores
- ✅ `_saveCharts()` also called alongside conversation save

### 4. Conversation Restore on History Switch
- ✅ Legacy: `_restoreConversation()` fetches from `/api/runs/{id}` and loads into store
- ✅ Context: Replay mode reads directly from `activeView.run.conversation` (no store loading needed)
- ⚠️ **Context mode gap**: No mechanism to load conversation into scoped stores for completed runs viewed in "live" mode
  - But this is not a practical issue because completed runs always use replay mode (showReplay)

### 5. Batch Mode Conversation Isolation
- ✅ Context mode: `WorkflowScope` uses `selectedRunId` as `effectiveWorkflowId`
  - Switching batch runs changes the effective workflow ID
  - Each workflow gets its own isolated store set
- ✅ Legacy mode: `switchBatchRun()` saves current, restores new, or fetches from backend
- ✅ Non-selected batch run events cached in `_cache` (Legacy) or routed to correct stores (Context)

---

## Issues Found

### No Stacking Issue
The conversation stacking concern is **NOT present** in either architecture:
- Replay mode (completed runs) reads directly from run records, bypassing stores entirely
- Live mode has proper isolation (Context: separate stores, Legacy: cache + explicit clearing)

### Minor Issues
1. ⚠️ **Context mode: no explicit conversation loading for scoped stores of completed runs**
   - Impact: Low - completed runs always use replay mode which reads from run records
   - If someone tried to use scoped stores for replay, conversation would be empty

2. ⚠️ **Legacy mode: race condition window**
   - Between clearing messages (line 360) and `_restoreConversation()` completing
   - Mitigated by `if (current.length === 0)` guard in restore function
   - New events from a different WebSocket could theoretically arrive during window

---

## Backend Conversation Isolation (verified)

| Operation | Owner | Non-owner | Admin |
|-----------|-------|-----------|-------|
| GET run (includes conversation) | 200 | 403 | 200 |
| PATCH conversation | 200 | 403 | N/A |
| PATCH charts | N/A | 403 | N/A |

---

**Test completed**: 2026-05-27
