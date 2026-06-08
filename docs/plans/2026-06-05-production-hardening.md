# Production Hardening — Performance, Robustness, Full History

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the frontend + server production-grade: race-free run switching, fast rendering with 200+ messages, paginated full history access, and optimized data transfer.

**Architecture:** Server adds GZip + pagination + compact JSON. Frontend adds request sequencing + AbortController + conversation virtualization + RAF streaming + React.memo. Global store leaks are eliminated. Users can access ALL historical runs via paginated "Load more".

**Tech Stack:** @tanstack/react-virtual, starlette GZipMiddleware, requestAnimationFrame batching, Zustand useShallow

---

## Phase 0: Race Condition Elimination (3 tasks)

### Task 1: Add request sequencing to viewStore.showReplay

**Files:**
- Modify: `frontend/src/stores/viewStore.ts:1-82`

**Step 1: Add monotonic counter and stale guard**

In `frontend/src/stores/viewStore.ts`, add a module-level counter and guard the async callback:

```ts
// Add after imports (line 7), before the type definitions:
let _replaySeq = 0;
```

**Step 2: Wrap showReplay with sequence guard**

Replace the `showReplay` action (lines 24-81) with:

```ts
  showReplay: (run) => {
    const seq = ++_replaySeq;

    // Ensure scoped stores exist for this workflow
    const manager = getWorkflowManager();
    manager.getOrCreate(run.run_id);

    // Clear stale global data
    useAgentIOStore.getState().reset();

    const doReplay = (chartGroups: RunRecord["chart_groups"], eventsData: RunRecord["events"]) => {
      if (seq !== _replaySeq) return; // stale — discard
      const wsEvents = eventsData as WSEvent[] | undefined;
      const hasPersistedData = run.agent_io && run.conversation && run.dag && run.result?.trace;
      if (hasPersistedData) {
        loadRunFromPersistedData(run.run_id, { ...run, chart_groups: chartGroups }, wsEvents);
      } else if (wsEvents && wsEvents.length > 0) {
        replayEventsToStores(run.run_id, wsEvents);
      } else {
        loadLegacyRunData(
          run.run_id,
          run.conversation ?? [],
          chartGroups,
          run.dag,
          run.workflow_name,
          run.result,
        );
      }
      set({
        activeView: { type: "replay", runId: run.run_id, run: { ...run, chart_groups: chartGroups, events: eventsData ?? undefined } },
        chartsLoading: false,
      });
    };

    const needsLazyLoad = (run._has_charts || run._has_events) && !run.chart_groups && !run.events;
    if (needsLazyLoad) {
      set({ chartsLoading: true });
      const store = useRunHistoryStore.getState();
      Promise.all([
        run._has_charts ? store.fetchRunCharts(run.run_id) : Promise.resolve(null),
        run._has_events ? store.fetchRunEvents(run.run_id) : Promise.resolve(null),
      ]).then(([charts, events]) => {
        if (seq !== _replaySeq) return; // stale — discard
        doReplay(charts, events ?? undefined);
      }).catch(() => {
        if (seq !== _replaySeq) return;
        doReplay(null, undefined);
      });
    } else {
      doReplay(run.chart_groups ?? null, run.events ?? undefined as RunRecord["events"]);
    }
  },
```

**Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 4: Commit**

```bash
git add frontend/src/stores/viewStore.ts
git commit -m "fix: add request sequencing to showReplay — prevents stale data on rapid click"
```

---

### Task 2: Add AbortController to sidebar run clicks

**Files:**
- Modify: `frontend/src/stores/runHistoryStore.ts:125-131`
- Modify: `frontend/src/components/sidebar/RunHistoryList.tsx:103-122`

**Step 1: Add AbortSignal support to fetchRun**

In `frontend/src/stores/runHistoryStore.ts`, change the `fetchRun` signature and implementation:

```ts
  fetchRun: async (runId: string, signal?: AbortSignal) => {
    try {
      const r = await fetchWithAuth(`/api/runs/${runId}`, { signal });
      if (r.ok) return await r.json();
    } catch (e: any) {
      if (e?.name === "AbortError") return null;
      console.error("fetchRun failed:", e);
    }
    return null;
  },
```

