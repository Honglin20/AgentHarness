# 前端性能 Phase 0+1 实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 解决两个紧急问题：(1) streaming 时前端渲染慢，(2) 刷新页面后 TODO step 状态丢失/永久转圈。这是 Phase 2+3 大重构之前的止血 + TODO 持久化补缺。

**Architecture:** Surgical fix，不动数据流模型。Phase 0 修 streaming 渲染管线 4 个反模式；Phase 1 给 `loadRunFromPersistedData` 补 todoStore hydration section + terminal 步骤强制收敛。

**Tech Stack:** React 18, Zustand, @tanstack/react-virtual, vitest, @testing-library/react

---

## 根因定位

### Phase 0 根因 — streaming 渲染慢

| 编号 | 反模式 | 文件:行 | 影响 |
|------|--------|---------|------|
| 0.1 | `setVisibleCount(VISIBLE_WINDOW)` 在每次 messages ref 变化时重置 | `ScopedConversationTab.tsx:558-563` | 60Hz effect 跑 + 用户加载的 earlier messages 被冲掉 |
| 0.2 | virtualizer `measureElement` + 流式高度变化 | `ScopedConversationTab.tsx:690` | ResizeObserver cascade，每个 streaming chunk 触发全列表 reflow |
| 0.3 | textBatcher 每 RAF 全量拷贝 `[...state.messages]` | `conversation.ts:554-585` + `rafBatcher.ts` | 数组越大越慢，线性退化 |
| 0.4 | `getNodeCollapsed` 依赖 `workflowNodes` ref | `ScopedConversationTab.tsx:591-598` | estimateSize 重建 → virtualizer invalidate |

### Phase 1 根因 — TODO 刷新后失效

- `loadRunFromPersistedData`（`replayEvents.ts:218-385`）的 9 个 section 覆盖了 workflowStore / spanStore / conversationStore / outputStore / agentIOStore / toolCallStore / chartStore / followup sessions / run summary，**唯独没有 todoStore**
- events replay 路径下，如果 workflow 中途被切，最后 `todo.updated` 状态停在 `in_progress`，没有 terminal 事件来标记 → step 永久转圈

---

## Task 依赖关系

- Task 0.1, 0.2, 0.3, 0.4 互相独立，可并行
- Task 1.1 必须先于 1.2（1.2 依赖 1.1 hydrate 出来的 todoStore）
- Phase 0 和 Phase 1 互不依赖，可并行

---

## Task 0.1: 修复 setVisibleCount 重置逻辑

**Files:**
- Create: `frontend/src/hooks/useStableVisibleCount.ts`
- Create: `frontend/src/hooks/__tests__/useStableVisibleCount.test.ts`
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx:556-567`

### Step 1: 写失败的测试

```ts
// frontend/src/hooks/__tests__/useStableVisibleCount.test.ts
import { renderHook, act } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { useStableVisibleCount } from "../useStableVisibleCount";

describe("useStableVisibleCount", () => {
  it("resets to initial when resetKey changes", () => {
    let resetKey = "run-A";
    const { result, rerender } = renderHook(() => useStableVisibleCount(50, resetKey));

    act(() => result.current[1]((c) => c + 100));
    expect(result.current[0]).toBe(150);

    resetKey = "run-B";
    rerender();
    expect(result.current[0]).toBe(50);
  });

  it("does NOT reset when resetKey stays the same", () => {
    const { result, rerender } = renderHook(() => useStableVisibleCount(50, "run-A"));
    act(() => result.current[1]((c) => c + 100));
    expect(result.current[0]).toBe(150);
    rerender();
    expect(result.current[0]).toBe(150);
  });
});
```

### Step 2: 跑测试确认失败

```
cd frontend && npx vitest run useStableVisibleCount
```

Expected: FAIL with "Cannot find module '../useStableVisibleCount'"

### Step 3: 实现 hook

```ts
// frontend/src/hooks/useStableVisibleCount.ts
import { useEffect, useRef, useState } from "react";

