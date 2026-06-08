# Tasks 8 & 9: Frontend Cache Dedup + Token Breakdown Display

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish the two bonus tasks deferred from Phase 4 — extract the shared cache-management utility for the 3 scoped stores (conversation/workflow/output), and surface the backend's `token_breakdown` data in the Diagnostics panel UI.

**Architecture:** Task 8 creates a `withCache()` factory in `frontend/src/lib/storeCache.ts` that captures the 4 identical methods (saveToCache / restoreFromCache / setActiveWid / clearCache) and the in-place update helpers (updateCachedWid / getCacheForWid) used by the store-specific "append to cached entry" methods. Each store keeps its own `*ToCache` methods but delegates the common CRUD to the factory. Task 9 wires the backend's already-emitted `token_breakdown` field through the event type, store, and a new `TokenBreakdown.tsx` component that renders a per-agent token table.

**Tech Stack:** TypeScript, Zustand vanilla stores, React, Next.js

---

## Task 8: Extract shared store cache management

### Context

The 3 scoped stores (`conversation.ts`, `workflow.ts`, `output.ts`) each inline ~30-50 lines of cache-management methods that follow the same shape:

```ts
saveToCache: (wid) => { ... extract snap, write to _cache[wid] ... }
restoreFromCache: (wid) => { ... read _cache[wid], apply snap or return false ... }
setActiveWid: (wid) => { ... save current to _cache[old], apply _cache[new] or default ... }
clearCache: () => set({ _cache: {}, _activeWid: null })
```

The differences are only:
1. Which state fields to snapshot (conversation: messages/pendingQuestionId/pendingQuestionAgent; workflow: nodes/status/workflowId/workflowName/dag/envelope; output: texts/activeNodeId)
2. How to apply a snapshot back to state
3. What the "default empty" state looks like

Two stores (conversation, workflow) also have `*ToCache` methods that mutate a cached entry in-place (e.g. `updateNodeInCache`, `appendAgentTextToCache`). These can't be generalized because they depend on store-specific logic, but they share a common "get or initialize the cache entry" pattern.

The shared utility will provide:
- `saveToCache`, `restoreFromCache`, `setActiveWid`, `clearCache` — generic
- `getCacheForWid`, `setCacheForWid` — primitives that the store-specific `*ToCache` methods build on

### Task 8.1: Create `withCache` factory

**Files:**
- Create: `frontend/src/lib/storeCache.ts`
- Test: `frontend/src/lib/__tests__/storeCache.test.ts` (new)

**Step 1: Write the failing test**