Update the interface at line 90:
```ts
  fetchRun: (runId: string, signal?: AbortSignal) => Promise<RunRecord | null>;
```

**Step 2: Add AbortController to RunHistoryList**

In `frontend/src/components/sidebar/RunHistoryList.tsx`, add a ref after line 69:

```tsx
  const abortRef = useRef<AbortController | null>(null);
```

Update imports (line 1) to include `useRef`:
```tsx
import { useEffect, useMemo, useRef, useState } from "react";
```

**Step 3: Update handleClickRun to use AbortController**

Replace the `handleClickRun` function (lines 103-122) with:

```tsx
  const handleClickRun = async (run: RunSummary) => {
    if (isSelectMode) {
      toggleRunSelection(run.run_id);
      return;
    }
    onLeaveBenchmark?.();
    selectRun(run.run_id);

    // Abort previous fetch
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;

    const full = await fetchRun(run.run_id, ac.signal);
    if (!full || ac.signal.aborted) return;

    if (full.status === "running") {
      setWorkflow(full.run_id, full.workflow_name, full.dag ?? null);
      showLive();
      return;
    }
    showReplay(full);
  };
```

**Step 4: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 5: Commit**

```bash
git add frontend/src/stores/runHistoryStore.ts frontend/src/components/sidebar/RunHistoryList.tsx
git commit -m "fix: add AbortController to sidebar clicks — cancels stale fetches"
```

---

### Task 3: Remove global agentIOStore writes from showReplay

**Files:**
- Modify: `frontend/src/stores/viewStore.ts` (the showReplay we just updated in Task 1)

**Step 1: Verify the change is already done**

In the showReplay from Task 1, confirm:
- The `for (const [nodeId, io] of Object.entries(run.agent_io))` block is **removed**
- It's replaced with `useAgentIOStore.getState().reset()`
- The scoped path reads from scoped stores only
- `AgentMessage.tsx` line 178-180 still has the global fallback for backward compat — that's fine

This was already done in Task 1's code. No additional changes needed.

**Step 2: Verify all Phase 0 changes together**

Manual test (browser):
1. Click Run A, immediately click Run B → only B's data appears, no flicker
2. Click Run A, wait for load, click Run B → B loads correctly
3. Rapid clicking through 5+ runs → final click's data is displayed, no overlap

**Step 3: Commit**

```bash
git add frontend/src/stores/viewStore.ts
git commit -m "fix: remove global agentIOStore writes from showReplay — no more cross-run data leak"
```

---

## Phase 1: Server-side Optimizations (4 tasks)

### Task 4: Add GZip compression middleware

**Files:**
- Modify: `server/app.py:121-150`

**Step 1: Add GZipMiddleware import and usage**

In `server/app.py`, add the import at line 5 (after the existing imports):

```python
from starlette.middleware.gzip import GZipMiddleware
```

In the `create_app()` function, add GZip middleware right after the CORS middleware (after line 150):

```python
    # GZip compression — reduces JSON response sizes by 60-80%
    app.add_middleware(GZipMiddleware, minimum_size=1000)
```

**Step 2: Verify**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 3: Manual verify**

Run: `curl -s -H "Accept-Encoding: gzip" -o /dev/null -w "%{size_download}" http://localhost:8000/api/runs`
Compare with: `curl -s -o /dev/null -w "%{size_download}" http://localhost:8000/api/runs`
Expected: Compressed size significantly smaller

**Step 4: Commit**

```bash
git add server/app.py
git commit -m "perf: add GZip compression middleware — 60-80% response size reduction"
```

---

### Task 5: Add pagination to list_runs backend

**Files:**
- Modify: `harness/run_store.py:171-213` — `list_runs` method
- Modify: `server/routes.py:644-695` — `list_runs` endpoint

**Step 1: Add pagination to RunStore.list_runs**

Replace `list_runs` method signature and add pagination params:

```python
    def list_runs(self, workflow_name: str | None = None, include_batch: bool = False,
                  user_id: str | None = None, summary_only: bool = False,
                  limit: int | None = None, offset: int = 0) -> dict:
```

At the end of `list_runs`, before the sort (line 212), add slicing:

