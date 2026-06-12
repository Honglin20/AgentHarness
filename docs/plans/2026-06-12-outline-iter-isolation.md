# Outline Iter Isolation — Plan E (todo iter-aware + badge degradation)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the iter-dimension mismatch surfaced during code review of the outline feature. Two concrete problems:
1. **Bug 3** — `TodoStep` has no `iteration` field; iter=2 of a loop node displays iter=1's step list.
2. **Bug 1 (visual)** — token / retry / duration / status badges read node-level `NodeState`, so all iter rows of the same node show **identical** numbers under different "Iteration N/M" titles.

**Approach:** Partial iter sinking — make conversation-data (which is naturally per-event) iter-aware; degrade node-aggregate metadata (token/retry/duration) via UI policy instead of sinking it. This is the boundary justified in review: event-stream data has iter as a natural dimension; aggregate properties do not.

**Non-goals (explicitly out of scope):**
- Sinking `NodeState` to iter dimension (that's Plan A2 — follow-up PR).
- Precise per-iter token accounting (user explicitly accepted error here).
- Changes to the legacy Timeline view (it's slated for deprecation).
- Backend / persistence schema migration (TodoStep.iteration is optional; old runs degrade cleanly).

---

## Architecture Decisions (confirmed in review)

### Decision 1: TodoStep.iteration stamped at handler layer

Same pattern as `ConversationMessage.iteration` (already shipped in this PR):
- `todo.created` / `todo.replaced` events arrive at `todoHandlers.ts`.
- Handler reads `stores.conversation.getState().currentIterationByNode[nodeId]` and stamps it onto each new step.
- `currentIterationByNode` is bumped by `node.started` (already done in this PR at `nodeHandlers.ts:21-27`).

**Why handler-layer stamping (not store-layer):** keeps the todo store API unchanged (`handleTodoCreated(store, nodeId, items)`), and the stamp source is the conversation store which is already iter-aware. One direction of dependency: todo handlers read conversation state, never the reverse.

### Decision 2: Badge degradation policy (not data sinking)

For non-message metadata (token, retry, duration, status), introduce an `isLatestIter` flag on `OutlineItem`:
- **Latest iter row** — uses node-level `NodeState` (real-time snapshot).
- **Historical iter rows** — hides token/retry/duration badges; status is inferred from that iter's messages.

This avoids the "three rows showing identical 12.0k" bug without sinking NodeState.

### Decision 3: retry badge — option C (display-only, no reset)

User confirmed: retryAttempts stays as node-level accumulation in NodeState. Display policy:
- Show retry badge only on `isLatestIter && node.status === "retrying"`.
- Historical iter rows don't show retry badge.
- No data loss (the array stays intact), no false precision (we don't claim "iter=2 retried N times").

### Decision 4: status inference for historical iters

For an iter that isn't the latest:
- If any agent message in that iter has `status: "error"` → `"failed"`
- Else if the iter has a `done` agent message → `"completed"`
- Else (no messages or only streaming) → `"idle"`

This is a heuristic; user accepted status imprecision for historical rows.

---

## Robustness Contract

- **Legacy TodoStep data** (no `iteration` field, e.g. persisted runs from before this PR): treated as `iteration=1`. UI filtering treats undefined as 1 → consistent with `ConversationMessage.iteration ?? 1` pattern.
- **Replay view**: `currentIterationByNode` may be empty after store reset, but messages retain their `iteration` field (persisted). Outline derivation uses messages as the source of truth for iter enumeration, so historical iters still display correctly. Only **new** step creation during replay would stamp `iteration=1` — acceptable since replay doesn't generate new steps.
- **Error boundaries**: Outline and Detail are already wrapped independently. No new failure modes introduced.
- **Empty states**: iter row with zero messages (synthesized idle entry, `deriveOutlineItems.ts:57-62`) → no status inference possible → falls back to `"idle"`.

---

## Performance Contract

- **Outline derivation cost**: unchanged — `deriveOutlineItems` is still O(N×M) over nodes×messages. Adding a `todos.filter(byIter)` inside `buildItem` is O(K) per item where K = todos for that node (typically <20). Total added cost negligible.
- **NodeBlockCard todo subscription**: switching from `s.todos[nodeId]` to a filtered selector. The selector returns a new array reference only when the filtered result changes by value — use a shallow-equal guard to avoid spurious re-renders.
- **No new network fetches, no new store, no new middleware.**

---

## Phase 1: Data Layer — TodoStep.iteration

### Task 1.1: Add `iteration` field to TodoStep type

**File:** `frontend/src/contexts/workflow-context/stores/todo.ts:14`

```ts
export interface TodoStep {
  taskId: string;
  content: string;
  activeForm: string;
  status: TodoStepStatus;
  detail: string | null;
  tokenUsage?: { input: number; output: number; total: number };
  /**
   * Which loop iteration of this node created the step. 1-indexed.
   * Undefined for legacy data (treated as iteration 1 by consumers).
   * Stamped at todo.created / todo.replaced time from
   * currentIterationByNode[nodeId] — same pattern as ConversationMessage.iteration.
   */
  iteration?: number;
}
```

**Test:** type-level only — existing `TodoStep` consumers continue to compile because the field is optional.

### Task 1.2: Stamp iteration in handleTodoCreated and handleTodoReplaced

**File:** `frontend/src/contexts/workflow-context/stores/todo.ts`

Two options:
- **(A)** Change function signatures to accept `iteration: number` and have the handler pass it in.
- **(B)** Keep signatures; stamp inside the store function by reading from a passed-in `currentIter` parameter.

**Chosen: (A)** — explicit, testable, no hidden coupling.

```ts
export function handleTodoCreated(
  store: StoreApi<TodoState>,
  nodeId: string,
  items: TodoStepItem[],
  iteration: number,  // ← new param
) {
  store.setState((state) => {
    // ... existing logic ...
    const newSteps: TodoStep[] = items
      .filter((item) => !existingIds.has(item.task_id))
      .map((item) => ({
        taskId: item.task_id,
        content: item.content,
        activeForm: item.activeForm,
        status: item.status,
        detail: item.detail ?? null,
        iteration,  // ← stamp
      }));
    // ...
  });
}

export function handleTodoReplaced(
  store: StoreApi<TodoState>,
  nodeId: string,
  items: TodoStepItem[],
  iteration: number,  // ← new param
): void {
  // ... stamp iteration on each new step ...
}
```

`handleTodoUpdated`, `handleTodoBulkCompleted`, `accumulateStepTokens`, `forceTerminalSteps` — **no signature change**. They mutate existing steps in-place; the step's iteration was set at creation time and never changes.

### Task 1.3: Wire iteration from todoHandlers

**File:** `frontend/src/contexts/workflow-context/routing/todoHandlers.ts`

For `todo.created` and `todo.replaced` events, read current iter from conversation store:

```ts
"todo.created": (stores, p) => {
  const conv = stores.conversation.getState();
  const iter = conv.currentIterationByNode[p.node_id] ?? 1;
  handleTodoCreated(stores.todo, p.node_id, p.items, iter);

  const firstInProgress = p.items.find((i) => i.status === "in_progress");
  if (firstInProgress) {
    stores.conversation.getState().setCurrentStep(p.node_id, firstInProgress.task_id);
  }
},

"todo.replaced": (stores, p) => {
  const iter = stores.conversation.getState().currentIterationByNode[p.node_id] ?? 1;
  handleTodoReplaced(stores.todo, p.node_id, p.items, iter);
},
```

**Critical ordering:** `todo.created` can fire **before** `node.started` in some edge cases (engine emits todo list as part of node startup). If that happens, `currentIterationByNode[nodeId]` is undefined → defaults to 1. The subsequent `node.started` will bump the counter to the correct value, but the steps stamped with iter=1 are already wrong.

**Mitigation:** This is the same risk that exists for `ConversationMessage.iteration` (messages created at `node.started` time also read `currentIterationByNode`). The PR shipping iter-stamping verified event ordering: `node.started` fires **before** the first `agent_message` / `todo.created` in the engine's emit sequence. Document this as an invariant in `nodeHandlers.ts`.

**Test:** see Phase 4 test matrix — `node.started` then `todo.created` ordering.

---

## Phase 2: Derivation Layer — iter-aware todo filtering + isLatestIter

### Task 2.1: deriveOutlineItems filters todos by iter

**File:** `frontend/src/components/outline/deriveOutlineItems.ts:85`

Current:
```ts
const todosForNode = todos[entry.nodeId] ?? [];
```

Change to:
```ts
const todosForNode = (todos[entry.nodeId] ?? []).filter(
  (t) => (t.iteration ?? 1) === entry.iteration,
);
```

`computeActivity` at line 160 then reads from this filtered list — `find(in_progress)` will only match steps in the current iter.

### Task 2.2: Compute isLatestIter per item

**File:** `frontend/src/components/outline/types.ts`

Add to `OutlineItem`:
```ts
export interface OutlineItem {
  // ... existing ...
  /** True if this is the highest iteration seen for this nodeId.
   *  Used by badge/status degradation policy: latest iter shows node-level
   *  real-time data; historical iters show inferred values. */
  isLatestIter: boolean;
}
```

**File:** `frontend/src/components/outline/deriveOutlineItems.ts`

In step 5 (the projection loop), pass `isLatestIter`:

```ts
return sorted.map((entry, idx) => {
  const node = nodes[entry.nodeId];
  const iterCount = iterCountByNode.get(entry.nodeId) ?? 1;
  const isLatestIter = entry.iteration === iterCount;
  // ...
  return buildItem(entry, node, name, todosForNode, iterMessages, iterCount, idx, isLatestIter);
});
```

`buildItem` threads `isLatestIter` through to `computeBadges` and `computeStatus`.

### Task 2.3: computeBadges — degrade non-iter-aware badges on historical iters

**File:** `frontend/src/components/outline/deriveOutlineItems.ts:172`

```ts
function computeBadges(
  node: NodeState | undefined,
  iteration: number,
  iterCount: number,
  isLatestIter: boolean,  // ← new
): OutlineBadge[] {
  const badges: OutlineBadge[] = [];
  if (iterCount > 1) {
    badges.push({ kind: "iteration", text: `#${iteration}`, title: `Iteration ${iteration} of ${iterCount}` });
  }
  // Token / retry badges only on latest iter — node-level values are not
  // iter-partitionable, so showing them on historical rows would be
  // misleading (three rows showing the same number under different titles).
  if (isLatestIter) {
    if (node?.retryAttempts?.length) {
      const last = node.retryAttempts[node.retryAttempts.length - 1];
      badges.push({
        kind: "retry",
        text: `${last.attempt + 1}/${last.maxAttempts}`,
        title: `Retry attempt ${last.attempt + 1} of ${last.maxAttempts}`,
      });
    }
    if (node?.tokenUsage && node.tokenUsage.total > 0) {
      badges.push({
        kind: "tokens",
        text: formatTokens(node.tokenUsage.total),
        title: `${node.tokenUsage.input} in / ${node.tokenUsage.output} out`,
      });
    }
  }
  return badges;
}
```

Iteration badge (`#1`, `#2`) stays on all rows — it's genuinely iter-level.

### Task 2.4: computeStatus — infer for historical iters

**File:** `frontend/src/components/outline/deriveOutlineItems.ts:122`

```ts
function computeStatus(
  node: NodeState | undefined,
  pendingQuestionCount: number,
  iterMessages: ConversationMessage[],
  isLatestIter: boolean,
): OutlineStatus {
  if (pendingQuestionCount > 0) return "waiting-for-user";
  if (!node) return "idle";

  // Latest iter — use node-level real-time status.
  if (isLatestIter) {
    switch (node.status) {
      case "running": return "running";
      case "success": return "completed";
      case "failed": return "failed";
      case "retrying": return "retrying";
      default: return "idle";
    }
  }

  // Historical iter — infer from messages. The node has since moved on
  // to a later iter, so node.status reflects the current iter, not this one.
  if (iterMessages.some((m) => m.status === "error")) return "failed";
  if (iterMessages.some((m) => m.status === "done")) return "completed";
  return "idle";
}
```

`buildItem` needs `iterMessages` to compute status — it already receives `iterMessages`, so no signature change beyond passing `isLatestIter`.

### Task 2.5: computeActivity — guard retrying/failed/tokens for historical iters

**File:** `frontend/src/components/outline/deriveOutlineItems.ts:135`

```ts
function computeActivity(
  node: NodeState | undefined,
  todos: TodoStep[],
  pendingQuestions: ConversationMessage[],
  isLatestIter: boolean,  // ← new
): AgentActivity {
  if (pendingQuestions.length > 0) {
    return { kind: "waiting-for-user", questionId: pendingQuestions[0].questionId ?? "", questionCount: pendingQuestions.length };
  }
  if (!node) return { kind: "idle" };

  // Retry / failed activities only meaningful on latest iter — historical
  // iters' retryAttempts are accumulated into node-level array and don't
  // reflect this specific iter.
  if (isLatestIter && node.status === "retrying" && node.retryAttempts?.length) {
    const last = node.retryAttempts[node.retryAttempts.length - 1];
    return { kind: "retrying", attempt: last.attempt + 1, maxAttempts: last.maxAttempts };
  }

  // For historical iters with messages, treat as completed (already
  // inferred by computeStatus). For latest iter, fall through to running/
  // completed logic below.
  if (!isLatestIter) {
    return { kind: "completed" };  // durationMs omitted — we don't have per-iter duration
  }

  if (node.status === "failed") {
    return { kind: "failed", errorSummary: node.classifiedFailure?.category ?? node.error ?? "Failed" };
  }
  if (node.status === "running") {
    const activeStep = todos.find((t) => t.status === "in_progress");
    return { kind: "running", currentStepContent: activeStep?.activeForm || activeStep?.content };
  }
  if (node.status === "success") {
    return { kind: "completed", durationMs: node.durationMs };
  }
  return { kind: "idle" };
}
```

---

## Phase 3: UI Layer — NodeBlockCard filters todos by iter

### Task 3.1: NodeBlockCard accepts optional iteration prop

**File:** `frontend/src/components/conversation/ScopedConversationTab.tsx:381`

```tsx
interface NodeBlockCardProps {
  // ... existing ...
  /** When set, filters the displayed todo list to this iteration.
   *  Undefined (Timeline view) shows all steps regardless of iter. */
  iteration?: number;
}

const NodeBlockCard = React.memo(function NodeBlockCard({
  // ... existing ...
  iteration,
}: NodeBlockCardProps) {
  // ...
  const todos = useStore(todoStore!, (s) => {
    const all = s.todos[nodeId];
    if (!all) return all;
    if (iteration === undefined) return all;  // Timeline compatibility
    return all.filter((t) => (t.iteration ?? 1) === iteration);
  });
  // ...
});
```

**Critical performance note:** zustand's default equality is `Object.is`. Returning a new filtered array on every store update would cause re-renders even when the filtered result is identical. Use a shallow-equal wrapper:

```ts
import { shallow } from "zustand/shallow";

const todos = useStore(
  todoStore!,
  (s) => {
    const all = s.todos[nodeId];
    if (!all) return all;
    if (iteration === undefined) return all;
    return all.filter((t) => (t.iteration ?? 1) === iteration);
  },
  shallow,
);
```

### Task 3.2: AgentDetailView passes iteration to NodeBlockCard

**File:** `frontend/src/components/outline/AgentDetailView.tsx:121`

Already receives `iteration` as a prop — just thread it through:

```tsx
<NodeBlockCard
  block={block}
  getAgentIO={getAgentIO}
  getNodeState={getNodeState}
  sendStructuredAnswer={sendStructuredAnswer}
  conversationActions={conversationActions}
  todoStore={todoStore}
  iteration={iteration}  // ← new
/>
```

### Task 3.3: ScopedConversationTab timeline usage — no change

The timeline view (line 608 in ScopedConversationTab.tsx) renders `<NodeBlockCard todoStore={todoStore} ... />` without `iteration`. With `iteration === undefined`, NodeBlockCard shows all steps — preserves timeline's "full history" semantics. **No change needed.**

---

## Phase 4: Test Layer

### Task 4.1: Extend deriveOutlineItems.test.ts

**File:** `frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts`

Add test cases:

```ts
it("filters todos by iteration in computeActivity (Bug 3)", () => {
  const nodes = { a: node({ id: "a", name: "a", status: "running" }) };
  const todos = {
    a: [
      { taskId: "s1", content: "iter1 step", activeForm: "iter1", status: "completed", detail: null, iteration: 1 },
      { taskId: "s2", content: "iter2 step", activeForm: "iter2", status: "in_progress", detail: null, iteration: 2 },
    ],
  };
  const messages = [
    msg({ id: "1", nodeId: "a", agentName: "a", timestamp: 100, iteration: 1 }),
    msg({ id: "2", nodeId: "a", agentName: "a", timestamp: 200, iteration: 2 }),
  ];
  const items = deriveOutlineItems(nodes, messages, todos);
  // iter=2 row should show iter2's step, not iter1's
  const iter2 = items.find((i) => i.iteration === 2)!;
  expect(iter2.activity).toMatchObject({ kind: "running", currentStepContent: "iter2" });
});

it("isLatestIter is true only for the highest iteration of a node", () => {
  const nodes = { coder: node({ id: "coder", name: "coder", status: "running" }) };
  const messages = [
    msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1 }),
    msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2 }),
    msg({ id: "3", nodeId: "coder", agentName: "coder", timestamp: 300, iteration: 3 }),
  ];
  const items = deriveOutlineItems(nodes, messages, emptyTodo);
  expect(items.find((i) => i.iteration === 1)?.isLatestIter).toBe(false);
  expect(items.find((i) => i.iteration === 2)?.isLatestIter).toBe(false);
  expect(items.find((i) => i.iteration === 3)?.isLatestIter).toBe(true);
});

it("token badge only appears on latest iter (Bug 1 fix)", () => {
  const nodes = { coder: node({ id: "coder", name: "coder", status: "success", tokenUsage: { input: 1000, output: 500, total: 1500 } }) };
  const messages = [
    msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1 }),
    msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2 }),
  ];
  const items = deriveOutlineItems(nodes, messages, emptyTodo);
  expect(items.find((i) => i.iteration === 1)?.badges.find((b) => b.kind === "tokens")).toBeUndefined();
  expect(items.find((i) => i.iteration === 2)?.badges.find((b) => b.kind === "tokens")?.text).toBe("1.5k");
});

it("historical iter status is inferred from messages, not node.status", () => {
  // node.status = "running" (because iter=2 is running), but iter=1 already completed
  const nodes = { coder: node({ id: "coder", name: "coder", status: "running" }) };
  const messages = [
    msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1, status: "done" }),
    msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2, status: "streaming" }),
  ];
  const items = deriveOutlineItems(nodes, messages, emptyTodo);
  expect(items.find((i) => i.iteration === 1)?.status).toBe("completed");
  expect(items.find((i) => i.iteration === 2)?.status).toBe("running");
});

it("historical iter with error message is marked failed", () => {
  const nodes = { coder: node({ id: "coder", name: "coder", status: "success" }) };
  const messages = [
    msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1, status: "error" }),
    msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2, status: "done" }),
  ];
  const items = deriveOutlineItems(nodes, messages, emptyTodo);
  expect(items.find((i) => i.iteration === 1)?.status).toBe("failed");
});
```

### Task 4.2: Extend todo store test

**File:** `frontend/src/contexts/workflow-context/stores/__tests__/todo.iteration.test.ts` (new file)

```ts
import { describe, it, expect } from "vitest";
import { createTodoStore, handleTodoCreated, handleTodoReplaced } from "../todo";

describe("TodoStep.iteration stamping", () => {
  it("handleTodoCreated stamps iteration on each new step", () => {
    const store = createTodoStore("wf-1");
    handleTodoCreated(store, "coder", [
      { task_id: "s1", content: "step1", activeForm: "stepping", status: "in_progress", detail: null },
    ], 2);
    expect(store.getState().todos.coder[0].iteration).toBe(2);
  });

  it("handleTodoReplaced stamps iteration on replacement steps", () => {
    const store = createTodoStore("wf-1");
    handleTodoCreated(store, "coder", [
      { task_id: "s1", content: "old", activeForm: "old", status: "completed", detail: null },
    ], 1);
    handleTodoReplaced(store, "coder", [
      { task_id: "s2", content: "new", activeForm: "new", status: "in_progress", detail: null },
    ], 2);
    expect(store.getState().todos.coder).toHaveLength(1);
    expect(store.getState().todos.coder[0].iteration).toBe(2);
  });

  it("legacy steps without iteration are treated as iter=1 by consumers", () => {
    const store = createTodoStore("wf-1");
    // Manually inject a legacy step (simulating persisted data from before this PR)
    store.setState({
      todos: { coder: [{ taskId: "legacy", content: "x", activeForm: "x", status: "completed", detail: null }] },
    });
    // Consumer-side filter: (t.iteration ?? 1) === 1
    const iter1Steps = store.getState().todos.coder.filter((t) => (t.iteration ?? 1) === 1);
    expect(iter1Steps).toHaveLength(1);
  });
});
```

### Task 4.3: Verify todo handler wiring

**File:** `frontend/src/contexts/workflow-context/routing/__tests__/todoHandlers.iteration.test.ts` (new file)

```ts
import { describe, it, expect, beforeEach } from "vitest";
import { createConversationStore } from "@/contexts/workflow-context/stores/conversation";
import { createTodoStore } from "@/contexts/workflow-context/stores/todo";
// ... build minimal stores, fire todo.created event after setCurrentIteration ...

describe("todo.created handler — iteration stamping", () => {
  it("reads currentIterationByNode at event time and stamps steps", () => {
    // 1. fire node.started (bumps currentIterationByNode to 1)
    // 2. fire todo.created → steps get iteration=1
    // 3. fire node.completed + node.started (bumps to 2)
    // 4. fire todo.created → steps get iteration=2
  });
});
```

---

## Phase 5: Cleanup & Verify

### Task 5.1: Update OutlineItem type — add isLatestIter

Already covered in Task 2.2. Listed here as a checkpoint — ensure no consumer of `OutlineItem` breaks from the new field (it's optional in spirit, but adding as required since every item computes it).

### Task 5.2: Build + typecheck

```bash
cd frontend && npm run build
```

Expected: clean build. Watch for warnings about missing dependencies in useEffect / useMemo (the new `isLatestIter` flows through `buildItem`, which is called inside `.map` — no hook concerns).

### Task 5.3: Run tests

```bash
cd frontend && npm run test
```

Expected: all green, including new test files.

### Task 5.4: Manual verification

Rebuild worktree frontend, hard-refresh browser, test scenarios:

1. **NAS loop workflow** — `searcher` node runs 3 iterations.
   - Each outline row shows distinct todo list (iter-specific).
   - Historical iter rows don't show token/retry badges.
   - Latest iter row shows current node-level token/retry/status.
   - Historical iter status inferred from messages.

2. **Replay of a finished loop run** — outline shows correct iter split; historical iter status is `completed`/`failed` based on messages; legacy steps (no iteration field) display under iter=1.

3. **Timeline view** — todo list shows all steps across all iters (no regression).

4. **Single-iter workflow** — `isLatestIter === true` for the only row; behavior identical to pre-fix.

---

## Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| `todo.created` fires before `node.started` → steps stamped with wrong iter | 🟡 Medium | Engine ordering invariant (verified for message stamping, same path). Add handler-layer defensive check: if `currentIterationByNode[nodeId]` is undefined, default to 1 and log warning. |
| NodeBlockCard filtered selector causes re-render storms | 🟡 Medium | Use `shallow` equality from zustand. Verify with React DevTools profiler on a chatty agent. |
| Status inference wrong for edge-case messages (e.g. interrupted) | 🟢 Low | Inference is best-effort; falls back to `idle`. User accepted imprecision. |
| Legacy persisted TodoStep data | 🟢 Low | Optional field; `(t.iteration ?? 1)` pattern handles cleanly. |
| `isLatestIter` recomputed when iterCount changes mid-render | 🟢 Low | Pure derivation, single source of truth (`iterCountByNode`). No race. |

---

## Rollout

- Single PR. No feature flag needed (TodoStep.iteration is optional; visual changes are local to outline view).
- Squash-merge after Phase 5 verification.
- Update `docs/status/CURRENT.md` and `CHANGELOG.md` per project convention.

---

## Estimate

- Phase 1 (data layer): 0.5 day
- Phase 2 (derivation): 0.5 day
- Phase 3 (UI): 0.25 day
- Phase 4 (tests): 0.5 day
- Phase 5 (verify): 0.25 day

**Total: 2 days.**

---

## Future: Upgrade Path to Plan A2 (full NodeState sinking)

This plan is forward-compatible with A2:
- `TodoStep.iteration` and `ConversationMessage.iteration` remain — data foundation stays.
- When A2 lands (`IterState` parallel store), the `isLatestIter` branch in `computeBadges` / `computeStatus` is replaced with iter-snapshot reads. The branch structure makes the swap mechanical.
- No rewrite needed — only the "historical iter" code path changes from inference to iter-snapshot lookup.