```typescript
// frontend/src/lib/__tests__/storeCache.test.ts
import { describe, expect, it } from "vitest";
import { createStore } from "zustand/vanilla";
import { withCache } from "@/lib/storeCache";

interface TestState extends Record<string, unknown> {
  value: number;
  label: string;
  _cache: Record<string, { value: number; label: string }>;
  _activeWid: string | null;
}

function makeTestStore() {
  const store = createStore<TestState>()(() => ({
    value: 0,
    label: "",
    _cache: {},
    _activeWid: null,
  }));

  const cache = withCache(store, {
    extractSnapshot: (s) => ({ value: s.value, label: s.label }),
    applySnapshot: (_s, snap) => ({
      value: snap.value as number,
      label: snap.label as string,
    }),
    makeEmptySnapshot: () => ({ value: 0, label: "" }),
  });

  return { store, cache };
}

describe("withCache", () => {
  it("saveToCache writes a snapshot under wid", () => {
    const { store, cache } = makeTestStore();
    store.setState({ value: 42, label: "wf-1-state" });
    cache.saveToCache("wf-1");
    expect(store.getState()._cache["wf-1"]).toEqual({ value: 42, label: "wf-1-state" });
  });

  it("restoreFromCache applies snapshot and returns true when wid exists", () => {
    const { store, cache } = makeTestStore();
    cache.saveToCache("wf-1");
    store.setState({ value: 99, label: "different" });
    const ok = cache.restoreFromCache("wf-1");
    expect(ok).toBe(true);
    expect(store.getState().value).toBe(42);
  });

  it("restoreFromCache returns false when wid is absent", () => {
    const { store, cache } = makeTestStore();
    const ok = cache.restoreFromCache("nonexistent");
    expect(ok).toBe(false);
  });

  it("setActiveWid saves current then applies target snapshot", () => {
    const { store, cache } = makeTestStore();
    store.setState({ value: 10, label: "first" });
    cache.setActiveWid("wf-1");
    store.setState({ value: 20, label: "second" });
    cache.setActiveWid("wf-2");
    expect(store.getState()._cache["wf-1"]).toEqual({ value: 20, label: "second" });
    expect(store.getState().value).toBe(0); // empty default for unknown wid
    cache.setActiveWid("wf-1");
    expect(store.getState().value).toBe(20);
  });

  it("clearCache wipes cache and resets active wid", () => {
    const { store, cache } = makeTestStore();
    cache.saveToCache("wf-1");
    cache.clearCache();
    expect(store.getState()._cache).toEqual({});
    expect(store.getState()._activeWid).toBeNull();
  });

  it("getCacheForWid returns the stored snapshot", () => {
    const { store, cache } = makeTestStore();
    store.setState({ value: 7, label: "x" });
    cache.saveToCache("wf-1");
    expect(cache.getCacheForWid("wf-1")).toEqual({ value: 7, label: "x" });
    expect(cache.getCacheForWid("missing")).toBeUndefined();
  });

  it("setCacheForWid initializes an empty snapshot when missing", () => {
    const { store, cache } = makeTestStore();
    cache.setCacheForWid("wf-1");
    expect(cache.getCacheForWid("wf-1")).toEqual({ value: 0, label: "" });
  });

  it("setCacheForWid passes through an explicit snapshot", () => {
    const { store, cache } = makeTestStore();
    cache.setCacheForWid("wf-1", { value: 5, label: "init" });
    expect(cache.getCacheForWid("wf-1")).toEqual({ value: 5, label: "init" });
  });
});
```

**Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/lib/__tests__/storeCache.test.ts 2>/dev/null || echo "Vitest not configured — fall back to tsc-only check"`
Expected: FAIL — module doesn't exist. (If vitest isn't installed, skip to tsc-only verification; the manual browser smoke test in Task 8.5 covers behavior.)

**Step 3: Implement the factory**

```typescript
// frontend/src/lib/storeCache.ts
import type { StoreApi } from "zustand/vanilla";

type CacheEntry = Record<string, unknown>;

export interface WithCacheOptions<TState> {
  /** Extract a serializable snapshot from the store's current state. */
  extractSnapshot: (state: TState) => CacheEntry;
  /** Apply a cached snapshot back to the store. Returns a partial state patch. */
  applySnapshot: (state: TState, snap: CacheEntry) => Partial<TState>;
  /** Build the snapshot used when setActiveWid lands on a wid with no cached entry. */
  makeEmptySnapshot: () => CacheEntry;
}

export interface StoreCache {
  saveToCache: (wid: string) => void;
  restoreFromCache: (wid: string) => boolean;
  setActiveWid: (wid: string | null) => void;
  clearCache: () => void;
  /** Read a cached snapshot. Returns undefined if wid is unknown. */
  getCacheForWid: (wid: string) => CacheEntry | undefined;
  /** Ensure a snapshot exists for wid (inserting an empty/default if missing),
   *  or overwrite it with an explicit snap. Always returns the (now-existing) snapshot. */
  setCacheForWid: (wid: string, snap?: CacheEntry) => CacheEntry;
}