```python
        runs.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        total = len(runs)
        if limit is not None:
            runs = runs[offset:offset + limit]
        elif offset > 0:
            runs = runs[offset:]
        return {"runs": runs, "total": total, "has_more": (offset + len(runs)) < total if limit else False}
```

**Step 2: Update the route endpoint**

In `server/routes.py`, update `list_runs` (line 644) to accept pagination params:

```python
@router.get("/runs")
async def list_runs(
    request: Request,
    workflow_name: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> dict:
```

And update the call to `RunStore().list_runs()`:

```python
    result = RunStore().list_runs(
        workflow_name=workflow_name,
        include_batch=True,
        user_id=None if is_admin else user.user_id,
        summary_only=True,
        limit=limit,
        offset=offset,
    )

    persisted = result["runs"]
    persisted_ids = {r.get("run_id") for r in persisted}
```

At the return (line 695), return the paginated structure:

```python
    combined = live_records + persisted
    has_more = result["has_more"]
    return {"runs": combined, "total": result["total"] + len(live_records), "has_more": has_more}
```

**Step 3: Write test for pagination**

In `tests/test_run_store.py`, add:

```python
def test_list_runs_pagination(tmp_path):
    """list_runs should support limit/offset pagination."""
    store = RunStore(str(tmp_path))
    for i in range(10):
        store.save(
            run_id=f"run-{i:03d}",
            workflow_name="test",
            agents_snapshot=[],
            status="completed",
            inputs={"idx": i},
            result=None,
        )

    # First page
    page1 = store.list_runs(limit=4, offset=0)
    assert len(page1["runs"]) == 4
    assert page1["total"] == 10
    assert page1["has_more"] is True

    # Second page
    page2 = store.list_runs(limit=4, offset=4)
    assert len(page2["runs"]) == 4
    assert page2["has_more"] is True

    # Third page (partial)
    page3 = store.list_runs(limit=4, offset=8)
    assert len(page3["runs"]) == 2
    assert page3["has_more"] is False

    # No pagination — returns all
    all_runs = store.list_runs()
    assert len(all_runs["runs"]) == 10
    assert all_runs["total"] == 10
    assert all_runs["has_more"] is False
```

**Step 4: Run tests**

Run: `pytest tests/test_run_store.py -v`
Expected: All tests pass including new pagination test

**Step 5: Fix existing tests for new return format**

Existing tests in `test_run_store.py` return bare arrays — they must be updated to use `result["runs"]`. Update every `store.list_runs(...)` assertion.

For example, `test_save_and_list_runs`:
```python
        runs_result = store.list_runs()
        runs = runs_result["runs"]
        assert len(runs) == 3
```

Do the same for all tests that call `store.list_runs()`.

**Step 6: Run all tests again**

Run: `pytest tests/test_run_store.py -v`
Expected: All tests pass

**Step 7: Commit**

```bash
git add harness/run_store.py server/routes.py tests/test_run_store.py
git commit -m "feat: add pagination to list_runs — limit/offset/has_more support"
```

---

### Task 6: Compact JSON storage

**Files:**
- Modify: `harness/run_store.py:152`

**Step 1: Change main record to compact JSON**

In `harness/run_store.py` line 152, change:

```python
        self._atomic_write(path, json.dumps(record, indent=2, ensure_ascii=False))
```

to:

```python
        self._atomic_write(path, json.dumps(record, separators=(",", ":"), ensure_ascii=False))
```

**Step 2: Verify tests pass**

Run: `pytest tests/test_run_store.py -v`
Expected: All tests pass

**Step 3: Commit**

```bash
git add harness/run_store.py
git commit -m "perf: compact JSON storage — ~30% file size reduction"
```

---

### Task 7: Update frontend to handle paginated runs + client cache + "Load more"

**Files:**
- Modify: `frontend/src/stores/runHistoryStore.ts` (full rewrite of data layer)
- Modify: `frontend/src/components/sidebar/RunHistoryList.tsx`

**Step 1: Update runHistoryStore for pagination + cache**

Replace `frontend/src/stores/runHistoryStore.ts` (interfaces stay the same, state and actions change):

Add to the interface after `isSelectMode`:

```ts
  hasMore: boolean;
  totalCount: number;
```

Add to the state:

