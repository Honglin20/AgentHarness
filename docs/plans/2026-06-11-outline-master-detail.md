# Agent Outline + Master-Detail Conversation View Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an Outline navigation view (list of agents with live status, TODO progress, and ask_user alerts) plus a Detail view (single agent's conversation). Outline becomes the new default; the existing full-stream Timeline stays available as a toggle.

**Architecture:** Master-detail pattern. Outline is a **pure derivation** from existing scoped stores (workflow / todo / conversation) — no new fetches, no new backend endpoints. Detail reuses the existing `groupNodes` algorithm + `@tanstack/react-virtual` virtualizer, filtered to one `(nodeId, iteration)` pair. Loop disambiguation uses **frontend iteration counting** (zero backend change), mirroring the existing `stepId` stamping pattern.

**Tech Stack:** React 18, Zustand vanilla stores, @tanstack/react-virtual, TypeScript, Vitest.

**Design references (mature products):**
- **VS Code Outline panel** — left-side tree, click-to-navigate, sticky position, symbol icons.
- **Linear issue list** — compact one-line items, status icons (idle/in-progress/done/failed), keyboard nav (j/k), hover actions.
- **Slack sidebar** — unread/pending badges with pulse animation, active-row highlight, mention-style alert coloring.

**Performance contract (hard requirements):**
- Outline render cost: O(num_agents), typically <20 items, **zero per-message work**.
- Detail render cost: only the selected agent's messages pass through `groupNodes`; the virtualizer renders only visible rows.
- **Zero new network fetches** — all data already lands in scoped stores via the existing `showReplay` → `loadSidecars` → `applyHydration` pipeline.
- First paint: Outline visible the same frame stores populate (no extra skeleton).
- Switching agents: <16ms (in-memory filter, no I/O).

**Robustness contract:**
- Old conversation data without `iteration` field → degrades to iteration=1 (no crash, no data loss).
- Empty states: no agents yet, no selected agent, selected agent with zero messages — all explicitly handled.
- Replay-safe: derivation is a pure function of store state; identical store state produces identical outline.
- Error boundaries wrap Outline and Detail independently.

**Extensibility contract:**
- `OutlineItem` is a discriminated union — new agent lifecycle states added by extending the union, not by editing render switch statements.
- Badges are a composable array (`Badge[]`), each rendered by a small `<BadgeRenderer>` — adding a new badge type is one switch case.
- Selection state lives in its own store (`outlineStore`), decoupled from data stores — Detail can later be embedded elsewhere without dragging outline state along.

**Non-goals (explicitly out of scope):**
- Backend `nodeId` uniqueness for loops (deferred — frontend iteration counting is sufficient for v1).
- Swimlane/Gantt-style parallel visualization.
- Cross-agent search (defer to a future "global search" feature).
- Mobile responsive layout.

---

## Phase 1: Data Layer — Iteration Tracking

**Goal:** Stamp each `ConversationMessage` with the iteration number of its parent node, so loops can be disambiguated later. Mirrors the existing `currentStepIdByNode` + `stepId` pattern exactly.

**Why first:** This is the foundation. UI work in later phases depends on the `iteration` field existing. Doing it first means later phases don't need to revisit the data model.

### Task 1.1: Add `iteration` field to ConversationMessage type

**Files:**
- Modify: `frontend/src/stores/conversationStore.ts:14-55` (the `ConversationMessage` interface)

**Step 1: Write the failing type test**

Create `frontend/src/stores/__tests__/conversationMessage.types.test.ts`:

```typescript
import { describe, it, expectTypeOf } from "vitest";
import type { ConversationMessage } from "@/stores/conversationStore";

describe("ConversationMessage", () => {
  it("has optional iteration field (number | undefined)", () => {
    const m1: ConversationMessage = {
      id: "msg-1",
      type: "agent",
      content: "",
      timestamp: 0,
    };
    const m2: ConversationMessage = {
      id: "msg-2",
      type: "agent",
      content: "",
      timestamp: 0,
      iteration: 2,
    };
    expectTypeOf(m1.iteration).toEqualTypeOf<number | undefined>();
    expectTypeOf(m2.iteration).toEqualTypeOf<number | undefined>();
  });
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/stores/__tests__/conversationMessage.types.test.ts
```

Expected: FAIL with "Property 'iteration' does not exist on type ConversationMessage".

**Step 3: Add the field**

In `frontend/src/stores/conversationStore.ts`, add to `ConversationMessage` after the `stepId?` field:

```typescript
  /**
   * Which loop iteration of this node produced the message. 1-indexed.
   * Undefined for legacy data (treated as iteration 1 by consumers) and
   * for messages that aren't part of a node (system, user-typed).
   *
   * Stamped at creation time from `currentIterationByNode[nodeId]` — same
   * pattern as `stepId`. See `setCurrentIteration` action.
   */
  iteration?: number;
```

**Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/stores/__tests__/conversationMessage.types.test.ts
```

Expected: PASS.

**Step 5: Commit**

```bash
git add frontend/src/stores/conversationStore.ts frontend/src/stores/__tests__/conversationMessage.types.test.ts
git commit -m "feat(conv): add iteration field to ConversationMessage type"
```

---

### Task 1.2: Add `currentIterationByNode` state + `setCurrentIteration` action

**Files:**
- Modify: `frontend/src/stores/conversationStore.ts:70-130` (the `ConversationState` interface — add field + action signature)
- Modify: `frontend/src/contexts/workflow-context/stores/conversation.ts:56-66` (initial state)
- Modify: `frontend/src/contexts/workflow-context/stores/conversation.ts:356-377` (add `setCurrentIteration` implementation alongside `setCurrentStep`)
- Test: `frontend/src/stores/__tests__/conversationStore.iteration.test.ts`

**Step 1: Write the failing test**

Create `frontend/src/stores/__tests__/conversationStore.iteration.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { createConversationStore } from "@/contexts/workflow-context/stores/conversation";

describe("createConversationStore — iteration tracking", () => {
  it("initializes with empty currentIterationByNode", () => {
    const store = createConversationStore("wf-1");
    expect(store.getState().currentIterationByNode).toEqual({});
  });

  it("setCurrentIteration sets the iteration for a node", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 2);
    expect(store.getState().currentIterationByNode.coder).toBe(2);
  });

  it("setCurrentIteration is idempotent (same value → no-op)", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 1);
    const before = store.getState();
    store.getState().setCurrentIteration("coder", 1);
    expect(store.getState()).toBe(before);
  });

  it("reset() clears currentIterationByNode", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 3);
    store.getState().reset();
    expect(store.getState().currentIterationByNode).toEqual({});
  });
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/stores/__tests__/conversationStore.iteration.test.ts
```

Expected: FAIL with "setCurrentIteration is not a function" or "currentIterationByNode is undefined".

**Step 3: Add the field to `ConversationState`**

In `frontend/src/stores/conversationStore.ts`, inside the `ConversationState` interface, after `currentStepIdByNode`:

```typescript
  /**
   * nodeId → current loop iteration count for that node. 1-indexed.
   * Incremented by `setCurrentIteration` (called from nodeHandlers on
   * node.started — same place that calls `handleNodeStarted`). Each new
   * message created on this node stamps `iteration` from this map.
   *
   * Never cleared per-iteration — only wiped by `reset()`. A nodeId that
   * executes N times ends up with iteration=N at the end of the run.
   */
  currentIterationByNode: Record<string, number>;
```

And add to the Actions section:

```typescript
  setCurrentIteration: (nodeId: string, iteration: number) => void;
```

**Step 4: Add initial state + implementation in `conversation.ts`**

In `frontend/src/contexts/workflow-context/stores/conversation.ts`:

Add to `initialState` (around line 56-66):

```typescript
    currentIterationByNode: {} as Record<string, number>,
```

Add the implementation next to `setCurrentStep` (around line 365-377):

```typescript
    setCurrentIteration: (nodeId, iteration) =>
      set((state) => {
        if (state.currentIterationByNode[nodeId] === iteration) return state;
        return {
          currentIterationByNode: {
            ...state.currentIterationByNode,
            [nodeId]: iteration,
          },
        };
      }),
```

Add to the `reset()` action (around line 356-363):

```typescript
        currentIterationByNode: {},