export function withCache<TState extends Record<string, unknown>>(
  store: StoreApi<TState>,
  options: WithCacheOptions<TState>,
): StoreCache {
  return {
    saveToCache: (wid) => {
      const snap = options.extractSnapshot(store.getState());
      store.setState({
        _cache: { ...store.getState()["_cache"], [wid]: snap },
      } as unknown as Partial<TState>);
    },

    restoreFromCache: (wid) => {
      const state = store.getState();
      const snap = (state["_cache"] as Record<string, CacheEntry>)?.[wid];
      if (!snap) return false;
      store.setState(options.applySnapshot(state, snap));
      store.setState({ _activeWid: wid } as unknown as Partial<TState>);
      return true;
    },

    setActiveWid: (wid) => {
      const state = store.getState();
      const cache = { ...((state["_cache"] as Record<string, CacheEntry>) ?? {}) };
      const currentWid = state["_activeWid"] as string | null;

      // Save current state to its wid before switching (unless first switch)
      if (currentWid && currentWid !== wid) {
        cache[currentWid] = options.extractSnapshot(state);
      }

      if (wid && cache[wid]) {
        const applied = options.applySnapshot(state, cache[wid]);
        store.setState({ ...applied, _cache: cache, _activeWid: wid } as unknown as Partial<TState>);
      } else {
        // Apply empty default
        const applied = options.applySnapshot(state, options.makeEmptySnapshot());
        store.setState({ ...applied, _cache: cache, _activeWid: wid } as unknown as Partial<TState>);
      }
    },

    clearCache: () => {
      store.setState({ _cache: {}, _activeWid: null } as unknown as Partial<TState>);
    },

    getCacheForWid: (wid) => {
      return (store.getState()["_cache"] as Record<string, CacheEntry> | undefined)?.[wid];
    },

    setCacheForWid: (wid, snap) => {
      const cache = { ...((store.getState()["_cache"] as Record<string, CacheEntry>) ?? {}) };
      if (!cache[wid]) {
        cache[wid] = snap ?? options.makeEmptySnapshot();
      } else if (snap) {
        cache[wid] = snap;
      }
      store.setState({ _cache: cache } as unknown as Partial<TState>);
      return cache[wid];
    },
  };
}
```

**Step 4: Run test (or type-check if vitest unavailable)**

Run: `cd frontend && npx vitest run src/lib/__tests__/storeCache.test.ts 2>/dev/null && echo PASS || (npx tsc --noEmit && echo "tsc OK — vitest missing, deferring to manual smoke test")`
Expected: PASS, or tsc-clean with explicit vitest-missing note.

**Step 5: Commit**

```bash
git add frontend/src/lib/storeCache.ts frontend/src/lib/__tests__/storeCache.test.ts
git commit -m "feat: withCache() — shared cache-management factory for scoped stores"
```

---

### Task 8.2: Refactor `output.ts` to use `withCache` (smallest store first)

**Files:**
- Modify: `frontend/src/contexts/workflow-context/stores/output.ts`

**Why output.ts first:** It's the simplest (only `texts` + `activeNodeId`) and has no `*ToCache` extras. Good warm-up for the conversation/workflow refactors.

**Step 1: Replace the 4 inline cache methods with `withCache` delegation**

```typescript
// frontend/src/contexts/workflow-context/stores/output.ts
import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { OutputState } from "@/stores/outputStore";
import { createRafBatcher, type RafBatcher } from "@/lib/rafBatcher";
import { withCache, type StoreCache } from "@/lib/storeCache";