```ts
  hasMore: false,
  totalCount: 0,
```

Update `fetchRuns`:

```ts
  fetchRuns: async (workflowName?: string, loadMore = false) => {
    set({ loading: true });
    try {
      const { runs: currentRuns } = get();
      const offset = loadMore ? currentRuns.length : 0;
      const limit = 50;
      const params = new URLSearchParams();
      if (workflowName) params.set("workflow_name", workflowName);
      params.set("limit", String(limit));
      params.set("offset", String(offset));
      const r = await fetchWithAuth(`/api/runs?${params}`);
      if (r.ok) {
        const data = await r.json();
        const newRuns: RunSummary[] = data.runs;
        set({
          runs: loadMore ? [...currentRuns, ...newRuns] : newRuns,
          hasMore: data.has_more,
          totalCount: data.total,
          loading: false,
        });
      } else {
        console.error(`fetchRuns: ${r.status} ${r.statusText}`);
        set({ loading: false });
      }
    } catch (e) {
      console.error("fetchRuns failed:", e);
      set({ loading: false });
    }
  },
```

Update `reset`:

```ts
  reset: () => set({ runs: [], loading: false, selectedRunId: null, selectedRunIds: new Set<string>(), isSelectMode: false, hasMore: false, totalCount: 0 }),
```

**Step 2: Update RunHistoryList to show "Load more"**

In `frontend/src/components/sidebar/RunHistoryList.tsx`, add to the destructured store values (around line 51):

```tsx
  const hasMore = useRunHistoryStore((s) => s.hasMore);
```

Add a load more handler after `handleBatchDelete`:

```tsx
  const handleLoadMore = () => {
    fetchRuns(undefined, true);
  };
```

Add "Load more" button at the bottom of the sidebar (before the closing `</div>` of the container, around line 364):

```tsx
      {hasMore && (
        <div className="px-3 py-2">
          <button
            onClick={handleLoadMore}
            disabled={loading}
            className="w-full rounded-md border border-dashed border-app-border py-1.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors disabled:opacity-50"
          >
            {loading ? "Loading..." : "Load more runs"}
          </button>
        </div>
      )}
```

**Step 3: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 4: Commit**

```bash
git add frontend/src/stores/runHistoryStore.ts frontend/src/components/sidebar/RunHistoryList.tsx
git commit -m "feat: paginated run history — Load more button, no run left behind"
```

---

## Phase 2: Rendering Performance (4 tasks)

### Task 8: Install @tanstack/react-virtual

**Step 1: Install**

Run: `cd frontend && npm install @tanstack/react-virtual`

**Step 2: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/package.json frontend/package-lock.json
git commit -m "chore: add @tanstack/react-virtual dependency"
```

---

### Task 9: Virtualize ScopedConversationTab

**Files:**
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx`

**Step 1: Replace full list render with virtualizer**

Replace the entire `ScopedConversationTab` component with a virtualized version. Key changes:
- Import `useVirtualizer` from `@tanstack/react-virtual`
- Replace `blocks.map(...)` with virtualizer
- Collapsed nodes get `estimateSize: 80`, expanded get `estimateSize: 200`
- Use `measureElement` for dynamic measurement after render
- Auto-scroll via `virtualizer.scrollToIndex(blocks.length - 1)`

