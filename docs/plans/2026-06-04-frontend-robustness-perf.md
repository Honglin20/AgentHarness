# Frontend Robustness + Performance Plan

## Context

Frontend has two categories of problems:
1. **Correctness bugs** — conversation overlap when switching runs, history disappearing after refresh, stale data leaking between runs
2. **Performance degradation** — slow rendering with 100+ messages, unnecessary re-renders, uncompressed API responses

Root causes:
- `viewStore.showReplay()` has **no request sequencing** — async callbacks from stale requests overwrite current state
- **Global stores + scoped stores coexist** — backward compat writes to global `agentIOStore` leak data across runs
- **Zero virtualization** — ConversationTab renders all messages as DOM nodes
- **No memoization** — only 2 of ~30 components use React.memo
- **No compression** — FastAPI sends uncompressed JSON, no pagination
- **No client cache** — every sidebar click fetches fresh data

---

## Phase 0: Race Condition Elimination (P0, ~3h)

### 0.1 — Request sequencing in viewStore

**File:** `frontend/src/stores/viewStore.ts`

Add a monotonic counter outside the store. In `showReplay`, capture the counter value. In the async `Promise.all().then()` callback, check if the counter still matches — if not, discard the result.

```ts
let _replaySeq = 0;

showReplay: (run) => {
  const seq = ++_replaySeq;
  // ... existing sync setup ...

  if (needsLazyLoad) {
    set({ chartsLoading: true });
    Promise.all([...]).then(([charts, events]) => {
      if (seq !== _replaySeq) return; // stale — discard
      doReplay(charts, events);
    });
  } else {
    doReplay(run.chart_groups, run.events);
  }
}
```

**Risk:** LOW. Purely additive guard. If the counter is stale, we simply skip the state update.

### 0.2 — AbortController for sidebar clicks

**File:** `frontend/src/stores/runHistoryStore.ts`
**File:** `frontend/src/components/sidebar/RunHistoryList.tsx`

1. Add an `AbortController` ref to the store (or a module-level variable).
2. In `fetchRun`, accept an optional `AbortSignal`.
3. In `handleClickRun`, before calling `fetchRun`, abort the previous request:

```ts
const abortRef = useRef<AbortController | null>(null);

const handleClickRun = async (run) => {
  abortRef.current?.abort();
  const ac = new AbortController();
  abortRef.current = ac;

  const full = await fetchRun(run.run_id, ac.signal);
  if (!full || ac.signal.aborted) return; // stale or cancelled
  // ... rest of logic
};
```

**Risk:** LOW. AbortController is standard Web API.

### 0.3 — Guard showReplay against stale run data

**File:** `frontend/src/stores/viewStore.ts`

In `doReplay`, check that the run being replayed is still the intended one:

```ts
const doReplay = (...) => {
  if (seq !== _replaySeq) return; // double-check inside async boundary
  // ... proceed with store population ...
};
```

**Verification:**
- Click Run A, immediately click Run B → only B's data appears, no flicker
- Click Run A, wait for load, click Run B → B loads correctly
- Rapid clicking through 5+ runs → final click's data is displayed, no overlap

---

## Phase 1: Global Store Cleanup (P0, ~2h)

### 1.1 — Remove global agentIOStore write from showReplay

**File:** `frontend/src/stores/viewStore.ts`

Delete lines 26-30 (the backward compat block that writes to global `useAgentIOStore`). All consumers in the scoped path use scoped stores via `WorkflowManager`. The legacy `ConversationTab` + `useWorkflowEvents` path gets its data from `_routeToUIStores`, not from this write.

Replace with a reset: `useAgentIOStore.getState().reset()` — clears any stale data.

**Risk:** LOW. Verified that:
- Scoped path reads from scoped stores only
- Legacy path writes via `_routeToUIStores` independently
- No component in the scoped path reads global `agentIOStore` directly

### 1.2 — Guard global cache writes in setActiveWorkflowId

**File:** `frontend/src/hooks/useWorkflowEvents.ts`

In the `setActiveWorkflowId` function (lines 399-435), add a guard: if `WorkflowManager` has an active scoped workflow for this ID, skip the global cache manipulation. Only set the WorkflowManager's active ID.

**Risk:** MEDIUM. This affects batch mode cache save/restore. Must test:
- Batch mode: start benchmark, switch between tasks, verify conversation
- Single workflow: start, pause, resume — verify no state leak

**Verification:** Run a single workflow to completion → click a historical run → click another → no stale agentIO data visible.

---

## Phase 2: Rendering Performance (P1, ~8h)

### 2.1 — React.memo on leaf components (~2h)

**Files:**
- `frontend/src/components/conversation/AgentMessage.tsx` (AgentNodeHeader, ThinkingBlock)
- `frontend/src/components/conversation/UserMessage.tsx`
- `frontend/src/components/conversation/SystemMessage.tsx`
- `frontend/src/components/conversation/ToolCallMessage.tsx` (already has memo — verify)
- `frontend/src/components/conversation/MarkdownText.tsx` (already has memo — verify)
- `frontend/src/components/conversation/AgentQuestionCard.tsx`