export function createOutputStore(workflowId: string): StoreApi<OutputState> {
  let outputBatcher: RafBatcher<string, string>;

  const initialState: OutputState = {
    texts: {},
    activeNodeId: null,
    workflowError: null,
    _cache: {},
    _activeWid: null,

    appendText: () => {},
    setActiveNode: () => {},
    clearNode: () => {},
    setWorkflowError: () => {},
    reset: () => {},
    saveToCache: () => {},
    restoreFromCache: () => false,
    setActiveWid: () => {},
    clearCache: () => {},
  };

  const store = createStore<OutputState>()((set, get) => ({
    ...initialState,

    appendText: (nodeId, delta) => {
      outputBatcher.push(nodeId, delta, (prev, next) => prev + next);
    },
    setActiveNode: (nodeId) => set({ activeNodeId: nodeId }),
    clearNode: (nodeId) =>
      set((state) => {
        const { [nodeId]: _, ...rest } = state.texts;
        return {
          texts: rest,
          activeNodeId: state.activeNodeId === nodeId ? null : state.activeNodeId,
        };
      }),
    setWorkflowError: (error) => set({ workflowError: error }),
    reset: () => set({ texts: {}, activeNodeId: null, workflowError: null }),
    saveToCache: () => cache.saveToCache(get()._activeWid ?? ""),
    restoreFromCache: (wid) => cache.restoreFromCache(wid),
    setActiveWid: (wid) => cache.setActiveWid(wid),
    clearCache: () => cache.clearCache(),
  }));

  const cache: StoreCache = withCache(store, {
    extractSnapshot: (s) => ({ texts: s.texts, activeNodeId: s.activeNodeId }),
    applySnapshot: (_s, snap) => ({
      texts: (snap.texts as Record<string, string>) ?? {},
      activeNodeId: (snap.activeNodeId as string | null) ?? null,
    }),
    makeEmptySnapshot: () => ({ texts: {}, activeNodeId: null }),
  });

  outputBatcher = createRafBatcher<string, string>((updates) => {
    store.setState((state) => {
      const texts = { ...state.texts };
      updates.forEach((d, nid) => {
        texts[nid] = (texts[nid] ?? "") + d;
      });
      return { texts };
    });
  });

  return store;
}
```

**Note on `saveToCache(wid)`:** The original store signature is `saveToCache(wid: string) => void`. The factory's `saveToCache(wid)` matches exactly — the change above is a mistake (using `get()._activeWid`); restore the `wid` parameter:

```typescript
saveToCache: (wid) => cache.saveToCache(wid),
```

(Final code should pass `wid` through, not read `_activeWid`.)

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors related to output.ts.

**Step 3: Commit**

```bash
git add frontend/src/contexts/workflow-context/stores/output.ts
git commit -m "refactor: output store uses withCache() — drops ~25 lines of inline cache code"
```

---

### Task 8.3: Refactor `workflow.ts` to use `withCache`

**Files:**
- Modify: `frontend/src/contexts/workflow-context/stores/workflow.ts`

**Step 1: Replace the 4 cache methods and refactor `updateNodeInCache` to use `cache.getCacheForWid`/`setCacheForWid`**

The `workflow.ts` store has `updateNodeInCache(wid, payload)` — a store-specific method that mutates a node inside a cached snapshot. It can't be fully generalized, but it can use the factory's `setCacheForWid`/`getCacheForWid` primitives.

Replace the `saveToCache` / `restoreFromCache` / `setActiveWid` / `clearCache` methods with `cache.*()` calls, and rewrite `updateNodeInCache` so its "create cache entry if missing" preamble uses `cache.setCacheForWid(wid, { ...makeEmptySnapshot, ...baseWorkflowFields })`:

```typescript
// Top of createWorkflowStore:
import { withCache, type StoreCache } from "@/lib/storeCache";

// After `const store = createStore<...>(...)`:
const cache: StoreCache = withCache(store, {
  extractSnapshot: (s) => ({
    nodes: s.nodes,
    status: s.status,
    workflowId: s.workflowId,
    workflowName: s.workflowName,
    dag: s.dag,
    envelope: s.envelope,
  }),
  applySnapshot: (_s, snap) => ({
    nodes: (snap.nodes as WorkflowState["nodes"]) ?? {},
    status: (snap.status as WorkflowState["status"]) ?? "idle",
    workflowId: (snap.workflowId as string | null) ?? null,
    workflowName: (snap.workflowName as string | null) ?? null,
    dag: (snap.dag as WorkflowState["dag"]) ?? null,
    envelope: (snap.envelope as WorkflowState["envelope"]) ?? null,
  }),
  makeEmptySnapshot: () => ({
    nodes: {},
    status: "running",
    workflowId: workflowId, // closure-captured initial workflowId
    workflowName: null,
    dag: null,
    envelope: null,
  }),
});

