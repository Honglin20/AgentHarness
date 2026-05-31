# Comprehensive Code Review — Full System Audit

**Date**: 2026-05-27
**Branch**: fix/context-architecture-ws-lifecycle
**Scope**: Frontend (all components, stores, events) + Backend (all API, WebSocket, engine, extensions)

---

## Executive Summary

| Severity | Count | Description |
|----------|-------|-------------|
| 🔴 Critical | 6 | Must fix before merge |
| ⚠️ Important | 12 | Should fix, functional impact |
| 💡 Suggestion | 15 | Nice to have, code quality |

### Critical Issues Summary

1. **`fetchWithAuth` not used in ScopedCenterPanel, ChatInput, Sidebar, Benchmark** — Auth headers missing on 15+ API calls
2. **DAG edit button `stopPropagation` blocks all editing** — DAGPreviewNode edit button dead
3. **`macro_graph.py:695` closure captures wrong variable** — `agent.on_fail` instead of `agent_def.on_fail`
4. **`llm_executor.py:223-224` tool_result key mismatch** — `"tool_result"` guard but `"result"` storage
5. **UserManager missing methods** — `list_users()`, `create_user()`, `delete_user()`, `get_user_by_id()` not defined
6. **`workflow.started` emitted outside user context** — Frontend never receives `workflow.started` event

---

## Phase G: Current Branch Changes

### G1: Context Architecture WS Lifecycle ✅ PASS

| Check | Status |
|-------|--------|
| No global variables (`__wsMethods`, `__useContextArchitecture`) | ✅ |
| WS lifecycle stability (WorkflowCenterPanel stable parent) | ✅ |
| React Context correct (WSMethodProvider wraps WorkflowScope) | ✅ |
| No stale closures in sendAnswer/sendStopAndRegenerate | ✅ |
| TypeScript build passes | ✅ |

**Suggestions:**
- Remove dead code: `useScopedWorkflowEvents` in context/useWorkflowEvents.ts is unused
- Convert `require()` to `next/dynamic` in WorkflowCenterPanel.tsx:56

### G2: ChatInput Scoped Store Injection ✅ PASS

| Check | Status |
|-------|--------|
| React hooks rules (all called unconditionally) | ✅ |
| Prop priority logic (correct `null` handling) | ✅ |
| Dependency arrays complete | ✅ |
| Three interaction modes correct | ✅ |
| Cancel/Resume use raw `fetch` | 🔴 (pre-existing) |

**🔴 Bug (pre-existing):** `ChatInput.tsx:116,134` uses raw `fetch` instead of `fetchWithAuth` for cancel/resume.

### G3: Collectors Backend Persistence ✅ PASS

| Check | Status |
|-------|--------|
| ConversationCollector logic | ✅ |
| ChartCollector output shape | ✅ |
| Integration in runner.py | ✅ |
| Tests pass (9/9) | ✅ |
| `build_conversation()` test coverage | 🔴 **Zero tests for production path** |

**⚠️ Important:** `build_conversation()` — the actual function called by runner.py — has zero test coverage. Only the Bus-buffer ConversationCollector is tested.

---

## Phase B: Frontend State & Events

### B1: Zustand Stores ⚠️ Issues Found

| Store | Status | Issues |
|-------|--------|--------|
| workflowStore | ⚠️ | Direct `_cache` mutation in `saveToCache:186` |
| conversationStore | 🔴 | Direct state mutation in cache methods (355-429); `msgCounter` reset causes ID reuse (302) |
| toolCallStore | ✅ | Minor: ID counter reset risk |
| outputStore | ⚠️ | Direct `_cache` mutation in `saveToCache:67` |
| chartStore | ✅ | Clean |
| chatStore | ✅ | Clean |
| agentIOStore | ✅ | Clean |
| batchStore | ✅ | Clean |
| viewStore | ⚠️ | Cross-store side effect in `showReplay:20-25` |
| runHistoryStore | ⚠️ | Silent error swallowing (101) |

**🔴 Critical:** `conversationStore.ts:355-429` — `appendAgentTextToCache`, `addToolCallToCache`, `addToolResultToCache` directly mutate `state._cache[wid]` before calling `set()`, violating Zustand immutability contract.