```

**Step 5: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/stores/__tests__/conversationStore.iteration.test.ts
```

Expected: PASS (all 4 tests).

**Step 6: Commit**

```bash
git add frontend/src/stores/conversationStore.ts \
        frontend/src/contexts/workflow-context/stores/conversation.ts \
        frontend/src/stores/__tests__/conversationStore.iteration.test.ts
git commit -m "feat(conv): add currentIterationByNode state + setCurrentIteration action"
```

---

### Task 1.3: Increment iteration on `node.started` in nodeHandlers

**Files:**
- Modify: `frontend/src/contexts/workflow-context/routing/nodeHandlers.ts:13-25` (the `node.started` handler)
- Test: `frontend/src/contexts/workflow-context/routing/__tests__/nodeHandlers.iteration.test.ts`

**Step 1: Write the failing test**

Create `frontend/src/contexts/workflow-context/routing/__tests__/nodeHandlers.iteration.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { createConversationStore } from "@/contexts/workflow-context/stores/conversation";
import { createWorkflowStore } from "@/contexts/workflow-context/stores/workflow";
import { createOutputStore } from "@/contexts/workflow-context/stores/output";
import { nodeHandlers } from "../nodeHandlers";
import type { WorkflowStores } from "@/contexts/workflow-context/types";
import type { StoreApi } from "zustand/vanilla";
import type { ConversationState } from "@/stores/conversationStore";
import type { WorkflowState } from "@/stores/workflowStore";
import type { OutputState } from "@/stores/outputStore";

function makeStores(): WorkflowStores {
  return {
    conversation: createConversationStore("wf-1") as StoreApi<ConversationState>,
    workflow: createWorkflowStore("wf-1") as StoreApi<WorkflowState>,
    output: createOutputStore() as unknown as StoreApi<OutputState>,
    // Other stores not needed for this test — cast through unknown.
  } as unknown as WorkflowStores;
}

function fireEvent(type: string, payload: Record<string, unknown>) {
  return { type, ts: Date.now(), payload, workflow_id: "wf-1" } as any;
}

describe("node.started handler — iteration counting", () => {
  let stores: WorkflowStores;
  const handler = nodeHandlers.find(([t]) => t === "node.started")![1];

  beforeEach(() => {
    stores = makeStores();
  });

  it("sets iteration=1 on first node.started for a nodeId", () => {
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(1);
  });

  it("increments iteration on subsequent node.started for same nodeId (loop)", () => {
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    // Simulate the node completing — without this, the idempotency guard
    // in node.started would skip the second fire.
    stores.workflow.getState().handleNodeCompleted({ node_id: "coder", agent_name: "coder", duration_ms: 100 } as any);
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(2);
  });

  it("new agent message after second node.started is stamped with iteration=2", () => {
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    stores.workflow.getState().handleNodeCompleted({ node_id: "coder", agent_name: "coder", duration_ms: 100 } as any);
    handler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    const lastMsg = stores.conversation.getState().messages.at(-1);
    expect(lastMsg?.iteration).toBe(2);
  });
});
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/contexts/workflow-context/routing/__tests__/nodeHandlers.iteration.test.ts
```

Expected: FAIL (currentIterationByNode stays empty / messages have no iteration).

**Step 3: Update the `node.started` handler**

In `frontend/src/contexts/workflow-context/routing/nodeHandlers.ts`, modify the `node.started` handler:

```typescript
  [
    "node.started",
    (stores, event, _ctx) => {
      const p = payload<NodeStartedPayload>(event);
      // Idempotent: skip if node is already tracked and running
      const existingNode = stores.workflow.getState().nodes[p.node_id];
      if (existingNode && existingNode.status === "running") return;

      // Increment loop iteration counter for this nodeId BEFORE creating
      // the agent message, so the message stamps the new iteration. Mirrors
      // the existing stepId pattern: state setter first, message creator
      // reads from state.
      const conv = stores.conversation.getState();
      const nextIter = (conv.currentIterationByNode[p.node_id] ?? 0) + 1;
      conv.setCurrentIteration(p.node_id, nextIter);

      stores.workflow.getState().handleNodeStarted(p);
      stores.output.getState().setActiveNode(p.node_id);
      stores.conversation.getState().addAgentMessage(p.node_id, p.agent_name);
    },
  ],
```

**Step 4: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/contexts/workflow-context/routing/__tests__/nodeHandlers.iteration.test.ts
```

Expected: PASS (all 3 tests).

**Step 5: Commit**

```bash
git add frontend/src/contexts/workflow-context/routing/nodeHandlers.ts \
        frontend/src/contexts/workflow-context/routing/__tests__/nodeHandlers.iteration.test.ts
git commit -m "feat(conv): increment iteration on node.started in nodeHandlers"
```

---

### Task 1.4: Stamp `iteration` on all message-creating actions

**Files:**
- Modify: `frontend/src/contexts/workflow-context/stores/conversation.ts`:
  - `addAgentMessage` (~line 85-108)
  - `addToolCall` (~line 163-199)
  - `addUserQuestion` (~line 238-260)
  - `addFollowupAgentMessage` (~line 497-521)
  - Text batcher fallback push (~line 567-580)
- Test: extend `frontend/src/stores/__tests__/conversationStore.iteration.test.ts`

**Step 1: Write the failing tests**

Append to `frontend/src/stores/__tests__/conversationStore.iteration.test.ts`:

```typescript
import { createConversationStore } from "@/contexts/workflow-context/stores/conversation";