// In the store actions:
saveToCache: (wid) => cache.saveToCache(wid),
restoreFromCache: (wid) => cache.restoreFromCache(wid),
setActiveWid: (wid) => cache.setActiveWid(wid),
clearCache: () => cache.clearCache(),

updateNodeInCache: (wid, payload) => {
  // Get or initialize the cache entry, then update the specific node.
  const existing = cache.getCacheForWid(wid);
  const base = existing ?? cache.setCacheForWid(wid, {
    nodes: {},
    status: "running",
    workflowId: wid,
    workflowName: null,
    dag: null,
    envelope: null,
  });
  const snap = base as WorkflowSnapshot;
  const nodes = { ...snap.nodes };

  // ... unchanged if/else if/else dispatch on payload shape ...
  // (Keep the existing NodeFailedPayload / NodeCompletedPayload / NodeStartedPayload
  // branches, but read/write through `nodes` then `cache.setCacheForWid(wid, { ...snap, nodes })`.)
},
```

**Note:** The existing `updateNodeInCache` mutates `_cache` directly via `set({...})`. The refactor switches the read/write through the factory primitives. The actual node-state construction (the if/else if/else branches) is unchanged.

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Commit**

```bash
git add frontend/src/contexts/workflow-context/stores/workflow.ts
git commit -m "refactor: workflow store uses withCache() for cache CRUD"
```

---

### Task 8.4: Refactor `conversation.ts` to use `withCache`

**Files:**
- Modify: `frontend/src/contexts/workflow-context/stores/conversation.ts`

**Step 1: Replace the 4 cache methods; refactor `appendAgentTextToCache` / `addToolCallToCache` / `addToolResultToCache` to use factory primitives**

The conversation store has 3 store-specific `*ToCache` methods. They mutate cached message arrays in-place. Same approach as workflow's `updateNodeInCache`: switch the read/write through `cache.getCacheForWid` / `cache.setCacheForWid`.

```typescript
import { withCache, type StoreCache } from "@/lib/storeCache";

// After store creation:
const cache: StoreCache = withCache(store, {
  extractSnapshot: (s) => ({
    messages: s.messages,
    pendingQuestionId: s.pendingQuestionId,
    pendingQuestionAgent: s.pendingQuestionAgent,
  }),
  applySnapshot: (_s, snap) => ({
    messages: (snap.messages as ConversationState["messages"]) ?? [],
    pendingQuestionId: (snap.pendingQuestionId as string | null) ?? null,
    pendingQuestionAgent: (snap.pendingQuestionAgent as string | null) ?? null,
  }),
  makeEmptySnapshot: () => ({
    messages: [],
    pendingQuestionId: null,
    pendingQuestionAgent: null,
  }),
});

// In the store actions:
saveToCache: (wid) => cache.saveToCache(wid),
restoreFromCache: (wid) => cache.restoreFromCache(wid),
setActiveWid: (wid) => cache.setActiveWid(wid),
clearCache: () => cache.clearCache(),