```tsx
import { useVirtualizer } from "@tanstack/react-virtual";

export function ScopedConversationTab({ autoScroll = true }: ScopedConversationTabProps = {}) {
  const messages = useConversationMessages();
  const { sendStructuredAnswer } = useWSMethods();
  const conversationActions = useConversationActions();
  const scrollRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const agentIOStore = useScopedStore("agentIO");
  const workflowStoreApi = useScopedStore("workflow");
  const agentIOData = useStore(agentIOStore!, (s) => s.data);
  const workflowNodes = useStore(workflowStoreApi!, (s) => s.nodes);

  const getAgentIO = useCallback((nodeId: string) => agentIOData[nodeId], [agentIOData]);
  const getNodeState = useCallback((nodeId: string) => workflowNodes[nodeId], [workflowNodes]);

  const blocks = useMemo(() => groupMessages(messages), [messages]);
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  const virtualizer = useVirtualizer({
    count: blocks.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (i) => {
      const b = blocks[i];
      if (b.kind === "other") return 60;
      const nodeId = b.nodeId;
      return collapsed[nodeId] ? 80 : 200;
    },
    overscan: 5,
  });

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (autoScroll && blocks.length > 0) {
      virtualizer.scrollToIndex(blocks.length - 1, { align: "end", behavior: "smooth" });
    }
  }, [blocks.length, autoScroll, virtualizer]);

  if (messages.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Start a workflow to begin
      </div>
    );
  }

  const toggle = (id: string) =>
    setCollapsed((prev) => ({ ...prev, [id]: !(prev[id] ?? false) }));

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto">
      <div
        style={{
          height: virtualizer.getTotalSize(),
          width: "100%",
          position: "relative",
        }}
      >
        {virtualizer.getVirtualItems().map((virtualRow) => {
          const b = blocks[virtualRow.index];
          return (
            <div
              key={virtualRow.key}
              data-index={virtualRow.index}
              ref={virtualizer.measureElement}
              style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <div className="px-6 py-2">
                {b.kind === "other" ? (
                  renderOtherBlock(b.message, sendStructuredAnswer, conversationActions)
                ) : (
                  <NodeBlockCard
                    block={b}
                    collapsed={collapsed[b.nodeId] ?? false}
                    onToggle={() => toggle(b.nodeId)}
                    getAgentIO={getAgentIO}
                    getNodeState={getNodeState}
                    sendStructuredAnswer={sendStructuredAnswer}
                    conversationActions={conversationActions}
                  />
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

Extract a helper to render "other" blocks:

```tsx
function renderOtherBlock(
  m: ConversationMessage,
  sendStructuredAnswer: (id: string, answer: any) => void,
  actions: { answerUserQuestion: (id: string, answer: any) => void },
) {
  if (m.type === "user") return <UserMessage key={m.id} message={m} />;
  if (m.type === "system") return <SystemMessage key={m.id} message={m} />;
  if (m.type === "question") {
    return (
      <AgentQuestionCard
        key={m.id}
        message={m}
        onSubmit={(answer) => {
          if (m.questionId) {
            sendStructuredAnswer(m.questionId, answer);
            actions.answerUserQuestion(m.questionId, answer);
          }
        }}
      />
    );
  }
  return <ToolCallMessage key={m.id} message={m} />;
}
```

Extract `NodeBlockCard` as a `React.memo` component:

```tsx
const NodeBlockCard = React.memo(function NodeBlockCard({
  block,
  collapsed,
  onToggle,
  getAgentIO,
  getNodeState,
  sendStructuredAnswer,
  conversationActions,
}: {
  block: NodeBlock;
  collapsed: boolean;
  onToggle: () => void;
  getAgentIO: (nodeId: string) => any;
  getNodeState: (nodeId: string) => any;
  sendStructuredAnswer: (id: string, answer: any) => void;
  conversationActions: { answerUserQuestion: (id: string, answer: any) => void };
}) {
  const { mainMessage: m, items, nodeId } = block;
  const totalSections = items.filter(
    (item) => (item.type === "agent" && item.content.trim()) || item.type === "tool_call"
  ).length;

  const preview = (() => {
    for (const line of (m.content ?? "").split("\n")) {
      const t = line.trim();
      if (t) return t;
    }
    return "";
  })();

  return (
    <div className="rounded-lg border border-app-border bg-background p-3">
      <AgentNodeHeader
        message={m}
        collapsed={collapsed}
        onToggleCollapse={onToggle}
        sectionItemCount={totalSections}
        getAgentIO={getAgentIO}
        getNodeState={getNodeState}
      />
      {collapsed ? (
        <button
          type="button"
          onClick={onToggle}
          className="block w-full min-w-0 truncate text-left text-sm text-muted-foreground hover:text-app-text-primary"
        >
          {preview || "(empty output)"}
        </button>
      ) : (
        <div className="flex flex-col gap-1">
          {items.map((item) => {
            if (item.type === "tool_call") {
              return <ToolCallMessage key={item.id} message={item} />;
            }
            if (item.type === "question") {
              return (
                <AgentQuestionCard
                  key={item.id}
                  message={item}
                  onSubmit={(answer) => {
                    if (item.questionId) {
                      sendStructuredAnswer(item.questionId, answer);
                      conversationActions.answerUserQuestion(item.questionId, answer);
                    }
                  }}
                />
              );
            }
            if (item.type === "agent") {
              const isStreaming = item.status === "streaming";
              return (
                <div key={item.id} className="flex flex-col gap-1">
                  {item.thinking && (
                    <ThinkingBlock text={item.thinking} streaming={isStreaming} />
                  )}
                  {item.content.trim() && (
                    <div className="text-sm">
                      <MarkdownText>{item.content}</MarkdownText>
                      {isStreaming && <span className="animate-pulse">▎</span>}
                    </div>
                  )}
                </div>
              );
            }
            return null;
          })}
        </div>
      )}
    </div>
  );
});
```

**Step 2: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Commit**

```bash
git add frontend/src/components/conversation/ScopedConversationTab.tsx
git commit -m "perf: virtualize conversation messages — handles 200+ messages smoothly"
```

---

### Task 10: Add React.memo to leaf components

**Files:**
- Modify: `frontend/src/components/conversation/UserMessage.tsx`
- Modify: `frontend/src/components/conversation/SystemMessage.tsx`
- Modify: `frontend/src/components/conversation/AgentQuestionCard.tsx`

**Step 1: Wrap UserMessage with React.memo**

In `frontend/src/components/conversation/UserMessage.tsx`:

```tsx
"use client";