/**
 * Like useState for a count, but auto-resets to `initial` when `resetKey`
 * changes. Used by ScopedConversationTab to reset the visible-window when
 * the user switches runs (workflowId changes), NOT on every streaming
 * chunk (which is what the previous effect-on-messages-ref logic did).
 *
 * Bug being fixed: previous code did
 *   useEffect(() => setVisibleCount(VISIBLE_WINDOW), [messages])
 * which fired 60×/sec during streaming (messages ref changes every text
 * batch) AND wiped out user-loaded earlier messages.
 */
export function useStableVisibleCount(
  initial: number,
  resetKey: unknown,
): [number, (updater: (c: number) => number) => void] {
  const prevKeyRef = useRef(resetKey);
  const [count, setCount] = useState(initial);
  useEffect(() => {
    if (prevKeyRef.current !== resetKey) {
      setCount(initial);
      prevKeyRef.current = resetKey;
    }
  }, [resetKey, initial]);
  return [count, setCount];
}
```

### Step 4: 接入 ScopedConversationTab

`ScopedConversationTab.tsx` 当前 line 556-567:

```tsx
// before
const prevMessagesRef = useRef(messages);
const [visibleCount, setVisibleCount] = useState(VISIBLE_WINDOW);
useEffect(() => {
  if (prevMessagesRef.current !== messages) {
    setVisibleCount(VISIBLE_WINDOW);
    prevMessagesRef.current = messages;
  }
}, [messages]);
```

改为：

```tsx
// after — workflowId is the "run identity" signal. Streaming chunks grow
// messages but don't change workflowId; switching runs does.
const workflowId = useStore(workflowStoreApi!, (s) => s.workflowId);
const [visibleCount, setVisibleCount] = useStableVisibleCount(VISIBLE_WINDOW, workflowId);
```

注意：`workflowStoreApi` 已经在 line 571 定义，需要把这两行移到 line 571 之后（或者把 `workflowStoreApi` 的定义上移）。

文件顶部 import 加：

```tsx
import { useStableVisibleCount } from "@/hooks/useStableVisibleCount";
```

### Step 5: 跑测试确认通过

```
cd frontend && npx vitest run useStableVisibleCount
```

Expected: PASS

### Step 6: 手动验证

1. `cd frontend && npm run dev`
2. 打开一个长 conversation run
3. 点击"Load 50 earlier" → 看到 earlier messages
4. 等待 streaming 或切换其他 run 再切回
5. 验证：earlier messages 不再被冲掉

### Step 7: Commit

```bash
git add frontend/src/hooks/useStableVisibleCount.ts \
        frontend/src/hooks/__tests__/useStableVisibleCount.test.ts \
        frontend/src/components/conversation/ScopedConversationTab.tsx
git commit -m "fix: visibleCount 重置绑定 workflowId，不再每个 streaming chunk 都重置"
```

---

## Task 0.2: 替换 measureElement 为静态估计

**Files:**
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx:622-639` (estimateSize 改进)
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx:690` (移除 measureElement ref)

### Step 1: Manual repro（建立 baseline）

1. `cd frontend && npm run dev`
2. 启动一个 streaming workflow
3. Chrome DevTools Performance tab → Record 5 秒
4. 观察：Layout / Recalculate Style 事件高频触发（每个 streaming chunk 都触发）
5. 截图保存作为 baseline

### Step 2: 移除 measureElement ref

`ScopedConversationTab.tsx:684-698` 当前：

```tsx
<div
  key={virtualRow.key}
  data-index={virtualRow.index}
  ref={virtualizer.measureElement}  // ← 这一行删除
  style={{
    position: "absolute",
    // ...
  }}