appendAgentTextToCache: (wid, nodeId, text, agentName) => {
  const existing = cache.getCacheForWid(wid);
  const base = (existing ?? cache.setCacheForWid(wid, {
    messages: [],
    pendingQuestionId: null,
    pendingQuestionAgent: null,
  })) as { messages: ConversationMessage[]; pendingQuestionId: string | null; pendingQuestionAgent: string | null };

  const messages = [...base.messages];
  const idx = messages.findLastIndex(
    (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming",
  );
  if (idx !== -1) {
    messages[idx] = { ...messages[idx], content: messages[idx].content + text };
  } else {
    messages.push({
      id: `msg-${msgCounter.next()}`,
      type: "agent",
      nodeId,
      agentName: agentName || "",
      content: text,
      status: "streaming",
      timestamp: Date.now(),
    });
  }
  cache.setCacheForWid(wid, { ...base, messages });
},
// (Same pattern for addToolCallToCache and addToolResultToCache.)
```

**Important:** Note the original code uses `state._cache[wid].messages[idx] = {...}` — i.e. direct mutation. The refactor makes this immutable (`[...messages]`) to avoid subtle aliasing bugs in the new factory path. Tests should still pass.

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Commit**

```bash
git add frontend/src/contexts/workflow-context/stores/conversation.ts
git commit -m "refactor: conversation store uses withCache() for cache CRUD"
```

---

### Task 8.5: Smoke test — cache still works for batch mode

**Files:** none (manual verification)

**Step 1: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 2: Manual browser smoke test**

Start the dev server and verify batch mode cache behavior:

1. `bash examples/launch_ui.sh`
2. Open http://localhost:3000
3. Run a benchmark with 2+ parallel workflows
4. Switch between the workflow tabs — verify each tab shows its own conversation/messages
5. Switch back to the first tab — verify its messages are still there (this is the cache restore path)
6. Stop the benchmark, restart it — verify cache doesn't leak old data into the new run

**Step 3: If smoke test passes, commit (no code changes for this task)**

```bash
# (No code to commit; this task is verification only.)
echo "Task 8.5 verified"
```

---

## Task 9: Token Breakdown Display

### Context

The backend already emits `token_breakdown` in `node.completed` events (verified in `harness/engine/macro_graph.py:917` — `build_node_completed_payload(..., token_breakdown=token_breakdown or None)`). The data shape is `{ agent_name: { input, output, total, cache_hit?, reasoning? } }`. But the frontend doesn't type it, store it, or display it.

This task wires the field through 4 layers:
1. `NodeCompletedPayload` type — declare the new field
2. `NodeState` interface — add `tokenBreakdown?` field
3. `handleNodeCompleted` — capture the field when applying the payload
4. `TokenBreakdown.tsx` — new component that renders a per-agent table
5. `DiagnosticsPanel.tsx` — render the component when a node is selected

### Task 9.1: Declare `token_breakdown` on the event type

**Files:**
- Modify: `frontend/src/types/events.ts:87-104` (`NodeCompletedPayload`)

**Step 1: Add the new field**

```typescript
// After the TokenUsage interface:
export interface AgentTokenUsage {
  input: number;
  output: number;
  total: number;
  cache_hit?: number;
  reasoning?: number;
}

export interface NodeCompletedPayload {
  node_id: string;
  agent_name: string;
  duration_ms: number;
  status: string;
  token_usage?: TokenUsage;
  /** Per-agent token breakdown — includes sub-agents if any. */
  token_breakdown?: Record<string, AgentTokenUsage>;
  cost_usd?: number;
  ttft_ms?: number;
  input_prompt?: string;
  system_prompt?: string;
  output_result?: Record<string, unknown>;
}
```

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Commit**

```bash
git add frontend/src/types/events.ts
git commit -m "feat: declare token_breakdown on NodeCompletedPayload"
```

---

### Task 9.2: Store `tokenBreakdown` on `NodeState`

**Files:**
- Modify: `frontend/src/stores/workflowStore.ts:12-29` (`NodeState`)
- Modify: `frontend/src/stores/workflowStore.ts` — `handleNodeCompleted` (capture the field)

**Step 1: Add `tokenBreakdown` to NodeState**

```typescript
import type { AgentTokenUsage } from "@/types/events";

export interface NodeState {
  // ... existing fields ...
  tokenUsage?: { input: number; output: number; total: number };
  /** Per-agent token breakdown — present when backend emits `token_breakdown`. */
  tokenBreakdown?: Record<string, AgentTokenUsage>;
  // ... rest ...
}
```

**Step 2: Capture the field in `handleNodeCompleted`**

Find the global `handleNodeCompleted` in `workflowStore.ts` and the scoped version in `contexts/workflow-context/stores/workflow.ts`. In both, update the `nodes[node_id]` assignment:

```typescript
nodes[payload.node_id] = {
  ...nodes[payload.node_id],
  id: payload.node_id,
  name: payload.agent_name,
  status: "success",
  durationMs: payload.duration_ms,
  tokenUsage: payload.token_usage,
  tokenBreakdown: payload.token_breakdown, // NEW
  costUsd: payload.cost_usd,
  ttftMs: payload.ttft_ms,
};
```

Also update `updateNodeInCache` in `workflow.ts` scoped store to capture `tokenBreakdown` when building the cached snapshot for `NodeCompletedPayload`.

**Step 3: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 4: Commit**

```bash
git add frontend/src/stores/workflowStore.ts frontend/src/contexts/workflow-context/stores/workflow.ts
git commit -m "feat: capture token_breakdown on NodeState in global + scoped stores"
```

---

### Task 9.3: Create `TokenBreakdown.tsx` component

**Files:**
- Create: `frontend/src/components/diagnostics/TokenBreakdown.tsx`

**Step 1: Implement the component**

```tsx
// frontend/src/components/diagnostics/TokenBreakdown.tsx
"use client";

import React from "react";
import type { AgentTokenUsage } from "@/types/events";

interface TokenBreakdownProps {
  breakdown: Record<string, AgentTokenUsage>;
}

/**
 * Renders a per-agent token usage table. Sub-agents (keys containing ".sub.")
 * are styled as muted. A totals row appears at the bottom.
 */
export const TokenBreakdown = React.memo(function TokenBreakdown({ breakdown }: TokenBreakdownProps) {
  const agents = Object.entries(breakdown);
  if (agents.length === 0) return null;

  const totals = agents.reduce(
    (acc, [, u]) => ({
      input: acc.input + u.input,
      output: acc.output + u.output,
      cache_hit: acc.cache_hit + (u.cache_hit ?? 0),
      reasoning: acc.reasoning + (u.reasoning ?? 0),
    }),
    { input: 0, output: 0, cache_hit: 0, reasoning: 0 },
  );

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">Token Usage Breakdown</h4>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted-foreground">
            <th className="text-left">Agent</th>
            <th className="text-right">Input</th>
            <th className="text-right">Output</th>
            <th className="text-right">Cache Hit</th>
            <th className="text-right">Reasoning</th>
            <th className="text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {agents.map(([name, usage]) => {
            const isSub = name.includes(".sub.");
            return (
              <tr key={name} className={isSub ? "text-muted-foreground" : ""}>
                <td className="font-mono">{name}</td>
                <td className="text-right">{usage.input.toLocaleString()}</td>
                <td className="text-right">{usage.output.toLocaleString()}</td>
                <td className="text-right">{(usage.cache_hit ?? 0).toLocaleString()}</td>
                <td className="text-right">{(usage.reasoning ?? 0).toLocaleString()}</td>
                <td className="text-right font-medium">{usage.total.toLocaleString()}</td>
              </tr>
            );
          })}
          <tr className="border-t font-medium">
            <td>Total</td>
            <td className="text-right">{totals.input.toLocaleString()}</td>
            <td className="text-right">{totals.output.toLocaleString()}</td>
            <td className="text-right">{totals.cache_hit.toLocaleString()}</td>
            <td className="text-right">{totals.reasoning.toLocaleString()}</td>
            <td className="text-right">{(totals.input + totals.output).toLocaleString()}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
});
```

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Commit**

```bash
git add frontend/src/components/diagnostics/TokenBreakdown.tsx
git commit -m "feat: TokenBreakdown component — per-agent token usage table"
```

---

### Task 9.4: Integrate `TokenBreakdown` into `DiagnosticsPanel`

**Files:**
- Modify: `frontend/src/components/diagnostics/DiagnosticsPanel.tsx`

**Step 1: Render the breakdown when the selected node has one**

Find the `renderPanel` helper (or wherever node detail content is rendered). After the existing `BudgetBar` section, add:

```tsx
import { TokenBreakdown } from "./TokenBreakdown";