Wrap each with `React.memo()`. For `AgentNodeHeader`, use custom comparator checking only `message.status`, `message.content`, `collapsed`, `sectionItemCount`, `agentIOData[nodeId]`, `nodes[nodeId]`.

**Risk:** LOW. memo only affects re-render frequency.

### 2.2 — Consolidate store subscriptions with useShallow (~2h)

**File:** `frontend/src/components/sidebar/RunHistoryList.tsx`
**File:** `frontend/src/components/layout/CenterPanel.tsx`

Use `useShallow` from `zustand/shallow` (already imported in `hooks.ts`) to batch subscriptions:

```ts
import { useShallow } from "zustand/shallow";

// Before: 18 subscriptions → 18 potential re-renders
// After: 1 subscription → 1 re-render when any value changes
const { runs, loading, selectedRunId, ... } = useRunHistoryStore(
  useShallow(s => ({
    runs: s.runs,
    loading: s.loading,
    selectedRunId: s.selectedRunId,
    // ...
  }))
);
```

Also move computed selectors (e.g., `Object.keys(s.nodes).length`) into `useMemo`:

```ts
const nodeCount = useMemo(
  () => Object.keys(workflowNodes).length,
  [workflowNodes]
);
```

**Risk:** LOW. useShallow is standard Zustand utility.

### 2.3 — Virtualize conversation messages (~3h)

**File:** `frontend/src/components/conversation/ScopedConversationTab.tsx`

Install `@tanstack/react-virtual`:
```bash
cd frontend && npm install @tanstack/react-virtual
```

Replace the `blocks.map(...)` with `useVirtualizer`:
- Scroll container = existing `div[ref=scrollRef]`
- Estimated size: 80px for collapsed nodes, 200px for expanded
- Keep `bottomRef` auto-scroll → `virtualizer.scrollToIndex(blocks.length - 1)`
- Dynamic measurement via `measureElement` for accurate sizing after render

**Risk:** MEDIUM. Virtualization changes DOM structure. Must verify:
- Auto-scroll works during streaming (scrollToIndex on new messages)
- Manual scroll up works and doesn't jump
- Tool call expand/collapse doesn't break layout
- Question cards remain interactive

### 2.4 — RAF-batched streaming updates (~1h)

**File:** `frontend/src/stores/conversationStore.ts`

Buffer `appendAgentText` deltas and flush via `requestAnimationFrame`:

```ts
let _textBuf = new Map<string, { text: string; nodeId: string }>();
let _rafPending = false;

appendAgentText: (nodeId, text) => {
  _textBuf.set(nodeId, { text: (_textBuf.get(nodeId)?.text ?? "") + text, nodeId });
  if (!_rafPending) {
    _rafPending = true;
    requestAnimationFrame(() => {
      const updates = new Map(_textBuf);
      _textBuf.clear();
      _rafPending = false;
      set((state) => {
        const messages = [...state.messages];
        for (const [, { nodeId: nid, text: t }] of updates) {
          const idx = messages.findLastIndex(m => m.nodeId === nid && m.type === "agent" && m.status === "streaming");
          if (idx !== -1) messages[idx] = { ...messages[idx], content: messages[idx].content + t };
        }
        return { messages };
      });
    });
  }
}
```

Add sync flush before `completeAgentMessage`, `addToolCall`, and `failAgentMessage` to prevent text loss.

**Risk:** MEDIUM-HIGH. Timing changes. Must verify streaming cursor is smooth and no text is lost at message boundaries.

**Phase 2 Verification:**
- React DevTools Profiler: streaming text should cause ~60 re-renders/sec (not ~200)
- Load run with 200+ messages → DOM node count should stay ~30-40 visible rows
- Tool call expand/collapse should not cause other rows to shift unexpectedly

---

## Phase 3: Data Loading Optimization (P1, ~4h)

### 3.1 — GZip compression middleware (~0.5h)

**File:** `server/app.py`

```python
from starlette.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
```

Place after CORS middleware. Reduces JSON response sizes by 60-80%.

**Risk:** LOW. Standard middleware.

### 3.2 — Client-side run cache (~1h)

**File:** `frontend/src/stores/runHistoryStore.ts`

Add `_runCache: Map<string, { data: RunRecord; ts: number }>` to store state.

In `fetchRun`:
1. Check cache. If entry exists and `< 30s` old, return cached data.
2. After successful fetch, store in cache.
3. `clearRunCache()` action for invalidation after rerun/resume/delete.

**Risk:** LOW. 30s TTL is conservative. User can always force-refresh.

### 3.3 — Compact JSON storage (~0.5h)

**File:** `harness/run_store.py`