### B2: Legacy Event Routing ⚠️ Issues Found

| Check | Status |
|-------|--------|
| Event type coverage (14/14 server-to-client) | ✅ |
| `node.completed` fallback logic | 🔴 Stale index captured outside setState |
| Batch cache updates for non-selected runs | ⚠️ Missing workflow-level status caching |
| `_restoreConversation` | ⚠️ Silent errors; missing field mapping |
| Exhaustiveness check | ⚠️ No `default` case in switch |

**🔴 Bug:** `useWorkflowEvents.ts:202-234` — Array index captured from `getState()` then used inside `setState()` callback. Concurrent events can make the index stale.

### B3: Context Architecture Event Routing ⚠️ Issues Found

| Check | Status |
|-------|--------|
| Logic parity with legacy routing | ✅ (intentional diffs are correct) |
| Store access keys match factory | ✅ |
| `saveConversation`/`saveCharts` use raw `fetch` | 🔴 |
| Batch dispatch parity | ⚠️ Missing non-selected run cache |
| No missing event types | ✅ |

**🔴 Bug:** `eventRouter.ts:85,101` — `saveConversation` and `saveCharts` use raw `fetch` instead of `fetchWithAuth`. Auth-enabled deployments will silently fail.

### B4-B6: WS Hooks, WorkflowManager, Stores Factory ✅ PASS

All pass with suggestions:
- `useWebSocket` and `useBatchWebSocket` share ~100 lines of duplicate code
- `WorkflowManager.dispatchEvent` is dead code with TODO
- `workflowStores.ts` has dead stub methods (85-148)
- Message ID double-prefix: `msg-msg-1` instead of `msg-1`

---

## Phase A: Frontend UI Components

### A1: Landing Page 🔴 Bug Found

**🔴 Critical:** `ScopedCenterPanel.tsx` uses raw `fetch()` on lines 163, 175, 185, 192, 212 — no auth headers. Should use `fetchWithAuth`.

**⚠️:** Template state typed as `any[]` (line 66); multiple `(selectedTemplate as any)` casts.

### A2: Conversation Tab ✅ PASS

All checks pass:
- Message type grouping correct
- Auto-scroll and auto-collapse working
- Scoped version uses context stores correctly
- AgentMessage IO panel reads from scoped or global stores

**💡 Suggestion:** `groupMessages` function duplicated in ConversationTab and ScopedConversationTab.

### A3: Chat Interactions 🔴 Bug (same as G2)

Cancel/resume use raw `fetch` — covered in G2.

### A4: DAG Preview 🔴 Bug Found

**🔴 Critical:** `DAGPreviewNode.tsx:26` — Edit button's `onClick` calls `e.stopPropagation()` without triggering edit. Actively blocks the parent's `onNodeClick` handler. **DAG node editing is broken.**

✅ Dagre layout, conditional edge labels, and mini-map all correct.

### A5: Charts ✅ PASS

- `filterGroupsByCategory` correct
- All 11 chart type components exist
- Scoped versions read from context stores
- Replay mode reads from run.chart_groups

**💡 Suggestion:** `ChartGroupCollection.tsx` and `ChartGroup.tsx` are dead code (not imported anywhere).

### A6: Sidebar ⚠️ Auth Issue

**⚠️ Important:** `RunHistoryList.tsx` (lines 39, 116, 132, 145) and `Sidebar.tsx` (line 30) use raw `fetch`. Same `fetchWithAuth` issue.

✅ Run grouping, status icons, and agent browser all correct.

### A7: Benchmark ⚠️ Auth Issue

**⚠️ Important:** All benchmark components use raw `fetch` (BenchmarkRunner:44,77,87; BenchmarkCompare:44).

✅ Runner, Editor, and Compare flows all functionally correct.

**💡 Suggestion:** `BenchmarkCompare` ChartsTab only renders 2 of 11 chart types.

### A8: Diagnostics ✅ PASS

All checks pass:
- Three tabs work correctly
- Live mode reads from stores, replay derives from run record
- Trace shows timing and tokens

**⚠️:** Replay node status mapping is lossy (non-success → "failed"). Replay tool call timestamps default to epoch (0).

---

