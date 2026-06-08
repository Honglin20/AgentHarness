# WS Event Replay Idempotency Fix

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Eliminate duplicate UI state caused by WS reconnect replaying events that have already been processed, with `chat.question` (ask_user) as the primary user-facing symptom.

**Architecture:** Two-layer defense. Layer 1: Frontend tracks the last seen `seq` number and sends it on reconnect, so the backend only replays genuinely missed events. Layer 2: Every stateful event handler in `routeEvent.ts` guards against duplicate processing by checking existing store state before mutating. Together these prevent the root cause (full replay) and mitigate any remaining edge cases (per-handler idempotency).

**Tech Stack:** React hooks, Zustand stores, WebSocket, Python asyncio Bus

---

## Root Cause Analysis

### The Bug

User answers an ask_user question, but after a page refresh or network reconnect, the question card reappears as if never answered.

### The Chain

```
WS onclose → autoReconnect → connect(sinceSeq=0)
  → Server subscribe(since_seq=0) → Bus replays ALL buffered events
  → chat.question {question_id: "q1"} arrives again
  → routeEvent.ts case "chat.question": NO dedup guard
  → conversationStore.addUserQuestion() appends duplicate message
  → pendingQuestionId set to "q1" again → ChatInput shows input field
```

### Why sinceSeq=0 Is Always Hardcoded

`useWorkflowWS.ts:39` passes `sinceSeq: 0` to `useWebSocket`. The hook never updates this value — it's a static prop. On reconnect (`onclose` → `connect()`), the same `0` is reused, causing full buffer replay every time.

### Why Per-Handler Idempotency Is Also Needed

Even with correct `sinceSeq`, edge cases remain: server restart clears the buffer, multiple WS connections for the same workflow, or rapid connect/disconnect cycles. Each handler must be self-protecting.

---

## Task Breakdown

### Task 1: Track last seen seq on the frontend

**Files:**
- Modify: `frontend/src/hooks/useWebSocket.ts`
- Modify: `frontend/src/contexts/workflow-context/useWorkflowWS.ts`
- Test: `tests/` (manual verification — no unit test infrastructure for hooks)

**Step 1: Add `_lastSeq` tracking to useWebSocket**

In `frontend/src/hooks/useWebSocket.ts`, add a ref to track the highest seq seen:

```typescript
// Add inside useWebSocket function, after existing refs (line ~38)
const lastSeqRef = useRef<number>(0);
```

In the `onmessage` handler (line ~89), extract and store the seq:

```typescript
ws.onmessage = (e) => {
  try {
    const event: WSEvent = JSON.parse(e.data);
    if (typeof event.seq === "number" && event.seq > lastSeqRef.current) {
      lastSeqRef.current = event.seq;
    }
    onEventRef.current?.(event);
  } catch {}
};
```

**Step 2: Use lastSeqRef in connect URL instead of the static prop**

Change the `sinceSeq` usage in `connect()` (line ~77) to prefer the tracked value:

```typescript
// Replace:
//   if (sinceSeq !== undefined) {
//     url += `&since_seq=${sinceSeq}`;
//   }
// With:
const effectiveSeq = lastSeqRef.current > 0 ? lastSeqRef.current : sinceSeq;
if (effectiveSeq !== undefined) {
  url += `&since_seq=${effectiveSeq}`;
}
```

This means: on first connect, use the `sinceSeq` prop (0). On reconnect, use the last seq we actually saw — so only genuinely missed events are replayed.

**Step 3: Update useWorkflowWS to NOT hardcode sinceSeq=0**

In `frontend/src/contexts/workflow-context/useWorkflowWS.ts:39`, change:

```typescript
// Replace: sinceSeq: 0,
// With:    sinceSeq: 0,  // initial connect replays from start; reconnects use tracked seq
```

The prop is still `0` for the initial connect (correct — we want all buffered events on first load). The improvement is that reconnects now use `lastSeqRef.current` from inside `useWebSocket`.

**Step 4: Verify manually**

