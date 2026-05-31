# Cross-Cutting Review & Iteration Summary

**Date**: 2026-05-27
**Iteration**: Ralph Loop #1 (of max 20)

---

## Overall Assessment

The application has solid user isolation for runs and conversation, with known gaps in benchmark isolation and conversation persistence reliability.

---

## Pass/Fail Summary

| Area | Status | Details |
|------|--------|---------|
| User resolution (API) | ✅ PASS | X-User-Id and X-API-Key both work |
| Run listing isolation | ✅ PASS | Users see only their own runs |
| Run detail access control | ✅ PASS | 403 for non-owners, 200 for owners/admin |
| Conversation update isolation | ✅ PASS | 403 for non-owners |
| Charts update isolation | ✅ PASS | 403 for non-owners |
| Run delete isolation | ✅ PASS | 403 for non-owners |
| Workflow definitions isolation | ✅ PASS | Shared/private/legacy correctly scoped |
| Conversation stacking | ✅ PASS | No stacking in either architecture mode |
| Replay mode rendering | ✅ PASS | Reads from run record, bypasses store |
| WebSocket event isolation | ✅ PASS | User-scoped events |
| Batch mode switching | ✅ PASS | Cache management + isolated stores |
| User switching reset | ✅ PASS | All stores cleared on switch |
| Benchmark CRUD | ✅ PASS | Create, read, update, delete work |
| Benchmark comparison | ✅ PASS | Scores, charts, history tabs functional |
| **Benchmark isolation** | ⚠️ **GAP** | No user ownership on benchmarks/results |
| **Conversation persistence** | ⚠️ **GAP** | 87% of runs have no conversation saved |
| **UserManager staleness** | ⚠️ **OPERATIONAL** | Server restart needed for new users |

---

## Critical Issues (2)

### 1. Conversation Persistence Gap
- **Impact**: 87% of completed runs show empty conversation in replay mode
- **Root Cause**: Conversation built from live WS events; only saved when frontend connected
- **Fix Options**:
  - (a) Backend-side conversation capture from event bus
  - (b) Retroactive conversation generation from result data (outputs, trace)
  - (c) Accept as design limitation and show "No conversation captured" message

### 2. Benchmark User Isolation
- **Impact**: All users see all benchmarks and results
- **Root Cause**: BenchmarkStore has no user_id awareness
- **Fix Options**:
  - (a) Add user_id to benchmark results + filter by user
  - (b) Keep benchmarks as shared resources with user attribution
  - (c) Add ownership checks to benchmark API endpoints

---

## Operational Issues (1)

### UserManager Staleness
- Users added to users.json manually are not picked up by running server
- Must recreate via `POST /api/users` (admin) or restart server
- Consider: auto-reload mechanism (file watcher or API reload endpoint)

---

## Architecture Quality

**Strengths**:
- Clean dual-mode architecture (Legacy + Context)
- Proper ownership checks on all data mutations
- Admin override for all access control
- WebSocket event isolation via user context
- Batch mode with cache management prevents cross-run contamination

**Areas for Improvement**:
- Conversation persistence reliability
- Benchmark ownership model
- UserManager hot-reload
- Duplicate code (formatOutputAsMd in 3 places)

---

## Files Reviewed

| File | Key Findings |
|------|-------------|
| server/routes.py | All endpoints have user checks; benchmark endpoints lack isolation |
| harness/user_manager.py | Default fallback; no auto-reload |
| frontend/src/lib/api.ts | Clean auth header injection; empty string fallback for missing userId |
| frontend/src/stores/conversationStore.ts | Cache management prevents stacking |
| frontend/src/stores/runHistoryStore.ts | Relies on backend filtering |
| frontend/src/stores/viewStore.ts | showReplay populates agentIO but not conversation |
| frontend/src/hooks/useWorkflowEvents.ts | Legacy mode cache + clear; saveConversation only if messages exist |
| frontend/src/contexts/workflow-context/WorkflowScope.tsx | Isolated stores per workflow |
| frontend/src/contexts/workflow-context/eventRouter.ts | Context mode event routing |
| frontend/src/components/layout/CenterPanel.tsx | Replay reads from run record |
| frontend/src/components/layout/ScopedCenterPanel.tsx | Context mode panel with replay support |
| frontend/src/components/benchmark/BenchmarkCompare.tsx | No user filtering |
| harness/benchmark_store.py | No user_id in results |

---

**Review completed**: 2026-05-27
**Next iteration**: Deep-dive on specific failure scenarios, edge cases, race conditions