## Phase C: Backend REST API

### C1: Authentication & Permissions 🔴 Bug Found

**🔴 Critical:** `UserManager` missing methods: `list_users()`, `create_user()`, `delete_user()`, `get_user_by_id()`. Routes.py calls these (lines 62, 70, 84, 96, 100) but they don't exist. **3 user management endpoints crash at runtime.**

✅ Invalid key fallback to default user works correctly.
✅ No global auth middleware (by design).

### C2: Workflow CRUD ✅ PASS

- Concurrent limit (max 50): ✅
- Cancel/Resume ownership checks: ✅
- DAG caching: ✅
- Definitions user isolation: ✅

**⚠️:** Batch/benchmark endpoints bypass API-layer capacity check.

### C3: Run Management ✅ PASS

- Run listing isolation: ✅
- Run detail access control: ✅
- DELETE/PATCH/Rerun ownership: ✅
- Conversation/chart persistence: ✅

### Other Backend Findings

**🔴 Critical:** `POST /api/config` (line 174) has **no authentication**. Any unauthenticated caller can change API key and model.

**🔴 Critical:** `workflow.started` emitted outside user context (`routes.py:764`). Since `BROADCAST_RULES["workflow.started"] == "self"`, the event has no `user_id` and is **silently discarded** by all WebSocket subscribers. Frontend never receives `workflow.started`.

**⚠️ Important:** 12 endpoints lack authentication (GET /api/config, POST /api/config, GET /api/tools, POST /api/charts, GET /api/workflows/{id}, GET dag/trace/checkpoints, all 6 benchmark endpoints, GET /api/batch/{id}).

---

## Phase D: Backend WebSocket + Runner

### D1: WebSocket Event Filtering 🔴 Bug Found

**🔴 Critical:** `ws_handler.py:170,332` calls `user_mgr.get_user_by_id()` which doesn't exist on UserManager. If any "admin" broadcast rule event fires, the entire WebSocket connection dies.

✅ BROADCAST_RULES correctly defined.
✅ Message handling (chat.answer, stop_and_regenerate) correct.

**⚠️:** Incoming WS messages not authenticated — any connection can send chat.answer or stop_and_regenerate.

### D2: Batch WebSocket ✅ PASS

- BatchFanIn merging: ✅
- Per-run user filtering: ✅
- batch.completed synthesis: ✅

**⚠️:** No ownership check on batch WebSocket connection.

### D3: Runner ✅ PASS

- Concurrent control (semaphore): ✅
- Cancel with 2s timeout: ✅
- work_dir security (deny-list): ✅
- Cleanup (cwd restore, MCP disconnect): ✅
- Run persistence: ✅

---

## Phase E: Core Engine

### E1: DAG Compilation ✅ PASS

- Topological sort: ✅
- Cycle detection: ✅
- Missing dependency detection: ✅
- Conditional edges excluded from cycle check: ✅

### E2: Macro Graph 🔴 Bug Found

**🔴 Critical:** `macro_graph.py:695` — `agent.on_fail` should be `agent_def.on_fail`. Closure captures loop variable instead of parameter. Causes wrong `on_fail` target for all nodes except the last.

✅ Conditional edge routing, passthrough nodes, stop-and-regenerate all correct.

### E3: Micro Agent + LLM Executor 🔴 Bug Found

**🔴 Critical:** `llm_executor.py:223-224` — Guard checks `"tool_result" not in tc` but stores as `tc["result"]`. Deduplication logic never works. Test fails: `test_tool_calls_collected`.

✅ Micro agent prompt construction and streaming correct.
✅ LLM client DeepSeek compatibility correct.

### E4: Public API ⚠️ Bug Found

**⚠️ Important:** `api.py:332` — `for dep in a.after:` crashes with `TypeError: 'NoneType' object is not iterable` when `a.after is None` (conditional-only nodes in private workflows).

✅ Agent/Workflow definitions, run/arun, save/load all correct.

---

## Phase F: Extension System

### F1: EventBus (Bus) ✅ PASS

- WS client management: ✅
- Hook concurrent execution: ✅
- Middleware chain: ✅
- User context injection: ✅

**⚠️:** Singleton pattern makes test isolation hard.