1. Start a workflow that triggers ask_user
2. Answer the question
3. Open browser DevTools → Network → WS → observe the connection
4. Kill the WS connection (DevTools → block ws:// temporarily)
5. Watch it reconnect — verify the new WS URL has `since_seq=<number>` not `since_seq=0`
6. Verify the question card does NOT reappear

**Step 5: Commit**

```
feat: track last WS seq for delta replay on reconnect
```

---

### Task 2: Add chat.question idempotency guard

**Files:**
- Modify: `frontend/src/contexts/workflow-context/routeEvent.ts:336-356`
- Test: manual verification

**Step 1: Add dedup check before processing chat.question**

In `routeEvent.ts`, modify the `chat.question` case (line ~336):

```typescript
case "chat.question": {
  const p = payload<ChatQuestionPayload>(event);
  // Idempotent: skip if this question was already processed (WS replay guard)
  const alreadyExists = stores.conversation.getState().messages.some(
    (m) => m.type === "question" && m.questionId === p.question_id
  );
  if (alreadyExists) break;

  stores.chat.getState().addAgentQuestion(p.question_id, p.question);
  const conv = stores.conversation.getState();
  // ... rest of existing handler unchanged
```

**Step 2: Verify**

1. Start a workflow with ask_user
2. Answer the question
3. Refresh the page (which triggers WS reconnect with full replay)
4. Verify: no duplicate question card appears

**Step 3: Commit**

```
fix: guard chat.question against WS replay duplication
```

---

### Task 3: Add todo.created / todo.updated idempotency guards

**Files:**
- Modify: `frontend/src/contexts/workflow-context/routeEvent.ts:413-431`

**Step 1: Add task_id dedup to todo.created handler**

The `handleTodoCreated` in `workflowStores.ts` already has dedup (fixed in prior session). Verify it's present. If so, no change needed — just confirm.

Read `workflowStores.ts` `handleTodoCreated` and confirm the `existingIds` Set check exists. If missing, add it.

**Step 2: Add guard to todo.updated handler**

In `routeEvent.ts`, the `todo.updated` case (line ~421) calls `handleTodoUpdated` which does `const steps = state.todos[nodeId]; if (!steps) return state;`. This is already safe — if the node has no steps, it's a no-op. If the update was already applied (same task_id, same status), the map returns the same object — harmless no-op.

No change needed. Confirm and move on.

**Step 3: Commit** (only if changes were needed)

```
fix: guard todo events against WS replay duplication
```

---

### Task 4: Add node lifecycle idempotency guards

**Files:**
- Modify: `frontend/src/contexts/workflow-context/routeEvent.ts:134-175`

**Step 1: Guard node.started against duplicate**

In the `node.started` case, check if the node already exists in workflow state:

```typescript
case "node.started": {
  const p = payload<NodeStartedPayload>(event);
  // Idempotent: skip if node is already tracked and running
  const existingNode = stores.workflow.getState().nodes[p.node_id];
  if (existingNode && existingNode.status === "running") break;

  stores.workflow.getState().handleNodeStarted(p);
  // ... rest unchanged
```

**Step 2: Guard node.completed / node.failed against duplicate**

For `node.completed` and `node.failed`, the conversationStore handlers (`completeAgentMessage`, `failAgentMessage`) already search for a streaming message and return early if not found. This means replaying a `node.completed` when the message is already `completed` is a no-op. Verify this and confirm.

**Step 3: Commit**

```
fix: guard node.started against WS replay duplication
```

---

### Task 5: Add agent.text_delta dedup protection

**Files:**
- Modify: `frontend/src/contexts/workflow-context/routeEvent.ts:186-197`

**Context:** `agent.text_delta` appends text to a streaming message. On replay, this would cause duplicated text. However, `appendAgentText` in conversationStore uses `findLastIndex` to find a `streaming` message — after `node.completed` the message status changes to `completed`, so replayed deltas would be no-ops.

The real risk is during an active reconnect while a node is still streaming. This is a narrow edge case but worth guarding.

**Step 1: Add seq tracking to conversationStore messages**

This is a larger change. Instead, use a simpler approach: track processed seq range in a ref.

In `routeEvent.ts`, add a module-level processed event tracker:

```typescript
// At top of file, after imports
const _processedSeqs = new Set<number>();
const SEQ_PRUNE_SIZE = 500; // prune when set grows too large
```

**Step 2: Add seq check and recording in routeEvent**

Wrap the main `routeEvent` function to check and record seq:

```typescript
export function routeEvent(
  stores: WorkflowStores,
  event: WSEvent,
  ctx: RouteContext
): void {
  // Global dedup: skip events we've already processed
  const seq = event.seq;
  if (typeof seq === "number") {
    if (_processedSeqs.has(seq)) return;
    _processedSeqs.add(seq);
    // Prune to prevent unbounded growth
    if (_processedSeqs.size > SEQ_PRUNE_SIZE) {
      const entries = Array.from(_processedSeqs).sort((a, b) => a - b);
      const toKeep = entries.slice(-SEQ_PRUNE_SIZE / 2);
      _processedSeqs.clear();
      toKeep.forEach((s) => _processedSeqs.add(s));
    }
  }

  switch (event.type) {
    // ... existing cases unchanged
```

This is a **universal guard** — every event type benefits without individual handler changes. Combined with Task 1 (sinceSeq tracking), this provides defense-in-depth.

**Step 3: Reset _processedSeqs when workflow changes**

In the `workflow.started` case where `!sameWorkflow` triggers a reset, also clear the seq tracker:

```typescript
if (!sameWorkflow) {
  resetAllStores(stores);
  _processedSeqs.clear();
}
```

**Step 4: Run tests**

```bash
python -m pytest tests/ -x -q
cd frontend && npx next lint --quiet
```

**Step 5: Commit**

```
fix: universal WS event dedup via processed-seq tracking
```

---

### Task 6: Verify _processedSeqs is scoped per workflow

**Files:**
- Modify: `frontend/src/contexts/workflow-context/routeEvent.ts`

**Context:** The module-level `_processedSeqs` is shared across all workflow scopes. When switching workflows, old seqs from a previous workflow could collide (seq numbers restart). We need the set to be scoped.

**Step 1: Change _processedSeqs to be per-workflow**

Replace the module-level set with a Map keyed by workflowId:

```typescript
// Replace:
//   const _processedSeqs = new Set<number>();
// With:
const _processedSeqsByWorkflow = new Map<string, Set<number>>();
```

Update the guard in `routeEvent`:

```typescript
export function routeEvent(
  stores: WorkflowStores,
  event: WSEvent,
  ctx: RouteContext
): void {
  const seq = event.seq;
  if (typeof seq === "number" && ctx.workflowId) {
    let seqs = _processedSeqsByWorkflow.get(ctx.workflowId);
    if (!seqs) {
      seqs = new Set();
      _processedSeqsByWorkflow.set(ctx.workflowId, seqs);
    }
    if (seqs.has(seq)) return;
    seqs.add(seq);
    if (seqs.size > SEQ_PRUNE_SIZE) {
      const entries = Array.from(seqs).sort((a, b) => a - b);
      const toKeep = entries.slice(-SEQ_PRUNE_SIZE / 2);
      seqs.clear();
      toKeep.forEach((s) => seqs.add(s));
    }
  }
```

In the reset path:

```typescript
if (!sameWorkflow) {
  resetAllStores(stores);
  // Don't clear other workflows' seqs — just let them age out
}
```

**Step 2: Check RouteContext type**

Verify `ctx.workflowId` exists in the `RouteContext` type. If not, add it. The `routeEvent` function receives `ctx: RouteContext` — check what fields it has.

Read `routeEvent.ts` to find the `RouteContext` type definition and confirm `workflowId` is available (it should be, since it's used by the calling code).

**Step 3: Commit**

```
fix: scope WS event dedup per workflow to prevent seq collisions
```

---

### Task 7: End-to-end manual verification

**No files changed — just verification.**

**Step 1: Test ask_user reconnect scenario**

1. Start a workflow that triggers ask_user
2. Answer the question
3. Open DevTools → Network → kill the WS connection
4. Wait for reconnect (3s)
5. Verify: question card stays answered, no duplicate

**Step 2: Test page refresh scenario**

1. Start a workflow that triggers ask_user
2. Answer the question
3. Refresh the page
4. Verify: question shows as answered in the conversation history

**Step 3: Test workflow switching**

1. Start workflow A with ask_user → answer
2. Start workflow B (different workflow)
3. Switch back to workflow A via run history
4. Verify: no phantom questions appear

**Step 4: Test active streaming reconnect**

1. Start a long-running workflow
2. While text is streaming, temporarily block network
3. Unblock and let it reconnect
4. Verify: streaming text does not duplicate

---

## Summary

| Task | Layer | What | Files |
|------|-------|------|-------|
| 1 | Root cause | Track last seq for delta replay on reconnect | `useWebSocket.ts`, `useWorkflowWS.ts` |
| 2 | Defense-in-depth | chat.question idempotency guard | `routeEvent.ts` |
| 3 | Defense-in-depth | todo event dedup (verify existing) | `routeEvent.ts` |
| 4 | Defense-in-depth | node.started idempotency guard | `routeEvent.ts` |
| 5 | Universal | Processed-seq tracking for ALL events | `routeEvent.ts` |
| 6 | Correctness | Scope seq tracking per workflow | `routeEvent.ts` |
| 7 | Verification | Manual e2e testing | — |

**Tasks 1 + 5 together form the complete fix.** Task 1 prevents unnecessary replay; Task 5 catches any events that slip through. Tasks 2-4 are belt-and-suspenders guards on the most user-visible event types.