Change all `json.dumps(record, indent=2, ...)` to `json.dumps(record, separators=(',', ':'), ensure_ascii=False)`.

~30% file size reduction. JSON is still valid — just not pretty-printed.

**Risk:** LOW. JSON files become harder to read manually, but that's what the UI is for.

### 3.4 — Pagination on list endpoint (~2h)

**File:** `server/routes.py` — `list_runs` endpoint
**File:** `harness/run_store.py` — `list_runs` method
**File:** `frontend/src/stores/runHistoryStore.ts` — `fetchRuns`
**File:** `frontend/src/components/sidebar/RunHistoryList.tsx`

Backend:
- Add `limit` (default 50) and `offset` (default 0) query params
- Return `{ runs: [...], total: int, has_more: bool }` instead of bare array

Frontend:
- Update `fetchRuns` to handle new shape
- Show "Load more" button when `has_more` is true
- Append to existing `runs` array on load-more

**Risk:** MEDIUM. API contract change. Frontend must handle both shapes during transition.

**Phase 3 Verification:**
- `curl -H "Accept-Encoding: gzip" -v http://localhost:8000/api/runs` → Content-Encoding: gzip
- Click same run twice → second click instant (cache hit)
- Create 60+ runs → sidebar shows 50, "Load more" loads next batch

---

## Phase 4: State Persistence (P2, ~1h)

### 4.1 — Harden URL state restoration

**File:** `frontend/src/hooks/useUrlState.ts`

The existing `useUrlState` already syncs `activeView` → URL params and restores on load. Fix:
1. Move `restored` ref to module level (survives React strict mode remount)
2. Add error handling for deleted runs (clear URL params silently)
3. Ensure lazy-loaded charts/events also work on URL restore (they do — `showReplay` handles this)

**Risk:** LOW. Existing mechanism just needs hardening.

**Phase 4 Verification:**
- Run a workflow, copy URL, open in new tab → same run loads with charts
- Delete a run, refresh page with its URL → no error, returns to home

---

## Execution Order

```
Phase 0 (race conditions)  →  3h  — stops the bleeding immediately
Phase 1 (global cleanup)   →  2h  — eliminates data leaking
Phase 3 (data loading)     →  4h  — backend perf, low risk high impact
Phase 2 (rendering perf)   →  8h  — biggest effort, do after correctness is solid
Phase 4 (persistence)      →  1h  — polish, small effort
```

Total: ~18h (2-3 focused days)

## Critical Files

| File | Changes |
|------|---------|
| `frontend/src/stores/viewStore.ts` | 0.1 sequencing, 1.1 remove global write |
| `frontend/src/stores/runHistoryStore.ts` | 0.2 AbortController, 3.2 client cache |
| `frontend/src/components/sidebar/RunHistoryList.tsx` | 0.2 click guard, 2.2 useShallow |
| `frontend/src/components/layout/CenterPanel.tsx` | 2.2 useShallow |
| `frontend/src/stores/conversationStore.ts` | 2.4 RAF batching |
| `frontend/src/components/conversation/ScopedConversationTab.tsx` | 2.3 virtualization |
| `frontend/src/components/conversation/*.tsx` | 2.1 React.memo |
| `frontend/src/hooks/useWorkflowEvents.ts` | 1.2 guard global cache |
| `server/app.py` | 3.1 GZip middleware |
| `harness/run_store.py` | 3.2 compact JSON, 3.4 pagination |
| `server/routes.py` | 3.4 pagination |
| `frontend/src/hooks/useUrlState.ts` | 4.1 harden restoration |
| `frontend/package.json` | 2.3 add @tanstack/react-virtual |

## Overall Risk Assessment

| Risk Level | Count | Areas |
|------------|-------|-------|
| LOW | 8 changes | sequencing, memo, useShallow, GZip, cache, compact JSON, URL state, global write removal |
| MEDIUM | 4 changes | virtualization (DOM structure), pagination (API contract), batch mode guard, compact JSON |
| MEDIUM-HIGH | 1 change | RAF batching (timing-sensitive) |

The MEDIUM-HIGH RAF batching change is the only one that could cause visible bugs (lost text at message boundaries). Mitigation: synchronous flush before message completion.

## Verification Checklist

After all phases:
1. [ ] Rapid clicking 5+ runs → final run displayed correctly, no overlap
2. [ ] Run workflow to completion → all agent conversations visible
3. [ ] Switch between completed run and live workflow → no stale data
4. [ ] Refresh page during replay → same run restored from URL
5. [ ] Load run with 200+ messages → smooth scroll, low DOM count
6. [ ] React DevTools Profiler → streaming causes ~60 re-renders/sec
7. [ ] GZip responses verified via curl
8. [ ] Batch mode: start benchmark, switch tasks → conversations correct
9. [ ] `pytest tests/test_run_store.py` passes
10. [ ] `cd frontend && npm run build` succeeds