>
```

删除 `ref={virtualizer.measureElement}` 这一行。

### Step 3: 改进 estimateSize 用 content-length 启发式

`ScopedConversationTab.tsx:625-638` 当前：

```tsx
estimateSize: (i) => {
  const b = blocks[i];
  if (b.kind === "other") return 60;
  if (getNodeCollapsed(b.nodeId)) return 80;
  let h = 40;
  for (const c of b.children) {
    if (c.kind === "agent_msg") h += 80;
    else if (c.kind === "tool_group") h += 32;
    else if (c.kind === "question") h += 120;
  }
  return h;
},
```

改为：

```tsx
estimateSize: (i) => {
  const b = blocks[i];
  if (b.kind === "other") return 60;
  if (getNodeCollapsed(b.nodeId)) return 80;
  let h = 40;  // header
  for (const c of b.children) {
    if (c.kind === "agent_msg") {
      // Heuristic: ~0.6px per char + 24px padding. Capped to avoid
      // pathological cases. Content length known at build time so this
      // is stable across re-renders (no ResizeObserver churn).
      const len = c.message.content?.length ?? 0;
      const thinking = c.message.thinking?.length ?? 0;
      h += Math.min(800, Math.max(40, (len + thinking) * 0.6 + 24));
    } else if (c.kind === "tool_group") {
      h += 32;  // collapsed tool group header
    } else if (c.kind === "question") {
      h += 120;
    }
  }
  return h;
},
```

注意：tool_group 默认 collapsed（用户点开才展开），所以 estimate 用 collapsed 大小 32px。展开时内容超出会导致 visual overlap，Phase 4 重写时彻底解决。

### Step 4: 手动验证

1. 重启 dev server
2. 同样的 streaming workflow，Performance record 5 秒
3. 对比 baseline：Layout 事件应该大幅减少（预计 80%+）
4. 视觉验证：长消息可能有 gap/overlap（已知 trade-off），但 streaming 流畅度大幅改善

### Step 5: Commit

```bash
git add frontend/src/components/conversation/ScopedConversationTab.tsx
git commit -m "perf: 移除 measureElement，用 content-length 启发式估算，streaming 不再 reflow cascade"
```

---

## Task 0.3: textBatcher 节流到 30Hz

**Files:**
- Modify: `frontend/src/lib/rafBatcher.ts`
- Create: `frontend/src/lib/__tests__/rafBatcher.test.ts`
- Modify: `frontend/src/contexts/workflow-context/stores/conversation.ts:554-604`

### Step 1: 写失败的测试

```ts
// frontend/src/lib/__tests__/rafBatcher.test.ts
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { createRafBatcher } from "../rafBatcher";