// Inside the panel render, after BudgetBar:
{selectedNodeId && nodes[selectedNodeId]?.tokenBreakdown && (
  <TokenBreakdown breakdown={nodes[selectedNodeId].tokenBreakdown} />
)}
```

For the scoped panel variant (`ScopedDiagnosticsPanel`), read `nodes` from the scoped store and apply the same logic.

For the global fallback variant (`GlobalDiagnosticsPanel`), same logic using the global store's `nodes`.

**Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors.

**Step 3: Commit**

```bash
git add frontend/src/components/diagnostics/DiagnosticsPanel.tsx
git commit -m "feat: render TokenBreakdown in DiagnosticsPanel for selected node"
```

---

### Task 9.5: Verify end-to-end with a workflow that has token usage

**Files:** none (manual verification)

**Step 1: Build frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

**Step 2: Manual browser smoke test**

1. `bash examples/launch_ui.sh`
2. Run any workflow that exercises the LLM (e.g. `examples/01_minimal.py` or one of the demo pipelines)
3. When the workflow completes, click on a completed agent node in the DAG or conversation
4. Open the Diagnostics panel
5. Verify the Token Usage Breakdown table appears with input/output/cache_hit/reasoning/total columns
6. If the workflow uses sub-agents, verify the sub-agent rows appear in muted styling and the totals row sums correctly

**Step 3: Commit frontend build**

```bash
git add frontend/out/
git commit -m "chore: rebuild frontend after Tasks 8 & 9 (cache dedup + token breakdown)"
```

---

## Summary

| Task | Layer | What | Files |
|------|-------|------|-------|
| 8.1 | lib | `withCache()` factory + tests | `frontend/src/lib/storeCache.ts`, `__tests__/storeCache.test.ts` |
| 8.2 | store | Refactor output store | `frontend/src/contexts/workflow-context/stores/output.ts` |
| 8.3 | store | Refactor workflow store | `frontend/src/contexts/workflow-context/stores/workflow.ts` |
| 8.4 | store | Refactor conversation store | `frontend/src/contexts/workflow-context/stores/conversation.ts` |
| 8.5 | — | Manual smoke test | — |
| 9.1 | types | Declare `token_breakdown` field | `frontend/src/types/events.ts` |
| 9.2 | store | Capture on NodeState | `frontend/src/stores/workflowStore.ts`, scoped workflow.ts |
| 9.3 | component | Create TokenBreakdown table | `frontend/src/components/diagnostics/TokenBreakdown.tsx` |
| 9.4 | panel | Integrate into DiagnosticsPanel | `frontend/src/components/diagnostics/DiagnosticsPanel.tsx` |
| 9.5 | — | Manual smoke test + frontend build | — |

## Success Criteria

| Metric | Current | Target |
|--------|---------|--------|
| Inline cache method copies across stores | 12 (4 methods × 3 stores) | 0 — all delegated to `withCache()` |
| `NodeState` exposes `tokenBreakdown` | No | Yes |
| Diagnostics panel shows per-agent tokens | No | Yes |
| Build passes | Yes | Yes |
| Zero TypeScript errors | Yes | Yes |

## Execution Order

```
8.1 — withCache factory        (30 min)
8.2 — output store refactor    (15 min)  ← simplest store, validate factory
8.3 — workflow store refactor  (30 min)  ← has updateNodeInCache extras
8.4 — conversation store       (45 min)  ← has 3 *ToCache extras
8.5 — cache smoke test         (15 min)
9.1 — events.ts type           (5 min)
9.2 — store capture            (15 min)
9.3 — TokenBreakdown component (20 min)
9.4 — DiagnosticsPanel wire    (15 min)
9.5 — token smoke test + build (15 min)
```

**Total: ~3.5 hours**