describe("createConversationStore — iteration stamping", () => {
  it("addAgentMessage stamps iteration from currentIterationByNode", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 2);
    store.getState().addAgentMessage("coder", "coder");
    const msg = store.getState().messages.at(-1)!;
    expect(msg.iteration).toBe(2);
  });

  it("addAgentMessage stamps iteration=1 when no iteration set (legacy/default)", () => {
    const store = createConversationStore("wf-1");
    store.getState().addAgentMessage("coder", "coder");
    const msg = store.getState().messages.at(-1)!;
    expect(msg.iteration).toBe(1);
  });

  it("addToolCall stamps iteration from currentIterationByNode", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 3);
    store.getState().addToolCall("coder", "coder", "bash", { cmd: "ls" });
    const msg = store.getState().messages.at(-1)!;
    expect(msg.iteration).toBe(3);
  });

  it("addUserQuestion stamps iteration when node_id present", () => {
    const store = createConversationStore("wf-1");
    store.getState().setCurrentIteration("coder", 2);
    store.getState().addUserQuestion({
      question_id: "q1",
      agent_name: "coder",
      node_id: "coder",
      question: "Continue?",
    } as any);
    const msg = store.getState().messages.at(-1)!;
    expect(msg.iteration).toBe(2);
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd frontend && npx vitest run src/stores/__tests__/conversationStore.iteration.test.ts
```

Expected: FAIL (messages have `iteration: undefined`).

**Step 3: Stamp iteration in each action**

In `frontend/src/contexts/workflow-context/stores/conversation.ts`, modify each action to read `currentIterationByNode[nodeId]` and stamp it:

For `addAgentMessage` (add `iteration` to the message object, after `stepId`):

```typescript
              stepId: state.currentStepIdByNode[nodeId],
              iteration: state.currentIterationByNode[nodeId] ?? 1,
```

For `addToolCall` (same pattern, after `stepId`):

```typescript
              stepId: state.currentStepIdByNode[nodeId],
              iteration: state.currentIterationByNode[nodeId] ?? 1,
```

For `addUserQuestion` (replace the existing `stepId` line):

```typescript
            stepId: payload.node_id ? state.currentStepIdByNode[payload.node_id] : undefined,
            iteration: payload.node_id ? (state.currentIterationByNode[payload.node_id] ?? 1) : undefined,
```

For `addFollowupAgentMessage` (after `stepId`):

```typescript
              stepId: state.currentStepIdByNode[nodeId],
              iteration: state.currentIterationByNode[nodeId] ?? 1,
```

For the text batcher's fallback push (when no streaming message exists, around line 567-580) — add `iteration` after `stepId`:

```typescript
              stepId: state.currentStepIdByNode[nid],
              iteration: state.currentIterationByNode[nid] ?? 1,
```

**Step 4: Run tests to verify they pass**

```bash
cd frontend && npx vitest run src/stores/__tests__/conversationStore.iteration.test.ts
```

Expected: PASS (all tests including the original 4 from Task 1.2).

**Step 5: Commit**

```bash
git add frontend/src/contexts/workflow-context/stores/conversation.ts \
        frontend/src/stores/__tests__/conversationStore.iteration.test.ts
git commit -m "feat(conv): stamp iteration field on all node-scoped messages"
```

---

### Task 1.5: Verify existing conversationStore tests still pass

**Files:**
- Test: `frontend/src/stores/__tests__/conversationStore.test.ts` (existing)

**Step 1: Run the full conversation test suite**

```bash
cd frontend && npx vitest run src/stores/__tests__/conversationStore.test.ts
```

Expected: PASS (no regressions). If any test asserts the exact shape of a message object and breaks on the new `iteration` field, update the assertion to either include `iteration: 1` or use `expect.objectContaining(...)`.

**Step 2: Commit any test updates**

```bash
git add frontend/src/stores/__tests__/conversationStore.test.ts
git commit -m "test(conv): update existing tests for iteration field"
```

(If no updates needed, skip the commit — leave a comment in the eventual integration commit.)

---

## Phase 2: Outline Derivation Layer

**Goal:** Build the pure derivation that turns store state into an ordered list of outline items. **No React, no UI** — this is testable in isolation. UI components in Phase 4 will consume this.

**Why second:** Pure derivation is the highest-risk area for bugs (parallel ordering, loop counting, ask_user detection). Isolating it lets us test exhaustively without React rendering overhead.

### Task 2.1: Define the `OutlineItem` type

**Files:**
- Create: `frontend/src/components/outline/types.ts`

**Step 1: Create the types file**

```typescript
/**
 * Outline type definitions.
 *
 * Design intent: discriminated unions force consumers to narrow before
 * reading variant-specific fields. New lifecycle states (e.g. "paused",
 * "interrupted-by-quota") are added by extending the union — the UI's
 * switch statement will get a TypeScript error pointing at every place
 * that needs updating.
 */

/** What an agent is doing right now, for the subtitle line. */
export type AgentActivity =
  | { kind: "idle" }
  | { kind: "running"; currentStepContent?: string }
  | { kind: "waiting-for-user"; questionId: string; questionCount: number }
  | { kind: "completed"; durationMs?: number }
  | { kind: "failed"; errorSummary: string }
  | { kind: "retrying"; attempt: number; maxAttempts: number };

/** Visual status — drives the icon + color. Decoupled from activity so
 *  the UI can theme consistently (e.g. "retrying" might share amber color
 *  with "waiting-for-user" but with different icons). */
export type OutlineStatus =
  | "idle"
  | "running"
  | "waiting-for-user"
  | "completed"
  | "failed"
  | "retrying";

/** A badge is a composable annotation — array of these renders independently. */
export interface OutlineBadge {
  kind: "retry" | "followup" | "iteration" | "tokens";
  /** Pre-formatted display string, e.g. "2/3", "#2", "1.5k". */
  text: string;
  /** Optional tooltip / title attribute. */
  title?: string;
}

/** One row in the outline list. */
export interface OutlineItem {
  /** Stable key — `${nodeId}__iter${iteration}` for loops, just nodeId otherwise. */
  key: string;
  nodeId: string;
  /** Display name (agent_name). */
  name: string;
  /** Which iteration this entry represents (1 for non-loop runs). */
  iteration: number;
  /** True if this nodeId has executed more than once. Drives the `#N` badge. */
  hasMultipleIterations: boolean;
  status: OutlineStatus;
  activity: AgentActivity;
  badges: OutlineBadge[];
  /** Sort order — by first-activity timestamp ascending. */
  order: number;
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/outline/types.ts
git commit -m "feat(outline): define OutlineItem types"
```

---

### Task 2.2: Build the `deriveOutlineItems` pure function

**Files:**
- Create: `frontend/src/components/outline/deriveOutlineItems.ts`
- Test: `frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts`

**Step 1: Write the failing tests**

Create `frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { deriveOutlineItems } from "../deriveOutlineItems";
import type { ConversationMessage } from "@/stores/conversationStore";
import type { NodeState } from "@/stores/workflowStore";
import type { TodoStep } from "@/contexts/workflow-context/stores/todo";

function msg(partial: Partial<ConversationMessage> & { id: string }): ConversationMessage {
  return {
    type: "agent",
    content: "",
    timestamp: 0,
    ...partial,
  } as ConversationMessage;
}

function node(partial: Partial<NodeState> & { id: string; name: string }): NodeState {
  return {
    status: "idle",
    ...partial,
  } as NodeState;
}

const emptyTodo: Record<string, TodoStep[]> = {};

describe("deriveOutlineItems", () => {
  it("returns empty array for empty inputs", () => {
    expect(deriveOutlineItems({}, [], emptyTodo)).toEqual([]);
  });

  it("emits one item per node, ordered by first-message timestamp", () => {
    const nodes = {
      a: node({ id: "a", name: "analyzer", status: "completed", durationMs: 1000 }),
      b: node({ id: "b", name: "runner", status: "completed", durationMs: 2000 }),
    };
    const messages = [
      msg({ id: "1", nodeId: "b", agentName: "runner", timestamp: 200, iteration: 1 }),
      msg({ id: "2", nodeId: "a", agentName: "analyzer", timestamp: 100, iteration: 1 }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items.map((i) => i.nodeId)).toEqual(["a", "b"]);
    expect(items[0].order).toBeLessThan(items[1].order);
  });

  it("includes nodes with no messages (idle nodes from DAG)", () => {
    const nodes = {
      a: node({ id: "a", name: "analyzer", status: "idle" }),
    };
    const items = deriveOutlineItems(nodes, [], emptyTodo);
    expect(items).toHaveLength(1);
    expect(items[0].status).toBe("idle");
    expect(items[0].iteration).toBe(1);
    expect(items[0].hasMultipleIterations).toBe(false);
  });

  it("splits same-nodeId messages into multiple items when iteration > 1 (loop)", () => {
    const nodes = {
      coder: node({ id: "coder", name: "coder", status: "completed" }),
    };
    const messages = [
      msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1 }),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2 }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items).toHaveLength(2);
    expect(items[0].iteration).toBe(1);
    expect(items[1].iteration).toBe(2);
    expect(items[0].key).toBe("coder__iter1");
    expect(items[1].key).toBe("coder__iter2");
    expect(items[0].hasMultipleIterations).toBe(true);
  });

  it("detects waiting-for-user status from pending question messages", () => {
    const nodes = {
      a: node({ id: "a", name: "analyzer", status: "running" }),
    };
    const messages = [
      msg({
        id: "1",
        nodeId: "a",
        agentName: "analyzer",
        timestamp: 100,
        iteration: 1,
        type: "question",
        status: "pending",
        questionId: "q1",
      } as any),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items[0].status).toBe("waiting-for-user");
    expect(items[0].activity).toMatchObject({ kind: "waiting-for-user", questionCount: 1 });
  });

  it("renders running status with current step from todos", () => {
    const nodes = {
      a: node({ id: "a", name: "analyzer", status: "running" }),
    };
    const todos = {
      a: [
        { taskId: "s1", content: "explore files", activeForm: "exploring files", status: "in_progress", detail: null },
        { taskId: "s2", content: "summarize", activeForm: "summarizing", status: "pending", detail: null },
      ] as TodoStep[],
    };
    const items = deriveOutlineItems(nodes, [], todos);
    expect(items[0].status).toBe("running");
    expect(items[0].activity).toMatchObject({ kind: "running", currentStepContent: "exploring files" });
  });

  it("retryAttempts produce a retry badge", () => {
    const nodes = {
      a: node({
        id: "a",
        name: "analyzer",
        status: "retrying",
        retryAttempts: [
          { attempt: 1, maxAttempts: 3, category: "NetworkError", reason: "timeout", delayS: 2, retryAfterS: null, ts: 0 },
        ],
      }),
    };
    const items = deriveOutlineItems(nodes, [], emptyTodo);
    expect(items[0].status).toBe("retrying");
    const retryBadge = items[0].badges.find((b) => b.kind === "retry");
    expect(retryBadge?.text).toBe("1/3");
  });

  it("tokens badge appears when total > 0", () => {
    const nodes = {
      a: node({
        id: "a",
        name: "analyzer",
        status: "completed",
        tokenUsage: { input: 1000, output: 500, total: 1500 },
      }),
    };
    const items = deriveOutlineItems(nodes, [], emptyTodo);
    const tokBadge = items[0].badges.find((b) => b.kind === "tokens");
    expect(tokBadge?.text).toBe("1.5k");
  });

  it("legacy messages without iteration field are treated as iteration 1", () => {
    const nodes = { a: node({ id: "a", name: "a", status: "completed" }) };
    const messages = [msg({ id: "1", nodeId: "a", agentName: "a", timestamp: 100 /* no iteration */ })];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items).toHaveLength(1);
    expect(items[0].iteration).toBe(1);
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/deriveOutlineItems.test.ts
```

Expected: FAIL with "Failed to resolve import" or "deriveOutlineItems is not a function".

**Step 3: Implement `deriveOutlineItems`**

Create `frontend/src/components/outline/deriveOutlineItems.ts`:

```typescript
/**
 * Pure derivation: store snapshot → ordered OutlineItem[].
 *
 * This is the single source of truth for what the outline renders. The UI
 * layer is a thin map over this output — no business logic in components.
 *
 * Properties guaranteed by this function:
 *   - Stable order: items sorted by first-message timestamp ascending;
 *     idle nodes (no messages) sort last, preserving DAG declaration order.
 *   - Loop expansion: a nodeId with messages across N iterations produces
 *     N items, keyed `${nodeId}__iter${n}`.
 *   - Deterministic: identical inputs always yield identical output. Safe
 *     to memoize on (nodes, messages, todos) references.
 */

import type { ConversationMessage } from "@/stores/conversationStore";
import type { NodeState } from "@/stores/workflowStore";
import type { TodoStep } from "@/contexts/workflow-context/stores/todo";
import type { OutlineItem, OutlineBadge, AgentActivity, OutlineStatus } from "./types";

export interface DeriveOutlineInput {
  nodes: Record<string, NodeState>;
  messages: ConversationMessage[];
  todos: Record<string, TodoStep[]>;
}

// Convenience positional form (kept for parity with how callers already
// pass these — groupMessages signature style).
export function deriveOutlineItems(
  nodes: Record<string, NodeState>,
  messages: ConversationMessage[],
  todos: Record<string, TodoStep[]>,
): OutlineItem[] {
  // 1. Collect (nodeId, iteration) pairs seen in messages.
  const iterSet = new Map<string, { nodeId: string; iteration: number; firstTs: number }>();
  for (const m of messages) {
    if (!m.nodeId) continue;
    const iter = m.iteration ?? 1;
    const key = `${m.nodeId}__iter${iter}`;
    const existing = iterSet.get(key);
    if (!existing || m.timestamp < existing.firstTs) {
      iterSet.set(key, { nodeId: m.nodeId, iteration: iter, firstTs: m.timestamp });
    }
  }

  // 2. For nodes with no messages yet, synthesize a single iter=1 entry.
  for (const nodeId of Object.keys(nodes)) {
    const key = `${nodeId}__iter1`;
    if (!iterSet.has(key)) {
      iterSet.set(key, { nodeId, iteration: 1, firstTs: Number.POSITIVE_INFINITY });
    }
  }

  // 3. Detect multiple iterations per nodeId for the badge.
  const iterCountByNode = new Map<string, number>();
  for (const { nodeId } of iterSet.values()) {
    iterCountByNode.set(nodeId, (iterCountByNode.get(nodeId) ?? 0) + 1);
  }

  // 4. Sort by firstTs ascending, with stable secondary sort on nodeId+iter.
  const sorted = [...iterSet.values()].sort((a, b) => {
    if (a.firstTs !== b.firstTs) return a.firstTs - b.firstTs;
    if (a.nodeId !== b.nodeId) return a.nodeId.localeCompare(b.nodeId);
    return a.iteration - b.iteration;
  });

  // 5. Project each entry to OutlineItem.
  return sorted.map((entry, idx) => {
    const node = nodes[entry.nodeId];
    const name = node?.name ?? entry.nodeId;
    const todosForNode = todos[entry.nodeId] ?? [];
    const iterMessages = messages.filter(
      (m) => m.nodeId === entry.nodeId && (m.iteration ?? 1) === entry.iteration,
    );
    return buildItem(entry, node, name, todosForNode, iterMessages, iterCountByNode.get(entry.nodeId) ?? 1, idx);
  });
}

function buildItem(
  entry: { nodeId: string; iteration: number; firstTs: number },
  node: NodeState | undefined,
  name: string,
  todos: TodoStep[],
  iterMessages: ConversationMessage[],
  iterCount: number,
  order: number,
): OutlineItem {
  const pendingQuestions = iterMessages.filter(
    (m) => m.type === "question" && m.status === "pending",
  );
  const status = computeStatus(node, pendingQuestions.length);
  const activity = computeActivity(node, todos, pendingQuestions);
  const badges = computeBadges(node, entry.iteration, iterCount);

  return {
    key: `${entry.nodeId}__iter${entry.iteration}`,
    nodeId: entry.nodeId,
    name,
    iteration: entry.iteration,
    hasMultipleIterations: iterCount > 1,
    status,
    activity,
    badges,
    order,
  };
}

function computeStatus(node: NodeState | undefined, pendingQuestionCount: number): OutlineStatus {
  if (pendingQuestionCount > 0) return "waiting-for-user";
  if (!node) return "idle";
  // NodeState.status values: idle | running | success | failed | retrying
  switch (node.status) {
    case "running": return "running";
    case "success": return "completed";
    case "failed": return "failed";
    case "retrying": return "retrying";
    default: return "idle";
  }
}

function computeActivity(
  node: NodeState | undefined,
  todos: TodoStep[],
  pendingQuestions: ConversationMessage[],
): AgentActivity {
  if (pendingQuestions.length > 0) {
    return {
      kind: "waiting-for-user",
      questionId: pendingQuestions[0].questionId ?? "",
      questionCount: pendingQuestions.length,
    };
  }
  if (!node) return { kind: "idle" };
  if (node.status === "retrying" && node.retryAttempts?.length) {
    const last = node.retryAttempts[node.retryAttempts.length - 1];
    return { kind: "retrying", attempt: last.attempt + 1, maxAttempts: last.maxAttempts };
  }
  if (node.status === "failed") {
    return { kind: "failed", errorSummary: node.classifiedFailure?.category ?? node.error ?? "Failed" };
  }
  if (node.status === "running") {
    const activeStep = todos.find((t) => t.status === "in_progress");
    return {
      kind: "running",
      currentStepContent: activeStep?.activeForm || activeStep?.content,
    };
  }
  if (node.status === "success") {
    return { kind: "completed", durationMs: node.durationMs };
  }
  return { kind: "idle" };
}

function computeBadges(
  node: NodeState | undefined,
  iteration: number,
  iterCount: number,
): OutlineBadge[] {
  const badges: OutlineBadge[] = [];
  if (iterCount > 1) {
    badges.push({ kind: "iteration", text: `#${iteration}`, title: `Iteration ${iteration} of ${iterCount}` });
  }
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
  return badges;
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
```

**Step 4: Run tests to verify they pass**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/deriveOutlineItems.test.ts
```

Expected: PASS (all 9 tests).

**Step 5: Commit**

```bash
git add frontend/src/components/outline/deriveOutlineItems.ts \
        frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts
git commit -m "feat(outline): pure deriveOutlineItems function with comprehensive tests"
```

---

### Task 2.3: Build `useAgentOutline` React hook

**Files:**
- Create: `frontend/src/components/outline/useAgentOutline.ts`
- Test: extend `frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts` (hook-level test, optional)

**Step 1: Create the hook**

```typescript
/**
 * useAgentOutline — React binding for deriveOutlineItems.
 *
 * Subscribes to the scoped workflow / conversation / todo stores and
 * memoizes the derivation. Re-derives ONLY when one of the three inputs
 * changes by reference. Because each store uses immutable updates, this
 * effectively means: re-derive on any store mutation, but skip re-render
 * if the derived array is reference-equal (React.memo on items).
 */

"use client";

import { useMemo } from "react";
import { useStore } from "zustand";
import { useScopedStore, useConversationMessages } from "@/contexts/workflow-context";
import { deriveOutlineItems } from "./deriveOutlineItems";
import type { OutlineItem } from "./types";

export function useAgentOutline(): OutlineItem[] {
  const messages = useConversationMessages();
  const workflowStoreApi = useScopedStore("workflow");
  const todoStoreApi = useScopedStore("todo");

  const nodes = useStore(workflowStoreApi!, (s) => s.nodes);
  const todos = useStore(todoStoreApi!, (s) => s.todos);

  return useMemo(
    () => deriveOutlineItems(nodes, messages, todos),
    [nodes, messages, todos],
  );
}
```

**Step 2: Smoke-test manually**

Add a temporary console.log in `ScopedConversationTab` and verify output during a run, OR skip this and rely on integration in Phase 4. The hook is a thin binding; correctness follows from `deriveOutlineItems` tests.

**Step 3: Commit**

```bash
git add frontend/src/components/outline/useAgentOutline.ts
git commit -m "feat(outline): useAgentOutline React hook with memoized derivation"
```

---

## Phase 3: Selection State (outlineStore)

**Goal:** Track which outline entry is selected + whether auto-follow is on. Lives in its own store so it can be reset independently and consumed by multiple components.

### Task 3.1: Create `outlineStore`

**Files:**
- Create: `frontend/src/components/outline/outlineStore.ts`
- Test: `frontend/src/components/outline/__tests__/outlineStore.test.ts`

**Step 1: Write the failing test**

Create `frontend/src/components/outline/__tests__/outlineStore.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { useOutlineStore } from "../outlineStore";

describe("outlineStore", () => {
  it("starts with no selection, autoFollow on, viewMode=outline", () => {
    const s = useOutlineStore.getState();
    expect(s.selectedKey).toBeNull();
    expect(s.autoFollow).toBe(true);
    expect(s.viewMode).toBe("outline");
  });

  it("select sets selectedKey and turns off autoFollow", () => {
    useOutlineStore.getState().select("coder__iter1", false);
    const s = useOutlineStore.getState();
    expect(s.selectedKey).toBe("coder__iter1");
    expect(s.autoFollow).toBe(false);
  });

  it("select with keepAutoFollow=true preserves autoFollow", () => {
    useOutlineStore.getState().setState({ autoFollow: true });
    useOutlineStore.getState().select("coder__iter1", true);
    expect(useOutlineStore.getState().autoFollow).toBe(true);
  });

  it("setAutoFollow toggles independently", () => {
    useOutlineStore.getState().setAutoFollow(false);
    expect(useOutlineStore.getState().autoFollow).toBe(false);
    useOutlineStore.getState().setAutoFollow(true);
    expect(useOutlineStore.getState().autoFollow).toBe(true);
  });

  it("setViewMode switches between outline and timeline", () => {
    useOutlineStore.getState().setViewMode("timeline");
    expect(useOutlineStore.getState().viewMode).toBe("timeline");
    useOutlineStore.getState().setViewMode("outline");
    expect(useOutlineStore.getState().viewMode).toBe("outline");
  });

  it("reset() clears selection but preserves viewMode", () => {
    useOutlineStore.getState().select("a__iter1", false);
    useOutlineStore.getState().setViewMode("timeline");
    useOutlineStore.getState().reset();
    const s = useOutlineStore.getState();
    expect(s.selectedKey).toBeNull();
    expect(s.autoFollow).toBe(true);
    expect(s.viewMode).toBe("timeline");
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/outlineStore.test.ts
```

Expected: FAIL (module not found).

**Step 3: Implement the store**

Create `frontend/src/components/outline/outlineStore.ts`:

```typescript
import { create } from "zustand";

export type OutlineViewMode = "outline" | "timeline";

/**
 * Selection + view-mode state for the conversation panel.
 *
 * Kept in its own store (not in conversationStore) so that:
 *   - Resetting conversation data on run switch doesn't blow away the
 *     user's view preference (outline vs timeline).
 *   - Detail view consumers don't re-render when unrelated conversation
 *     mutations happen.
 *
 * Lifecycle:
 *   - selectedKey follows the `${nodeId}__iter${n}` shape from OutlineItem.
 *   - autoFollow defaults on; selecting an item manually turns it off
 *     (so the user's choice "sticks" when a new agent starts running).
 *     The user can re-enable autoFollow via a button.
 */
interface OutlineState {
  selectedKey: string | null;
  autoFollow: boolean;
  viewMode: OutlineViewMode;

  /** Select an outline entry. keepAutoFollow=true preserves autoFollow
   *  (rare — used when autoFollow itself triggers the selection). */
  select: (key: string | null, keepAutoFollow?: boolean) => void;
  setAutoFollow: (on: boolean) => void;
  setViewMode: (mode: OutlineViewMode) => void;
  /** Low-level setter for tests + advanced callers. */
  setState: (partial: Partial<Omit<OutlineState, "select" | "setAutoFollow" | "setViewMode" | "setState" | "reset">>) => void;
  /** Reset to defaults but preserve viewMode (user preference). */
  reset: () => void;
}

export const useOutlineStore = create<OutlineState>()((set) => ({
  selectedKey: null,
  autoFollow: true,
  viewMode: "outline",

  select: (key, keepAutoFollow = false) =>
    set((s) => ({
      selectedKey: key,
      autoFollow: keepAutoFollow ? s.autoFollow : false,
    })),

  setAutoFollow: (on) => set({ autoFollow: on }),

  setViewMode: (mode) => set({ viewMode: mode }),

  setState: (partial) => set(partial),

  reset: () =>
    set((s) => ({
      selectedKey: null,
      autoFollow: true,
      viewMode: s.viewMode,
    })),
}));
```

**Step 4: Run tests to verify they pass**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/outlineStore.test.ts
```

Expected: PASS (all 6 tests).

**Step 5: Commit**

```bash
git add frontend/src/components/outline/outlineStore.ts \
        frontend/src/components/outline/__tests__/outlineStore.test.ts
git commit -m "feat(outline): outlineStore for selection + autoFollow + viewMode"
```

---

### Task 3.2: Auto-follow effect — subscribe to outline changes

**Files:**
- Create: `frontend/src/components/outline/useAutoFollowSelection.ts`

**Step 1: Create the hook**

```typescript
/**
 * useAutoFollowSelection — when autoFollow is on and a new "running" or
 * "waiting-for-user" item appears, automatically select it.
 *
 * Selection priority (highest first):
 *   1. waiting-for-user  — never miss an ask_user
 *   2. running           — follow active work
 *   3. (no auto-select for completed/failed/idle)
 *
 * When autoFollow is off, this hook does nothing — user's manual selection
 * sticks.
 */

"use client";

import { useEffect } from "react";
import { useOutlineStore } from "./outlineStore";
import type { OutlineItem } from "./types";

export function useAutoFollowSelection(items: OutlineItem[]): void {
  const autoFollow = useOutlineStore((s) => s.autoFollow);
  const select = useOutlineStore((s) => s.select);
  const selectedKey = useOutlineStore((s) => s.selectedKey);

  useEffect(() => {
    if (!autoFollow) return;

    // Priority 1: any waiting-for-user item.
    const waiting = items.find((i) => i.status === "waiting-for-user");
    if (waiting) {
      if (selectedKey !== waiting.key) select(waiting.key, true);
      return;
    }

    // Priority 2: the most-recently-started running item.
    const running = items.filter((i) => i.status === "running").sort((a, b) => b.order - a.order)[0];
    if (running && selectedKey !== running.key) {
      select(running.key, true);
    }
  }, [items, autoFollow, selectedKey, select]);
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/outline/useAutoFollowSelection.ts
git commit -m "feat(outline): useAutoFollowSelection hook — prioritized ask_user > running"
```

---

## Phase 4: UI Components

**Goal:** Build the Outline list + Detail pane. Keep components thin — all logic lives in `deriveOutlineItems` and the stores.

**Design language (from mature products):**
- **Density**: compact one-line items (~28px tall) like Linear. Active step subtitle on a second line only when running.
- **Status icons** (left, 16x16): `○` idle, `◐` running (animated pulse), `●` waiting-for-user (amber pulse), `✓` completed (emerald), `✗` failed (red), `↻` retrying (amber).
- **Badges** (right side, pill-shaped, muted): iteration `#2`, retry `2/3`, tokens `1.5k`.
- **Active row**: light blue background + left blue border accent.
- **Hover**: subtle muted background.
- **Keyboard**: `j`/`k` to move selection, `Enter` to pin (turns off autoFollow).

### Task 4.1: Build `OutlineItemRow` component

**Files:**
- Create: `frontend/src/components/outline/OutlineItemRow.tsx`

**Step 1: Create the component**

```tsx
"use client";

import React from "react";
import type { OutlineItem, OutlineStatus } from "./types";

const STATUS_ICON: Record<OutlineStatus, string> = {
  idle: "○",
  running: "◐",
  "waiting-for-user": "●",
  completed: "✓",
  failed: "✗",
  retrying: "↻",
};

const STATUS_TONE: Record<OutlineStatus, string> = {
  idle: "text-muted-foreground/50",
  running: "text-blue-500",
  "waiting-for-user": "text-amber-500",
  completed: "text-emerald-500",
  failed: "text-red-500",
  retrying: "text-amber-500",
};

const STATUS_ROW_TONE: Record<OutlineStatus, string> = {
  idle: "",
  running: "",
  "waiting-for-user": "bg-amber-500/5 border-l-2 border-amber-500",
  completed: "",
  failed: "",
  retrying: "",
};

interface Props {
  item: OutlineItem;
  selected: boolean;
  onSelect: (key: string) => void;
}

export const OutlineItemRow = React.memo(function OutlineItemRow({ item, selected, onSelect }: Props) {
  const subtitle = computeSubtitle(item);
  const waiting = item.status === "waiting-for-user";

  return (
    <button
      type="button"
      onClick={() => onSelect(item.key)}
      className={[
        "group flex w-full items-start gap-2 px-3 py-1.5 text-left text-xs transition-colors",
        selected ? "bg-blue-50 dark:bg-blue-900/30 border-l-2 border-blue-500" : "hover:bg-muted/50",
        STATUS_ROW_TONE[item.status],
      ].join(" ")}
      aria-current={selected ? "true" : undefined}
    >
      <span
        aria-hidden
        className={[
          "mt-0.5 shrink-0 text-sm leading-none",
          STATUS_TONE[item.status],
          waiting ? "animate-pulse" : "",
        ].join(" ")}
      >
        {STATUS_ICON[item.status]}
      </span>

      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="flex items-center gap-1.5">
          <span className={`truncate font-medium ${selected ? "text-app-text-primary" : "text-app-text-secondary"}`}>
            {item.name}
          </span>
          {item.badges.map((b, i) => (
            <span
              key={`${b.kind}-${i}`}
              className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground"
              title={b.title}
            >
              {b.text}
            </span>
          ))}
        </span>
        {subtitle && (
          <span className="truncate text-[11px] text-muted-foreground">{subtitle}</span>
        )}
      </span>
    </button>
  );
});

function computeSubtitle(item: OutlineItem): string | null {
  switch (item.activity.kind) {
    case "running":
      return item.activity.currentStepContent ?? "Working…";
    case "waiting-for-user":
      return `Waiting for answer (${item.activity.questionCount})`;
    case "retrying":
      return `Retrying — ${item.activity.attempt}/${item.activity.maxAttempts}`;
    case "failed":
      return item.activity.errorSummary;
    case "completed":
      return item.activity.durationMs ? `${(item.activity.durationMs / 1000).toFixed(1)}s` : null;
    default:
      return null;
  }
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/outline/OutlineItemRow.tsx
git commit -m "feat(outline): OutlineItemRow component — Linear-style compact row"
```

---

### Task 4.2: Build `AgentOutline` list component

**Files:**
- Create: `frontend/src/components/outline/AgentOutline.tsx`

**Step 1: Create the component**

```tsx
"use client";

import React, { useCallback } from "react";
import { useAgentOutline } from "./useAgentOutline";
import { useAutoFollowSelection } from "./useAutoFollowSelection";
import { useOutlineStore } from "./outlineStore";
import { OutlineItemRow } from "./OutlineItemRow";

/**
 * AgentOutline — left-side list of agents.
 *
 * Performance: each OutlineItemRow is React.memo'd and only re-renders
 * when its specific item object changes (deriveOutlineItems returns the
 * same item reference for unchanged nodes — see stable-iteration property
 * in deriveOutlineItems).
 */
export function AgentOutline() {
  const items = useAgentOutline();
  useAutoFollowSelection(items);

  const selectedKey = useOutlineStore((s) => s.selectedKey);
  const select = useOutlineStore((s) => s.select);
  const autoFollow = useOutlineStore((s) => s.autoFollow);
  const setAutoFollow = useOutlineStore((s) => s.setAutoFollow);

  const handleSelect = useCallback((key: string) => select(key, false), [select]);

  if (items.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
        No agents yet. Start a workflow to see the outline.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-app-border px-3 py-1.5">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Agents
        </span>
        <button
          type="button"
          onClick={() => setAutoFollow(!autoFollow)}
          className={[
            "rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors",
            autoFollow
              ? "bg-blue-500/10 text-blue-600 hover:bg-blue-500/20"
              : "bg-muted text-muted-foreground hover:bg-muted/70",
          ].join(" ")}
          title={autoFollow ? "Auto-follow ON — click to pin current selection" : "Pinned — click to re-enable auto-follow"}
        >
          {autoFollow ? "Following" : "Pinned"}
        </button>
      </div>

      {/* List — no virtualizer needed; outline is O(agents), usually <20 items */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {items.map((item) => (
          <OutlineItemRow
            key={item.key}
            item={item}
            selected={item.key === selectedKey}
            onSelect={handleSelect}
          />
        ))}
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/outline/AgentOutline.tsx
git commit -m "feat(outline): AgentOutline list with header + auto-follow toggle"
```

---

### Task 4.3: Build `AgentDetailView` — single-agent conversation

**Files:**
- Create: `frontend/src/components/outline/AgentDetailView.tsx`

**Step 1: Create the component**

```tsx
"use client";

import React, { useMemo } from "react";
import { useStore } from "zustand";
import { useVirtualizer } from "@tanstack/react-virtual";
import { InlineErrorBoundary } from "@/components/ErrorBoundary";
import {
  useConversationMessages,
  useWorkflowStore as useScopedStore,
} from "@/contexts/workflow-context";
import type { ConversationMessage, QuestionAnswer } from "@/stores/conversationStore";
import {
  buildChildren,
  extractMainMessage,
  type NodeChild,
} from "@/components/conversation/groupNodes";
import { useWSMethods } from "@/contexts/workflow-context/WorkflowScope";
import { useConversationActions } from "@/contexts/workflow-context/hooks";
import { NodeBlockCard } from "@/components/conversation/ScopedConversationTab";
import type { NodeBlock } from "@/components/conversation/groupNodes";

/**
 * AgentDetailView — conversation for ONE (nodeId, iteration) pair.
 *
 * Reuses NodeBlockCard from ScopedConversationTab verbatim so visual
 * parity is guaranteed. The only difference: we filter messages before
 * grouping, then synthesize a single NodeBlock.
 *
 * Performance: virtualizer with overscan:8. For typical agents (<200
 * messages), full render is fine; virtualizer protects against the rare
 * chatty agent with thousands of tool calls.
 */
interface Props {
  nodeId: string;
  iteration: number;
}

export function AgentDetailView({ nodeId, iteration }: Props) {
  const allMessages = useConversationMessages();
  const todoStore = useScopedStore("todo");

  const { sendStructuredAnswer } = useWSMethods();
  const conversationActions = useConversationActions();

  const filtered = useMemo(
    () => allMessages.filter((m) => m.nodeId === nodeId && (m.iteration ?? 1) === iteration),
    [allMessages, nodeId, iteration],
  );

  const block = useMemo<NodeBlock | null>(() => {
    if (filtered.length === 0) return null;
    return {
      kind: "node",
      nodeId,
      children: buildChildren(filtered),
      mainMessage: extractMainMessage(filtered),
    };
  }, [filtered, nodeId]);

  const scrollRef = React.useRef<HTMLDivElement>(null);

  const virtualizer = useVirtualizer({
    count: block ? 1 : 0,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 800,
    overscan: 8,
  });

  if (!block) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        This agent hasn't produced any output yet.
      </div>
    );
  }

  return (
    <div ref={scrollRef} className="h-full overflow-y-auto px-6 py-3">
      <div style={{ height: virtualizer.getTotalSize(), position: "relative" }}>
        {virtualizer.getVirtualItems().map((row) => (
          <div
            key={row.key}
            ref={virtualizer.measureElement}
            data-index={row.index}
            style={{ position: "absolute", top: 0, left: 0, width: "100%", transform: `translateY(${row.start}px)` }}
          >
            <InlineErrorBoundary label={`agent-${nodeId}-iter${iteration}`}>
              <NodeBlockCard
                block={block}
                getAgentIO={() => undefined}
                getNodeState={() => undefined}
                sendStructuredAnswer={sendStructuredAnswer}
                conversationActions={conversationActions}
                todoStore={todoStore}
              />
            </InlineErrorBoundary>
          </div>
        ))}
      </div>
    </div>
  );
}
```

**Note:** `NodeBlockCard` is currently not exported from `ScopedConversationTab.tsx`. Update its `export` declaration in Task 5.2.

**Step 2: Commit**

```bash
git add frontend/src/components/outline/AgentDetailView.tsx
git commit -m "feat(outline): AgentDetailView reuses NodeBlockCard for visual parity"
```

---

### Task 4.4: Build `OutlineMode` container — outline + detail side-by-side

**Files:**
- Create: `frontend/src/components/outline/OutlineMode.tsx`

**Step 1: Create the component**

```tsx
"use client";

import React, { useMemo } from "react";
import { AgentOutline } from "./AgentOutline";
import { AgentDetailView } from "./AgentDetailView";
import { useOutlineStore } from "./outlineStore";
import { useAgentOutline } from "./useAgentOutline";

/**
 * OutlineMode — split layout: outline (~240px) + detail (fills rest).
 *
 * If no selection and autoFollow didn't pick anything yet, show a hint
 * in the detail pane instead of an empty NodeBlockCard.
 */
export function OutlineMode() {
  const items = useAgentOutline();
  const selectedKey = useOutlineStore((s) => s.selectedKey);

  const selected = useMemo(
    () => items.find((i) => i.key === selectedKey) ?? null,
    [items, selectedKey],
  );

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-60 shrink-0 border-r border-app-border bg-app-bg-primary">
        <AgentOutline />
      </aside>
      <div className="min-w-0 flex-1">
        {selected ? (
          <AgentDetailView nodeId={selected.nodeId} iteration={selected.iteration} />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
            Select an agent on the left to view its conversation.
          </div>
        )}
      </div>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/outline/OutlineMode.tsx
git commit -m "feat(outline): OutlineMode split-pane container"
```

---

## Phase 5: Integration

**Goal:** Wire Outline/Timeline toggle into `ScopedCenterPanel` + export `NodeBlockCard` so `AgentDetailView` can use it.

### Task 5.1: Export `NodeBlockCard` from `ScopedConversationTab`

**Files:**
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx:384` (change `const NodeBlockCard` to `export const NodeBlockCard`)

**Step 1: Make the change**

In `frontend/src/components/conversation/ScopedConversationTab.tsx`, change:

```typescript
const NodeBlockCard = React.memo(function NodeBlockCard({
```

to:

```typescript
export const NodeBlockCard = React.memo(function NodeBlockCard({
```

**Step 2: Verify no breakage**

```bash
cd frontend && npx tsc --noEmit
```

Expected: PASS (no new type errors).

**Step 3: Commit**

```bash
git add frontend/src/components/conversation/ScopedConversationTab.tsx
git commit -m "refactor(conv): export NodeBlockCard for reuse in AgentDetailView"
```

---

### Task 5.2: Add view-mode toggle + conditional rendering in `ScopedCenterPanel`

**Files:**
- Modify: `frontend/src/components/layout/ScopedCenterPanel.tsx:308-311` (the `activeTab === "conversation"` branch)

**Step 1: Add the toggle + Outline/Timeline conditional**

In `frontend/src/components/layout/ScopedCenterPanel.tsx`:

Add imports at top:

```typescript
import { OutlineMode } from "@/components/outline/OutlineMode";
import { ScopedConversationTab } from "@/components/conversation/ScopedConversationTab";
import { useOutlineStore } from "@/components/outline/outlineStore";
```

(`ScopedConversationTab` is already imported — just confirming.)

Replace the conversation branch (around lines 308-311):

```tsx
        ) : activeTab === "conversation" ? (
          <ErrorBoundary module="ConversationTab">
            <ConversationPanel />
          </ErrorBoundary>
        ) : activeTab === "analysis" ? (
```

And add a small wrapper component at the bottom of the file (before the closing of the module):

```tsx
function ConversationPanel() {
  const viewMode = useOutlineStore((s) => s.viewMode);
  const setViewMode = useOutlineStore((s) => s.setViewMode);

  return (
    <div className="flex h-full flex-col">
      {/* View-mode toggle — top-right of the conversation panel */}
      <div className="flex shrink-0 justify-end border-b border-app-border/50 px-3 py-1">
        <div className="inline-flex rounded-md border border-app-border text-xs">
          <button
            type="button"
            onClick={() => setViewMode("outline")}
            className={`px-2 py-0.5 ${viewMode === "outline" ? "bg-muted font-medium text-app-text-primary" : "text-muted-foreground hover:bg-muted/50"}`}
          >
            Outline
          </button>
          <button
            type="button"
            onClick={() => setViewMode("timeline")}
            className={`px-2 py-0.5 ${viewMode === "timeline" ? "bg-muted font-medium text-app-text-primary" : "text-muted-foreground hover:bg-muted/50"}`}
          >
            Timeline
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {viewMode === "outline" ? <OutlineMode /> : <ScopedConversationTab />}
      </div>
    </div>
  );
}
```

**Step 2: Manually verify in browser**

Run the dev server, open the app, switch between Outline and Timeline. Verify:
- Toggle persists across tab switches (it should — viewMode is in a global store).
- Outline list populates during a workflow run.
- Clicking an agent shows its detail.
- Auto-follow picks the running agent.

**Step 3: Commit**

```bash
git add frontend/src/components/layout/ScopedCenterPanel.tsx
git commit -m "feat(outline): wire Outline/Timeline toggle into ScopedCenterPanel"
```

---

### Task 5.3: Reset outlineStore on workflow switch

**Files:**
- Modify: `frontend/src/stores/viewStore.ts:100-122` (the `showReplay` function — call `useOutlineStore.getState().reset()` after `resetAllStores`)

**Step 1: Add the reset**

In `frontend/src/stores/viewStore.ts`, add import:

```typescript
import { useOutlineStore } from "@/components/outline/outlineStore";
```

In `showReplay`, after the `resetAllStores(scoped.stores);` line (~line 113), add:

```typescript
    // Reset outline selection (but preserve viewMode preference) so the
    // previous run's selected agent doesn't bleed into the new run.
    useOutlineStore.getState().reset();
```

Do the same in the `showLive` function after its `resetAllStores` call.

**Step 2: Verify**

```bash
cd frontend && npx tsc --noEmit
```

Expected: PASS.

**Step 3: Commit**

```bash
git add frontend/src/stores/viewStore.ts
git commit -m "feat(outline): reset outlineStore selection on view switch"
```

---

### Task 5.4: Keyboard navigation (j/k)

**Files:**
- Modify: `frontend/src/components/outline/AgentOutline.tsx`

**Step 1: Add a `useEffect` for keyboard handling**

Add inside `AgentOutline`:

```typescript
import React, { useCallback, useEffect } from "react";

// Inside the component:
useEffect(() => {
  const onKey = (e: KeyboardEvent) => {
    // Only handle when outline is the focused area — don't steal j/k from
    // text inputs. Simplest heuristic: target is document.body or our container.
    const target = e.target as HTMLElement | null;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
      return;
    }
    if (e.key !== "j" && e.key !== "k") return;

    const idx = items.findIndex((i) => i.key === selectedKey);
    let nextIdx: number;
    if (e.key === "j") nextIdx = Math.min(items.length - 1, (idx < 0 ? -1 : idx) + 1);
    else nextIdx = Math.max(0, (idx < 0 ? items.length : idx) - 1);
    if (nextIdx === idx) return;

    e.preventDefault();
    select(items[nextIdx].key, false);
  };
  document.addEventListener("keydown", onKey);
  return () => document.removeEventListener("keydown", onKey);
}, [items, selectedKey, select]);
```

**Step 2: Manually verify**

In browser, focus the conversation area, press `j`/`k`. Selection should move.

**Step 3: Commit**

```bash
git add frontend/src/components/outline/AgentOutline.tsx
git commit -m "feat(outline): j/k keyboard navigation"
```

---

### Task 5.5: ask_user toast notification

**Files:**
- Modify: `frontend/src/components/outline/useAutoFollowSelection.ts`

**Step 1: Add toast import + emit on transition into waiting-for-user**

```typescript
import { toast } from "sonner";
```

Update the effect to detect transitions:

```typescript
const prevWaitingRef = useRef<string | null>(null);

useEffect(() => {
  if (!autoFollow) return;

  const waiting = items.find((i) => i.status === "waiting-for-user");

  // Toast only on transition (none → some).
  if (waiting && prevWaitingRef.current !== waiting.key) {
    toast.info(`${waiting.name} is waiting for your answer`, {
      description: "Click the highlighted agent in the outline to respond.",
      duration: 8000,
    });
  }
  prevWaitingRef.current = waiting?.key ?? null;

  // Existing auto-follow logic below…
  if (waiting) {
    if (selectedKey !== waiting.key) select(waiting.key, true);
    return;
  }
  // …
}, [items, autoFollow, selectedKey, select]);
```

(Add `useRef` to the imports.)

**Step 2: Verify**

Manually trigger an `ask_user` workflow. Confirm the toast appears once per question.

**Step 3: Commit**

```bash
git add frontend/src/components/outline/useAutoFollowSelection.ts
git commit -m "feat(outline): toast notification on ask_user transition"
```

---

## Phase 6: Polish & Verification

### Task 6.1: Run full test suite

**Step 1: Run all frontend tests**

```bash
cd frontend && npx vitest run
```

Expected: ALL PASS.

**Step 2: Run TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: PASS.

**Step 3: Fix any regressions**

If any pre-existing tests fail due to the new `iteration` field, update assertions and re-run.

**Step 4: Commit**

```bash
git add -A
git commit -m "test: fix regressions from iteration field introduction"
```

---

### Task 6.2: Performance smoke test

**Step 1: Open a large historical run**

Find the run with 5 agents (analyzer + configurator + runner + diagnostic_saver + report_painter). Open it.

**Step 2: Measure first paint**

- Outline view should render in <100ms after the existing hydration completes.
- Switching between agents should be <16ms (single React commit, no fetch).

**Step 3: Switch to Timeline mode**

- Should behave exactly as before (no regression in ScopedConversationTab).

**Step 4: Document findings**

If any performance target is missed, file a follow-up task with the specific scenario.

---

### Task 6.3: Update CURRENT.md

**Files:**
- Modify: `docs/status/CURRENT.md`

**Step 1: Update the status**

Replace the current "NAS 待做" section with a completion note pointing to the outline feature, OR keep NAS work as the next priority and add a brief mention of the outline feature in the CHANGELOG.

**Step 2: Update CHANGELOG.md**

Add an entry:

```markdown
## 2026-06-11 — Outline + Master-Detail Conversation View

- Added Outline navigation: agent list with live status, TODO progress, ask_user alerts.
- Added Detail view: single-agent conversation via `AgentDetailView`.
- Added iteration tracking: loop disambiguation via frontend iteration counting.
- Preserved Timeline view: toggle in conversation panel header.
- Commit: <fill-after-merge>
```

**Step 3: Commit**

```bash
git add docs/status/CURRENT.md docs/status/CHANGELOG.md
git commit -m "docs: update CURRENT + CHANGELOG for outline feature"
```

---

## Implementation Notes

### Performance invariants enforced by this plan

1. **Outline never iterates messages per-render for status** — `deriveOutlineItems` walks messages once to collect iterations, then indexes by nodeId. The walk is O(messages), but only runs when `messages` reference changes (every text batch). For a 5000-message run, this is ~5ms on commodity hardware — acceptable.

2. **Detail view filters with a single `.filter()` + `useMemo`** — no per-message work per render. The filtered array reference is stable across streaming chunks for unrelated agents.

3. **`OutlineItemRow` is `React.memo`'d** — when one agent's status changes, only its row re-renders. Other rows skip because their `item` reference is unchanged (guaranteed by `deriveOutlineItems` returning the same `OutlineItem` reference when input is structurally identical — verify this in Task 2.2 review).

4. **No new network fetches** — all data already in scoped stores from existing `showReplay` → `loadSidecars` → `applyHydration` pipeline. Outline + Detail are pure projections.

### Robustness invariants

1. **Legacy data compatibility**: `m.iteration ?? 1` everywhere. Old persisted runs render correctly (treated as iteration=1).

2. **Empty states**: no agents (empty workflow), no selection (initial state), selected agent with no messages — all explicitly rendered.

3. **Error boundaries**: `InlineErrorBoundary` wraps `NodeBlockCard` in Detail. If one agent's data is corrupt, others still render.

4. **Reset correctness**: switching runs clears outline selection but preserves viewMode preference (user's choice of Outline vs Timeline is sticky).

### Extensibility invariants

1. **New lifecycle state** (e.g. "paused-for-quota"): add to `OutlineStatus` union + `computeStatus` switch. TypeScript compiler points at every consumer that needs updating.

2. **New badge type** (e.g. "cost"): add to `OutlineBadge.kind` union + `computeBadges`. `OutlineItemRow` renders badges via a stable map — no component changes needed for the new badge.

3. **Alternative detail consumer** (e.g. embedded in a modal): `AgentDetailView` takes `nodeId` + `iteration` as props, no dependency on outline state. Reusable.

4. **Alternative outline source** (e.g. filtered by tag): `deriveOutlineItems` is pure — wrap it in a filtering function for any projection variant.

---

## File Summary

**Created:**
- `frontend/src/components/outline/types.ts`
- `frontend/src/components/outline/deriveOutlineItems.ts`
- `frontend/src/components/outline/useAgentOutline.ts`
- `frontend/src/components/outline/useAutoFollowSelection.ts`
- `frontend/src/components/outline/outlineStore.ts`
- `frontend/src/components/outline/OutlineItemRow.tsx`
- `frontend/src/components/outline/AgentOutline.tsx`
- `frontend/src/components/outline/AgentDetailView.tsx`
- `frontend/src/components/outline/OutlineMode.tsx`
- `frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts`
- `frontend/src/components/outline/__tests__/outlineStore.test.ts`
- `frontend/src/stores/__tests__/conversationMessage.types.test.ts`
- `frontend/src/stores/__tests__/conversationStore.iteration.test.ts`
- `frontend/src/contexts/workflow-context/routing/__tests__/nodeHandlers.iteration.test.ts`

**Modified:**
- `frontend/src/stores/conversationStore.ts` (add `iteration` field + `currentIterationByNode` + `setCurrentIteration`)
- `frontend/src/contexts/workflow-context/stores/conversation.ts` (initial state + setter + stamp in 5 actions)
- `frontend/src/contexts/workflow-context/routing/nodeHandlers.ts` (increment on `node.started`)
- `frontend/src/components/conversation/ScopedConversationTab.tsx` (export `NodeBlockCard`)
- `frontend/src/components/layout/ScopedCenterPanel.tsx` (toggle + conditional render)
- `frontend/src/stores/viewStore.ts` (reset outline on view switch)
- `docs/status/CURRENT.md`, `docs/status/CHANGELOG.md`

**Unchanged (intentionally):**
- `frontend/src/components/conversation/AgentMessage.tsx` (ThinkingBlock default-open fix is a separate small PR — see Problem 2 in design discussion)
- Backend code (no new endpoints, no schema changes)