describe("createRafBatcher", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "requestAnimationFrame").mockImplementation((cb: FrameRequestCallback) => {
      return setTimeout(() => cb(performance.now()), 16) as unknown as number;
    });
    vi.spyOn(globalThis, "cancelAnimationFrame").mockImplementation((id: number) => {
      clearTimeout(id);
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("flushes on RAF by default", () => {
    const apply = vi.fn();
    const b = createRafBatcher<string, string>(apply);
    b.push("k", "v1", (a, b) => a + b);
    vi.advanceTimersByTime(16);
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("throttles when minIntervalMs is set", () => {
    const apply = vi.fn();
    const b = createRafBatcher<string, string>(apply, { minIntervalMs: 50 });
    b.push("k", "v1", (a, b) => a + b);
    vi.advanceTimersByTime(16);
    expect(apply).not.toHaveBeenCalled();
    vi.advanceTimersByTime(40);  // total 56ms > 50ms
    expect(apply).toHaveBeenCalledTimes(1);
  });

  it("does not call apply when buffer is empty", () => {
    const apply = vi.fn();
    const b = createRafBatcher<string, string>(apply);
    b.push("k", "v1", (a, b) => a + b);
    vi.advanceTimersByTime(16);
    expect(apply).toHaveBeenCalledTimes(1);
    // No new pushes — next timer should no-op
    vi.advanceTimersByTime(32);
    expect(apply).toHaveBeenCalledTimes(1);
  });
});
```

### Step 2: 跑测试确认失败

```
cd frontend && npx vitest run rafBatcher
```

Expected: FAIL — `createRafBatcher` 不接受 options 参数

### Step 3: 实现节流

替换 `frontend/src/lib/rafBatcher.ts` 全文：

```ts
/**
 * RAF Batch Processor — coalesces high-frequency text deltas into a single
 * requestAnimationFrame flush. Each scoped store instance creates its own
 * batcher, so concurrent workflows never share state.
 *
 * Default behavior: flush on every RAF (~60Hz).
 * With `minIntervalMs`: throttle to a minimum interval between flushes.
 * Useful for high-frequency producers (text streaming) where 60Hz full-
 * array copies saturate the main thread.
 */

export interface RafBatcher<TKey, TValue> {
  push(key: TKey, value: TValue, merge: (prev: TValue, next: TValue) => TValue): void;
  flush(): void;
  cancel(): void;
}

export interface RafBatcherOptions {
  /**
   * Minimum interval between flushes, in ms. Default: undefined (flush on
   * every RAF, ~60Hz). Set to e.g. 33 to throttle to 30Hz, halving the
   * work for high-frequency producers like text streaming.
   */
  minIntervalMs?: number;
}

export function createRafBatcher<TKey, TValue>(
  apply: (updates: Map<TKey, TValue>) => void,
  options: RafBatcherOptions = {},
): RafBatcher<TKey, TValue> {
  const { minIntervalMs } = options;
  let buf = new Map<TKey, TValue>();
  let seq = 0;
  let pending = false;
  let lastFlushTs = 0;

  function flush(): void {
    if (buf.size === 0) return;
    const updates = new Map(buf);
    buf.clear();
    seq++;  // invalidate any pending RAF/timer
    pending = false;
    lastFlushTs = performance.now();
    apply(updates);
  }

  function schedule(): void {
    if (minIntervalMs === undefined) {
      const capturedSeq = ++seq;
      requestAnimationFrame(() => {
        if (capturedSeq !== seq) return;
        flush();
      });
      return;
    }
    // Throttled: wait at least minIntervalMs since last flush
    const elapsed = performance.now() - lastFlushTs;
    const wait = Math.max(0, minIntervalMs - elapsed);
    const capturedSeq = ++seq;
    setTimeout(() => {
      if (capturedSeq !== seq) return;
      flush();
    }, wait);
  }

  return {
    push(key, value, merge) {
      const existing = buf.get(key);
      buf.set(key, existing !== undefined ? merge(existing, value) : value);
      if (!pending) {
        pending = true;
        schedule();
      }
    },

    flush,

    cancel() {
      seq++;
      pending = false;
    },
  };
}
```

### Step 4: 接入 textBatcher / thinkBatcher 用 33ms 节流

`conversation.ts` line 554 和 587 当前：

```ts
textBatcher = createRafBatcher<string, { text: string; nodeId: string }>(
  (updates) => { /* ... existing body ... */ },
);

thinkBatcher = createRafBatcher<string, { text: string; nodeId: string }>(
  (updates) => { /* ... existing body ... */ },
);
```

改为（只加第二个参数）：

```ts
textBatcher = createRafBatcher<string, { text: string; nodeId: string }>(
  (updates) => { /* ... existing body ... */ },
  { minIntervalMs: 33 },  // 30Hz — halves main-thread pressure during streaming
);

thinkBatcher = createRafBatcher<string, { text: string; nodeId: string }>(
  (updates) => { /* ... existing body ... */ },
  { minIntervalMs: 33 },
);
```

### Step 5: 跑测试确认通过

```
cd frontend && npx vitest run rafBatcher
```

Expected: 3 tests PASS

### Step 6: 手动验证

1. `npm run dev`
2. 启动 streaming workflow
3. Performance record，对比 Task 0.2 baseline
4. 验证：每秒 setState 次数减半

### Step 7: Commit

```bash
git add frontend/src/lib/rafBatcher.ts \
        frontend/src/lib/__tests__/rafBatcher.test.ts \
        frontend/src/contexts/workflow-context/stores/conversation.ts
git commit -m "perf: textBatcher 节流到 30Hz (minIntervalMs=33)，streaming 时数组拷贝减半"
```

---

## Task 0.4: getNodeCollapsed 解依赖 workflowNodes

**Files:**
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx:591-604`

### Step 1: 改用 ref 读取

`ScopedConversationTab.tsx:591-604` 当前：

```tsx
const getNodeCollapsed = useCallback(
  (nodeId: string): boolean => {
    if (nodeId in userNodeCollapseOverride) return userNodeCollapseOverride[nodeId];
    const status = workflowNodes[nodeId]?.status;
    return status === "success" || status === "failed";
  },
  [userNodeCollapseOverride, workflowNodes],
);
```

改为：

```tsx
const getNodeCollapsed = useCallback(
  (nodeId: string): boolean => {
    if (nodeId in userNodeCollapseOverride) return userNodeCollapseOverride[nodeId];
    // Read from nodesRef (line 578-579) instead of workflowNodes — ref is
    // stable, so this callback's identity doesn't change on every node
    // status update. Without this, estimateSize (which calls this) gets
    // recreated on every status change → virtualizer invalidates.
    const status = nodesRef.current[nodeId]?.status;
    return status === "success" || status === "failed";
  },
  [userNodeCollapseOverride],  // nodesRef is stable
);
```

### Step 2: 验证 estimateSize 不再重建

打开 React DevTools Profiler，触发一次 node 状态变化（启动一个 workflow），观察 `getNodeCollapsed` 函数引用是否稳定（应该不再变化）。

### Step 3: 手动验证

1. `npm run dev`
2. 启动一个有多 node 的 workflow
3. 观察 streaming 时 NodeBlockCard 是否稳定（之前 status 变化会导致整个 NodeBlock 重新 estimate + invalidate）

### Step 4: Commit

```bash
git add frontend/src/components/conversation/ScopedConversationTab.tsx
git commit -m "perf: getNodeCollapsed 改读 nodesRef，解依赖 workflowNodes，estimateSize 不再重建"
```

---

## Task 1.1: loadRunFromPersistedData 加 todoStore hydration

**Files:**
- Modify: `frontend/src/contexts/workflow-context/replayEvents.ts:218-385`
- Create: `frontend/src/contexts/workflow-context/__tests__/todoHydration.test.ts`

### Step 1: 写失败的测试

```ts
// frontend/src/contexts/workflow-context/__tests__/todoHydration.test.ts
import { describe, it, expect, beforeEach } from "vitest";
import { loadRunFromPersistedData } from "../replayEvents";
import { getWorkflowManager } from "../WorkflowManager";

describe("loadRunFromPersistedData — todoStore hydration", () => {
  beforeEach(() => {
    getWorkflowManager().reset();
  });

  it("hydrates todoStore from events", () => {
    const workflowId = "test-wf-1";
    const run = {
      conversation: [],
      dag: { nodes: ["agent1"], edges: [] },
      result: {
        outputs: {},
        errors: {},
        trace: [
          { agent_name: "agent1", status: "success", duration_ms: 100, error: null },
        ],
      },
      chart_groups: null,
    } as any;
    const events = [
      {
        type: "todo.created",
        payload: {
          workflow_id: workflowId,
          node_id: "agent1",
          items: [
            { task_id: "t1", content: "Step 1", active_form: "Doing 1", status: "completed", detail: null },
            { task_id: "t2", content: "Step 2", active_form: "Doing 2", status: "in_progress", detail: null },
          ],
        },
      },
      {
        type: "todo.updated",
        payload: {
          workflow_id: workflowId,
          node_id: "agent1",
          task_id: "t2",
          status: "completed",
        },
      },
    ] as any[];

    loadRunFromPersistedData(workflowId, run, events);

    const todos = getWorkflowManager().getStores(workflowId)!.todo.getState().todos;
    expect(todos["agent1"]).toHaveLength(2);
    expect(todos["agent1"][0].status).toBe("completed");
    expect(todos["agent1"][1].status).toBe("completed");
  });

  it("leaves todoStore empty when no events", () => {
    const workflowId = "test-wf-2";
    const run = {
      conversation: [],
      dag: { nodes: ["agent1"], edges: [] },
      result: {
        outputs: {},
        errors: {},
        trace: [
          { agent_name: "agent1", status: "success", duration_ms: 100, error: null },
        ],
      },
      chart_groups: null,
    } as any;

    loadRunFromPersistedData(workflowId, run, undefined);

    const todos = getWorkflowManager().getStores(workflowId)!.todo.getState().todos;
    expect(Object.keys(todos)).toHaveLength(0);
  });
});
```

### Step 2: 跑测试确认失败

```
cd frontend && npx vitest run todoHydration
```

Expected: FAIL — "expected 0 to have length 2"，因为当前 loadRunFromPersistedData 没 hydrate todoStore

### Step 3: 实现 hydration

`replayEvents.ts` 顶部 imports 区加：

```ts
import {
  handleTodoCreated,
  handleTodoUpdated,
  type TodoStepItem,
  type TodoAutoAdvance,
} from "./stores/todo";
```

注意：`TodoStepItem` 和 `TodoAutoAdvance` 当前从 `@/types/events` 来。如果 `stores/todo.ts` 没 re-export 它们，可以直接从 events 类型 import。

在 `loadRunFromPersistedData` 函数里，section 8 (chartStore，`loadChartsFromGroups(stores.chart, run.chart_groups);` 那行) 之后、section 8.5 (followup sessions) 之前，插入：

```ts
// -- 7.5. todoStore (replay from events) --------------------------------
//
// todoStore has no equivalent of "agent_io" or "trace" in the persisted
// run record — the canonical source is the ws event stream. We scan the
// events array for todo.created / todo.updated and apply them in order.
//
// Without this section, refreshing a run that uses the TODO tool leaves
// todoStore empty, and ScopedConversationTab falls into its "no todos"
// branch — rendering every agent_msg / tool_call inline instead of
// under step rows. That's both a UX regression (no step list) and a
// perf regression (more items in the virtualizer).
if (events && events.length > 0) {
  for (const event of events) {
    if (event.type === "todo.created") {
      const p = event.payload as {
        node_id: string;
        items: TodoStepItem[];
      };
      handleTodoCreated(stores.todo, p.node_id, p.items);
    } else if (event.type === "todo.updated") {
      const p = event.payload as {
        node_id: string;
        task_id: string;
        status?: "in_progress" | "completed" | null;
        detail?: string | null;
        auto_advance?: TodoAutoAdvance | null;
      };
      handleTodoUpdated(
        stores.todo,
        p.node_id,
        p.task_id,
        p.status ?? undefined,
        p.detail,
        p.auto_advance ?? null,
      );
    }
  }
}
```

### Step 4: 跑测试确认通过

```
cd frontend && npx vitest run todoHydration
```

Expected: 2 tests PASS

### Step 5: Commit

```bash
git add frontend/src/contexts/workflow-context/replayEvents.ts \
        frontend/src/contexts/workflow-context/__tests__/todoHydration.test.ts
git commit -m "fix: loadRunFromPersistedData 补 todoStore hydration section，刷新后 TODO 不再丢失"
```

---

## Task 1.2: 已完成 workflow 的 in_progress step 强制 terminal

**Files:**
- Modify: `frontend/src/contexts/workflow-context/stores/todo.ts` (add `forceTerminalSteps` helper + extend status type)
- Modify: `frontend/src/contexts/workflow-context/replayEvents.ts` (call after hydration)
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx:304-314` (STEP_ICON / STEP_TONE 加 interrupted)
- Modify: `frontend/src/contexts/workflow-context/__tests__/todoHydration.test.ts` (加测试)

### Step 1: 加 interrupted 状态 + forceTerminalSteps helper

`stores/todo.ts` 当前接口：

```ts
export interface TodoStep {
  taskId: string;
  content: string;
  activeForm: string;
  status: "pending" | "in_progress" | "completed";
  detail: string | null;
}
```

改为：

```ts
export type TodoStepStatus = "pending" | "in_progress" | "completed" | "interrupted";

export interface TodoStep {
  taskId: string;
  content: string;
  activeForm: string;
  status: TodoStepStatus;
  detail: string | null;
}
```

在 `stores/todo.ts` 末尾加 helper：

```ts
/**
 * Force all in_progress steps for a node to a terminal status. Used during
 * hydration when the workflow is already finished but the persisted todo
 * events show some steps stuck in_progress (workflow was killed mid-step,
 * or trailing todo.updated events weren't captured in the buffer).
 *
 * Without this, the UI shows a perpetual spinner on those steps after a
 * page refresh.
 */
export function forceTerminalSteps(
  store: StoreApi<TodoState>,
  nodeId: string,
  finalStatus: "completed" | "interrupted",
): void {
  store.setState((state) => {
    const steps = state.todos[nodeId];
    if (!steps) return state;
    const hasInProgress = steps.some((s) => s.status === "in_progress");
    if (!hasInProgress) return state;
    const updated = steps.map((s) =>
      s.status === "in_progress" ? { ...s, status: finalStatus } : s,
    );
    return {
      todos: { ...state.todos, [nodeId]: updated },
    };
  });
}
```

### Step 2: 写失败的测试

在 `todoHydration.test.ts` 末尾加 describe 块：

```ts
describe("forceTerminalSteps via loadRunFromPersistedData", () => {
  beforeEach(() => {
    getWorkflowManager().reset();
  });

  it("marks in_progress steps as completed when workflow succeeded", () => {
    const workflowId = "test-wf-3";
    const run = {
      conversation: [],
      dag: { nodes: ["agent1"], edges: [] },
      result: {
        outputs: {},
        errors: {},  // ← no errors
        trace: [
          { agent_name: "agent1", status: "success", duration_ms: 100, error: null },
        ],
      },
      chart_groups: null,
    } as any;
    const events = [
      {
        type: "todo.created",
        payload: {
          workflow_id: workflowId,
          node_id: "agent1",
          items: [
            { task_id: "t1", content: "Done", active_form: "", status: "completed", detail: null },
            { task_id: "t2", content: "Killed mid-step", active_form: "Working", status: "in_progress", detail: null },
          ],
        },
      },
      // No todo.updated for t2 — workflow was killed mid-step
    ] as any[];

    loadRunFromPersistedData(workflowId, run, events);

    const todos = getWorkflowManager().getStores(workflowId)!.todo.getState().todos;
    expect(todos["agent1"][1].status).toBe("completed");
  });

  it("marks in_progress steps as interrupted when workflow errored", () => {
    const workflowId = "test-wf-4";
    const run = {
      conversation: [],
      dag: { nodes: ["agent1"], edges: [] },
      result: {
        outputs: {},
        errors: { agent1: "Boom" },  // ← has errors
        trace: [
          { agent_name: "agent1", status: "failed", duration_ms: 100, error: "Boom" },
        ],
      },
      chart_groups: null,
    } as any;
    const events = [
      {
        type: "todo.created",
        payload: {
          workflow_id: workflowId,
          node_id: "agent1",
          items: [
            { task_id: "t1", content: "Working", active_form: "Doing", status: "in_progress", detail: null },
          ],
        },
      },
    ] as any[];

    loadRunFromPersistedData(workflowId, run, events);

    const todos = getWorkflowManager().getStores(workflowId)!.todo.getState().todos;
    expect(todos["agent1"][0].status).toBe("interrupted");
  });
});
```

### Step 3: 跑测试确认失败

```
cd frontend && npx vitest run todoHydration
```

Expected: 新加的 2 个测试 FAIL — "expected 'in_progress' to be 'completed'" / "to be 'interrupted'"

### Step 4: 接入 forceTerminalSteps 到 loadRunFromPersistedData

`replayEvents.ts` 的 todoStore hydration section（Task 1.1 加的那段）之后插入：

```ts
// -- 7.6. Force-terminal in_progress steps ------------------------------
//
// If the workflow is already finished (we're loading from a persisted
// run, not a live one) but some steps are still in_progress in the
// replayed state, force them to a terminal status. Without this, the
// UI shows a perpetual ▶ icon and spinner on those steps after refresh.
const workflowHadError = !!run.result?.errors &&
  Object.values(run.result.errors).some((e) => !!e);
const finalStatus: "completed" | "interrupted" = workflowHadError
  ? "interrupted"
  : "completed";
const todoState = stores.todo.getState();
for (const nodeId of Object.keys(todoState.todos)) {
  forceTerminalSteps(stores.todo, nodeId, finalStatus);
}
```

并在顶部 import 加 `forceTerminalSteps`：

```ts
import {
  handleTodoCreated,
  handleTodoUpdated,
  forceTerminalSteps,
  type TodoStepItem,
  type TodoAutoAdvance,
} from "./stores/todo";
```

### Step 5: STEP_ICON / STEP_TONE 加 interrupted

`ScopedConversationTab.tsx:304-314` 当前：

```tsx
const STEP_ICON: Record<TodoStep["status"], string> = {
  pending: "⬜",
  in_progress: "▶",
  completed: "✓",
};

const STEP_TONE: Record<TodoStep["status"], string> = {
  pending: "text-muted-foreground",
  in_progress: "text-blue-500",
  completed: "text-emerald-500",
};
```

改为：

```tsx
const STEP_ICON: Record<TodoStep["status"], string> = {
  pending: "⬜",
  in_progress: "▶",
  completed: "✓",
  interrupted: "⏸",
};

const STEP_TONE: Record<TodoStep["status"], string> = {
  pending: "text-muted-foreground",
  in_progress: "text-blue-500",
  completed: "text-emerald-500",
  interrupted: "text-amber-500",
};
```

### Step 6: 跑测试确认通过

```
cd frontend && npx vitest run todoHydration
```

Expected: 所有 4 个测试 PASS

### Step 7: tsc + build 验证

```
cd frontend && npx tsc --noEmit
```

Expected: 0 errors（如果有遗漏的 status 字面量没覆盖，tsc 会报 `Record<TodoStep["status"], ...>` 类型错误）

```
cd frontend && npm run build
```

Expected: build success

### Step 8: Commit

```bash
git add frontend/src/contexts/workflow-context/stores/todo.ts \
        frontend/src/contexts/workflow-context/replayEvents.ts \
        frontend/src/components/conversation/ScopedConversationTab.tsx \
        frontend/src/contexts/workflow-context/__tests__/todoHydration.test.ts
git commit -m "fix: 已完成 workflow 的 in_progress step 强制 terminal（completed/interrupted），刷新后不转圈"
```

---

## 完成后的整体验证

### Step 1: 全量测试

```
cd frontend && npm test
```

Expected: 所有测试通过（之前的 10/10 + 新加的 8 个测试 = 18/18）

### Step 2: tsc + build

```
cd frontend && npx tsc --noEmit && npm run build
```

Expected: 0 errors

### Step 3: 端到端手动验证

1. 启动一个 streaming workflow（有 TODO tool 的）
2. 观察 streaming：流畅度对比之前明显改善（无 reflow cascade）
3. 刷新页面：TODO step 列表正确显示，无永久转圈
4. 点击 "Load 50 earlier"，再触发 streaming 或切 workflow：earlier messages 不丢失
5. 切到 benchmark 模式跑多个 workflow：单选 workflow 的 streaming 仍然流畅（多 workflow 的彻底解决要等 Phase 2+3）

### Step 4: 总结 commit（可选）

```bash
git commit --allow-empty -m "milestone: Phase 0+1 完成，streaming 性能 + TODO 持久化止血"
```

---

## 已知 trade-offs

1. **measureElement 移除导致长消息可能有 visual gap/overlap** —— Phase 4 重写时彻底解决
2. **textBatcher 30Hz 导致 streaming 文本视觉刷新略迟钝** —— 30Hz 仍然是流畅的（>24fps），用户感知不到差别
3. **in_progress step 强制收敛丢失"workflow 真实中间状态"信息** —— 但持久化刷新后看到的应该是 final 状态，这是正确的语义

## 不在本计划范围

- Phase 2（后端持久化拆 meta/content）→ 见 `docs/plans/2026-06-10-frontend-perf-phase2-3-adr.md`
- Phase 3（WS 订阅协议）→ 同上
- 老 run 的 lazy 体验（用户已确认只对新 run 生效）
- benchmark 多 workflow 并发卡死的彻底解决（依赖 Phase 2+3）

---

## Execution Handoff

计划已保存到 `docs/plans/2026-06-10-frontend-perf-phase0-1.md`。两种执行选项：

**1. Subagent-Driven (this session)** - 我在这个 session 里每个 task 派一个新 subagent，task 之间我做 code review，迭代快

**2. Parallel Session (separate)** - 你开新 session 用 executing-plans 技能，批量执行带 checkpoint

哪种？