### F2: Eval Judge ✅ PASS

- GraphMutator logic: ✅
- Conditional edge routing: ✅
- Score extraction: ✅

**⚠️:** Duplicate file: `judge.py` is dead code (only `decisions.py` is imported).
**⚠️:** Double chart emission — both macro_graph and EvalChartPlugin emit chart.render.

### F3: Plugins ✅ PASS

- AgentTracePlugin: ✅
- EvalChartPlugin: ✅
- PerfMetricsPlugin: ✅

---

## Test Results

```
tests/engine/ + tests/harness/: 59 passed, 1 failed

Failed: tests/harness/engine/test_llm_executor.py::test_tool_calls_collected
  Cause: Key mismatch ("tool_result" vs "result") — tracked as E3 bug
```

---

## Prioritized Action Items

### 🔴 Critical (Must Fix Before Merge)

| # | Issue | File | Line |
|---|-------|------|------|
| 1 | `fetchWithAuth` missing on 15+ API calls | ScopedCenterPanel, ChatInput, RunHistoryList, Sidebar, BenchmarkRunner, BenchmarkCompare, eventRouter | Multiple |
| 2 | DAG edit button blocks all editing | DAGPreviewNode.tsx | 26 |
| 3 | Closure captures wrong variable (`agent` vs `agent_def`) | macro_graph.py | 695 |
| 4 | Tool result key mismatch (`"tool_result"` vs `"result"`) | llm_executor.py | 223-224 |
| 5 | UserManager missing methods (runtime crash) | user_manager.py | N/A |
| 6 | `workflow.started` never reaches frontend | routes.py | 764 |

### ⚠️ Important (Should Fix)

| # | Issue | File | Line |
|---|-------|------|------|
| 7 | Direct state mutation in conversationStore cache | conversationStore.ts | 355-429 |
| 8 | Stale index in node.completed fallback | useWorkflowEvents.ts | 202-234 |
| 9 | `POST /api/config` unauthenticated | routes.py | 174 |
| 10 | `api.py` list_saved crashes on `after=None` | api.py | 332 |
| 11 | `build_conversation()` has zero test coverage | collectors.py | 226-306 |
| 12 | 12 endpoints lack authentication | routes.py | Multiple |
| 13 | `msgCounter` reset causes ID reuse | conversationStore.ts | 302 |
| 14 | Batch cache missing workflow-level events | useWorkflowEvents.ts | 462-484 |
| 15 | Batch/benchmark bypass capacity pre-check | routes.py | 817, 967 |
| 16 | Duplicate `judge.py` dead code + double chart emit | extensions/eval/ | Multiple |
| 17 | Direct `_cache` mutation in workflowStore, outputStore | workflowStore.ts, outputStore.ts | 186, 67 |
| 18 | Replay status mapping lossy in DiagnosticsPanel | DiagnosticsPanel.tsx | 36 |

### 💡 Suggestions (Nice to Have)

| # | Issue |
|---|-------|
| 19 | Extract shared `useBaseWebSocket` hook (~100 lines saved) |
| 20 | Remove dead code: `useScopedWorkflowEvents`, `ChartGroupCollection`, `ChartGroup`, `judge.py` |
| 21 | Fix message ID double-prefix (`msg-msg-1`) |
| 22 | Extract `groupMessages` to shared utility |
| 23 | Add exhaustiveness check to event switch statements |
| 24 | Remove dead stub methods in `workflowStores.ts` (85-148) |
| 25 | Convert `require()` to `next/dynamic` or static import |
| 26 | Deduplicate `WorkflowStores` type exports |
| 27 | Support all chart types in BenchmarkCompare ChartsTab |
| 28 | Handle replay tool call timestamps gracefully |
| 29 | Add WebSocket incoming message authentication |
| 30 | Log errors instead of silent catch in restore/fetch functions |
| 31 | Type templates properly instead of `any[]` in ScopedCenterPanel |
| 32 | Remove dead `dispatchEvent` TODO in WorkflowManager |
| 33 | Replace duck-typing with discriminated union in `updateNodeInCache` |

---

**Review completed**: 2026-05-27
**Total findings**: 33 (6 Critical, 12 Important, 15 Suggestions)