import React from "react";
import type { ConversationMessage } from "@/stores/conversationStore";

interface UserMessageProps {
  message: ConversationMessage;
}

export const UserMessage = React.memo(function UserMessage({ message }: UserMessageProps) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] rounded-2xl bg-primary px-4 py-2 text-sm text-primary-foreground">
        {message.content}
      </div>
    </div>
  );
});
```

**Step 2: Wrap SystemMessage with React.memo**

In `frontend/src/components/conversation/SystemMessage.tsx`:

```tsx
"use client";

import React from "react";
import type { ConversationMessage } from "@/stores/conversationStore";

interface SystemMessageProps {
  message: ConversationMessage;
}

export const SystemMessage = React.memo(function SystemMessage({ message }: SystemMessageProps) {
  return (
    <div className="flex items-center gap-3 py-1">
      <hr className="flex-1 border-muted-foreground/30" />
      <span className="text-xs text-muted-foreground">{message.content}</span>
      <hr className="flex-1 border-muted-foreground/30" />
    </div>
  );
});
```

**Step 3: Wrap AgentQuestionCard with React.memo**

In `frontend/src/components/conversation/AgentQuestionCard.tsx`, change the export:

```tsx
export const AgentQuestionCard = React.memo(function AgentQuestionCard({ message, onSubmit }: AgentQuestionCardProps) {
```

Add `import React from "react"` at the top.

**Step 4: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 5: Commit**

```bash
git add frontend/src/components/conversation/UserMessage.tsx frontend/src/components/conversation/SystemMessage.tsx frontend/src/components/conversation/AgentQuestionCard.tsx
git commit -m "perf: add React.memo to leaf components — prevents unnecessary re-renders"
```

---

### Task 11: RAF-batched streaming in conversationStore

**Files:**
- Modify: `frontend/src/stores/conversationStore.ts:157-185`

**Step 1: Add RAF batching infrastructure**

Add after the `msgCounter` declaration (line 106):

```ts
// RAF batching for streaming text updates
let _textBuf = new Map<string, { text: string; nodeId: string }>();
let _rafPending = false;

function _flushTextBuf(set: (fn: (state: ConversationState) => Partial<ConversationState>) => void) {
  const updates = new Map(_textBuf);
  _textBuf.clear();
  _rafPending = false;
  if (updates.size === 0) return;
  set((state) => {
    const messages = [...state.messages];
    for (const [, { nodeId: nid, text: t }] of updates) {
      const idx = messages.findLastIndex(
        (m) => m.nodeId === nid && m.type === "agent" && m.status === "streaming"
      );
      if (idx !== -1) messages[idx] = { ...messages[idx], content: messages[idx].content + t };
    }
    return { messages };
  });
}
```

**Step 2: Replace appendAgentText with buffered version**

Replace `appendAgentText` (lines 157-185) with:

```ts
  appendAgentText: (nodeId, text) => {
    const existing = _textBuf.get(nodeId);
    _textBuf.set(nodeId, { text: (existing?.text ?? "") + text, nodeId });
    if (!_rafPending) {
      _rafPending = true;
      requestAnimationFrame(() => _flushTextBuf(set));
    }
  },
```

**Step 3: Add sync flush before message-completing actions**

Add a `flushText` helper and call it at the beginning of `completeAgentMessage`, `failAgentMessage`, and `addToolCall`:

```ts
  // At the start of completeAgentMessage, failAgentMessage, addToolCall:
  // Flush any pending text before transitioning the message state
  if (_rafPending) {
    _rafPending = false;
    const updates = new Map(_textBuf);
    _textBuf.clear();
    // Apply synchronously via a direct set call
    // This must happen BEFORE the status change
  }
```

More precisely, add a sync flush function and call it. Replace the entire block with these modified actions:

```ts
  completeAgentMessage: (nodeId, agentName, durationMs) =>
    set((state) => {
      // Flush pending text synchronously
      const pending = _textBuf.get(nodeId);
      if (pending) {
        _textBuf.delete(nodeId);
        const idx = state.messages.findLastIndex(
          (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
        );
        if (idx !== -1) {
          const messages = [...state.messages];
          messages[idx] = { ...messages[idx], content: messages[idx].content + pending.text };
          // Now apply the completion on the updated state
          messages[idx] = { ...messages[idx], agentName, status: "done" as const, durationMs };
          return { messages };
        }
      }

      const idx = state.messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")
      );
      if (idx === -1) return state;

      const messages = [...state.messages];
      messages[idx] = {
        ...messages[idx],
        agentName,
        status: "done",
        durationMs,
      };
      return { messages };
    }),
```

Apply the same pattern for `failAgentMessage` and `addToolCall` — flush pending text for that nodeId before transitioning status.

**Step 4: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 5: Manual verify**

- Start a workflow with streaming agent → text should appear smoothly (~60fps)
- After completion, verify no text is missing at message boundaries
- Multiple agents streaming concurrently → no text loss

**Step 6: Commit**

```bash
git add frontend/src/stores/conversationStore.ts
git commit -m "perf: RAF-batched streaming updates — ~60fps text rendering"
```

---

## Phase 3: Store Subscription Optimization (2 tasks)

### Task 12: Consolidate RunHistoryList subscriptions with useShallow

**Files:**
- Modify: `frontend/src/components/sidebar/RunHistoryList.tsx:50-68`

**Step 1: Replace 15 individual selectors with useShallow**

Replace lines 50-68 with:

```tsx
import { useShallow } from "zustand/shallow";

// Inside the component:
  const {
    runs, loading, selectedRunId, fetchRuns, fetchRun, selectRun,
    isSelectMode, selectedRunIds, toggleSelectMode, toggleRunSelection,
    clearSelection, hasMore,
  } = useRunHistoryStore(
    useShallow((s) => ({
      runs: s.runs,
      loading: s.loading,
      selectedRunId: s.selectedRunId,
      fetchRuns: s.fetchRuns,
      fetchRun: s.fetchRun,
      selectRun: s.selectRun,
      isSelectMode: s.isSelectMode,
      selectedRunIds: s.selectedRunIds,
      toggleSelectMode: s.toggleSelectMode,
      toggleRunSelection: s.toggleRunSelection,
      clearSelection: s.clearSelection,
      hasMore: s.hasMore,
    }))
  );

  const { showLive, showReplay, activeView } = useViewStore(
    useShallow((s) => ({
      showLive: s.showLive,
      showReplay: s.showReplay,
      activeView: s.activeView,
    }))
  );

  const { workflowStatus, liveWorkflowId, setWorkflow } = useWorkflowStore(
    useShallow((s) => ({
      workflowStatus: s.status,
      liveWorkflowId: s.workflowId,
      setWorkflow: s.setWorkflow,
    }))
  );

  const activeBatchId = useBatchStore((s) => s.activeBatchId);
```

**Step 2: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Commit**

```bash
git add frontend/src/components/sidebar/RunHistoryList.tsx
git commit -m "perf: consolidate sidebar subscriptions with useShallow — fewer re-renders"
```

---

### Task 13: Harden URL state restoration

**Files:**
- Modify: `frontend/src/hooks/useUrlState.ts:53-59`

**Step 1: Handle deleted runs gracefully**

In `useUrlState.ts`, update the runId restoration block (lines 53-59):

```ts
    if (runId) {
      let cancelled = false;
      useRunHistoryStore.getState().fetchRun(runId).then((run) => {
        if (!cancelled && run) {
          useViewStore.getState().showReplay(run);
        } else if (!cancelled) {
          // Run not found — clear URL params silently
          const params = readParams();
          params.delete("run");
          writeParams(params);
        }
      });
      return () => { cancelled = true; };
    }
```

**Step 2: Verify**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Commit**

```bash
git add frontend/src/hooks/useUrlState.ts
git commit -m "fix: handle deleted run URLs gracefully — clear params instead of error"
```

---

## Phase 4: Final Build Verification (1 task)

### Task 14: Build and verify everything works

**Step 1: Run Python tests**

Run: `pytest tests/ -x -q`
Expected: All tests pass

**Step 2: Build frontend**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors

**Step 3: Manual browser verification checklist**

1. [ ] Rapid clicking 5+ runs → final run displayed correctly, no overlap
2. [ ] Run workflow to completion → all agent conversations visible
3. [ ] Switch between completed run and live workflow → no stale data
4. [ ] Refresh page during replay → same run restored from URL
5. [ ] Delete a run, refresh with its URL → returns to home, no error
6. [ ] 50+ runs in sidebar → "Load more" loads next batch
7. [ ] Run with 100+ messages → smooth scroll, low DOM count (check via DevTools)
8. [ ] GZip verified: `curl -H "Accept-Encoding: gzip" -v http://localhost:8000/api/runs 2>&1 | grep "content-encoding"`

**Step 4: Commit frontend build**

```bash
git add frontend/out/
git commit -m "chore: rebuild frontend after production hardening"
```

---

## Execution Order Summary

```
Task 1  — viewStore sequencing          (15 min)  ← stops stale data
Task 2  — AbortController sidebar       (15 min)  ← cancels stale fetches
Task 3  — Remove global agentIO writes  (5 min)   ← no cross-run leak
Task 4  — GZip middleware               (10 min)  ← 60-80% size reduction
Task 5  — Pagination backend            (45 min)  ← scalable run history
Task 6  — Compact JSON                  (5 min)   ← 30% storage savings
Task 7  — Pagination frontend           (30 min)  ← Load more button
Task 8  — Install react-virtual         (5 min)
Task 9  — Virtualize conversation       (45 min)  ← handles 200+ messages
Task 10 — React.memo leaves             (15 min)  ← fewer re-renders
Task 11 — RAF streaming                 (30 min)  ← smooth 60fps text
Task 12 — useShallow sidebar            (15 min)  ← batch subscriptions
Task 13 — URL state hardening           (10 min)  ← polish
Task 14 — Build + verify                (30 min)  ← final check
```

Total: ~4.5 hours

## Risk Assessment

| Risk Level | Tasks | Notes |
|------------|-------|-------|
| LOW | 1, 2, 3, 4, 6, 8, 10, 12, 13 | Purely additive guards, standard patterns |
| MEDIUM | 5, 7, 9 | API contract change (5,7), DOM structure change (9) |
| MEDIUM-HIGH | 11 | Timing-sensitive RAF batching — must sync flush before status transitions |

## Verification Checklist

After all tasks:
1. [ ] Rapid clicking 5+ runs → final run displayed correctly
2. [ ] Run workflow to completion → all conversations visible
3. [ ] Switch between completed run and live workflow → no stale data
4. [ ] Refresh page during replay → same run restored from URL
5. [ ] Delete a run, refresh with its URL → no error, returns home
6. [ ] 50+ runs → sidebar paginates, "Load more" works
7. [ ] 200+ messages → smooth scroll, low DOM count (~30-40 visible)
8. [ ] GZip responses verified via curl
9. [ ] `pytest tests/` all pass
10. [ ] `cd frontend && npm run build` succeeds
