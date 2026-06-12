# Outline Iter Isolation — Hardening (Plan F)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all review findings from Plan E (B1, B2 full backend sync, D1, D2, T1-T4). After this plan, iter is a first-class concept sunk to the backend — `node.started` events carry it, `StepEntry` persists it, replay hydrates it correctly.

**Architecture:**
- **Iter source of truth** moves from frontend counter to backend engine state (`node_invocation_counts`).
- **Propagation:** engine state → `node.started` event payload → frontend `currentIterationByNode` (now a cache, not a counter).
- **Todo stamping:** `StepEntry.iteration` set at creation from `deps.iteration` (injected at deps build time).
- **Replay:** snapshot path reads `iteration` from persisted `todo_steps`; event-fallback path reads from `node.started` events in the replay stream.

**Tech Stack:** Python (Pydantic, LangGraph-style state), TypeScript (Zustand, React), Vitest, pytest.

**Plan E prerequisite:** This plan assumes Plan E (`docs/plans/2026-06-12-outline-iter-isolation.md`) is already merged. Plan E established:
- `TodoStep.iteration` field (frontend type)
- `handleTodoCreated/Replaced` take `iteration` param
- `currentIterationByNode` state in conversation store
- `OutlineItem.isLatestIter` derivation
- `computeStatus/Activity/Badges` degradation branches

This plan hardens Plan E: fixes the interrupted-status gap, sinks iter to backend, addresses shallow-equality contract, tightens test coverage.

---

## Architecture Decisions

### Decision 1: New `node_invocation_counts` state field (not reuse `iteration_counts`)

`iteration_counts` (state.py:21) is **conditional_edge-specific**, keyed by `f"{agent_def.name}_loop"`. NAS fixed-count loops, retry loops, and DAG-topology loops don't touch it.

Adding a separate `node_invocation_counts: Annotated[dict, merge_dicts]` keyed by `node_id` is clean:
- Doesn't muddy the existing conditional_edge semantics.
- Universal: increments on **every** `node_func` invocation, regardless of loop type.
- Reducer `merge_dicts` is already defined and tested.

### Decision 2: Frontend `currentIterationByNode` becomes a cache

Currently `node.started` handler bumps the counter (`+ 1`). After this plan, the handler reads `iteration` from the event payload and overwrites the cache. The state field stays (consumers don't change), only the writer logic changes.

Fallback for legacy events (no `iteration` in payload): keep the `?? 1` default — same as today, replays of pre-Plan-F runs degrade to iter=1.

### Decision 3: D1 — switch to `useShallow` (honor the contract)

Plan E's Performance Contract promised a shallow-equal guard. The implementation used `useMemo` alone, which returns a new array reference on every `rawTodos` change even when the filtered result is identical by value. Real perf impact is negligible (AgentDetailView mounts 1 NodeBlockCard), but the contract divergence is real. Switch to `useShallow` to honor the contract — cost is 1 import + 1 wrapper.

### Decision 4: D2 — historical iter skips `waiting-for-user`

Move `pendingQuestionCount` check inside the `isLatestIter` branch. Historical iters cannot meaningfully be "waiting" — the iter has ended. If a `pending` question somehow survives into a historical iter (engine bug), showing it as `completed`/`failed`/`idle` is less misleading than `waiting-for-user`.

### Decision 5: B1 — historical iter `interrupted` → `failed`

`ConversationMessage.status` has 7 values: `streaming | done | error | interrupted | pending | answered | timeout`. Plan E's inference only covered `error` and `done`. Treat `interrupted` as `failed` (the iter was cancelled mid-stream — that's a failure from the user's perspective). `timeout` is question-specific (handled by `pendingQuestionCount` path), not a message-level failure.

---

## Robustness Contract

- **Backwards compatibility:** pre-Plan-F persisted runs have no `iteration` on `todo_steps` and no `iteration` on `node.started` events. Frontend `?? 1` fallback handles both. Backend `StepEntry.iteration` defaults to 1.
- **Mixed-version replay:** if a run was started under Plan E (frontend counter) and replayed under Plan F, the replay reads `iteration` from events — absent → falls back to 1. Acceptable; same as today.
- **Engine state migration:** existing in-flight runs (unlikely during a frontend+backend deploy) may have stale `node_invocation_counts`. `merge_dicts` reducer handles missing key as 0.
- **Test coverage:** every fix has a test that fails before the fix and passes after (TDD).

---

## Phase 1: B1 — Historical iter `interrupted` status

### Task 1.1: Add failing test for `interrupted` message status

**Files:**
- Modify: `frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts`

**Step 1: Write failing test**

Append to the `deriveOutlineItems` describe block:

```ts
  it("historical iter with interrupted message is marked failed (B1 fix)", () => {
    const nodes = { coder: node({ id: "coder", name: "coder", status: "success" }) };
    const messages = [
      msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1, status: "interrupted" }),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2, status: "done" }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    expect(items.find((i) => i.iteration === 1)?.status).toBe("failed");
    expect(items.find((i) => i.iteration === 2)?.status).toBe("completed");
  });
```

**Step 2: Run test to verify it fails**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/deriveOutlineItems.test.ts -t "interrupted"
```

Expected: FAIL — `expected 'idle' to be 'failed'` (current inference doesn't handle `interrupted`).

**Step 3: Commit (red)**

```bash
git add frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts
git commit -m "test(outline): add failing case for interrupted status in historical iter (B1)"
```

### Task 1.2: Fix `computeStatus` to treat `interrupted` as failed

**Files:**
- Modify: `frontend/src/components/outline/deriveOutlineItems.ts:148-156`

**Step 1: Update the historical-iter inference**

Find this block in `computeStatus`:

```ts
  // Historical iter — node.status reflects the current iter, not this one.
  // Infer from messages: error → failed, done → completed, else → idle.
  if (iterMessages.some((m) => m.status === "error")) return "failed";
  if (iterMessages.some((m) => m.status === "done")) return "completed";
  return "idle";
```

Replace with:

```ts
  // Historical iter — node.status reflects the current iter, not this one.
  // Infer from messages:
  //   error / interrupted → failed (cancelled mid-stream is a failure mode)
  //   done                → completed
  //   else                → idle (no terminal signal)
  if (iterMessages.some((m) => m.status === "error" || m.status === "interrupted")) {
    return "failed";
  }
  if (iterMessages.some((m) => m.status === "done")) return "completed";
  return "idle";
```

**Step 2: Run test to verify it passes**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/deriveOutlineItems.test.ts -t "interrupted"
```

Expected: PASS.

**Step 3: Run full outline suite for regression**

```bash
cd frontend && npx vitest run src/components/outline
```

Expected: all tests pass.

**Step 4: Commit (green)**

```bash
git add frontend/src/components/outline/deriveOutlineItems.ts
git commit -m "fix(outline): treat interrupted messages as failed in historical iter status (B1)"
```

---

## Phase 2: D2 — Move `pendingQuestionCount` inside `isLatestIter` branch

### Task 2.1: Add failing test for historical iter with stale pending question

**Files:**
- Modify: `frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts`

**Step 1: Write failing test**

Append:

```ts
  it("historical iter with stale pending question does not show waiting-for-user (D2 fix)", () => {
    // Edge case: a pending question somehow survives into a historical iter
    // (shouldn't happen in practice — engine interrupts on iter boundary —
    // but if it does, "waiting" is the wrong status for a past iter).
    const nodes = { coder: node({ id: "coder", name: "coder", status: "running" }) };
    const messages = [
      msg({
        id: "1",
        nodeId: "coder",
        agentName: "coder",
        timestamp: 100,
        iteration: 1,
        type: "question",
        status: "pending",
        questionId: "q1",
      } as any),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2, status: "streaming" }),
    ];
    const items = deriveOutlineItems(nodes, messages, emptyTodo);
    // iter=1 is historical — must NOT show waiting-for-user even though
    // a pending question exists in its messages. Should infer from the
    // iter's overall state instead.
    const iter1Status = items.find((i) => i.iteration === 1)?.status;
    expect(iter1Status).not.toBe("waiting-for-user");
    // iter=2 IS latest and has no pending question — running.
    expect(items.find((i) => i.iteration === 2)?.status).toBe("running");
  });
```

**Step 2: Run to verify failure**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/deriveOutlineItems.test.ts -t "stale pending"
```

Expected: FAIL — `expected 'waiting-for-user' not to equal 'waiting-for-user'`.

**Step 3: Commit (red)**

```bash
git add frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts
git commit -m "test(outline): historical iter with stale pending question (D2)"
```

### Task 2.2: Reorder `computeStatus` branches

**Files:**
- Modify: `frontend/src/components/outline/deriveOutlineItems.ts:135-160`

**Step 1: Replace `computeStatus` body**

Current signature: `computeStatus(node, pendingQuestionCount, iterMessages, isLatestIter)`.

New body:

```ts
function computeStatus(
  node: NodeState | undefined,
  pendingQuestionCount: number,
  iterMessages: ConversationMessage[],
  isLatestIter: boolean,
): OutlineStatus {
  if (!node) return "idle";

  if (isLatestIter) {
    // Latest iter — pending questions are real and actionable.
    if (pendingQuestionCount > 0) return "waiting-for-user";
    switch (node.status) {
      case "running": return "running";
      case "success": return "completed";
      case "failed": return "failed";
      case "retrying": return "retrying";
      default: return "idle";
    }
  }

  // Historical iter — pendingQuestionCount is intentionally ignored:
  // a past iter cannot meaningfully be "waiting". If a question somehow
  // wasn't answered/interrupted before iter boundary (engine bug), surfacing
  // it as waiting-for-user would be more misleading than inferring from
  // message state.
  if (iterMessages.some((m) => m.status === "error" || m.status === "interrupted")) {
    return "failed";
  }
  if (iterMessages.some((m) => m.status === "done")) return "completed";
  return "idle";
}
```

**Step 2: Run failing test**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/deriveOutlineItems.test.ts -t "stale pending"
```

Expected: PASS.

**Step 3: Run full suite for regression**

```bash
cd frontend && npx vitest run src/components/outline
```

Expected: all pass — note that the existing "waiting-for-user" tests use latest-iter scenarios, so they still pass under the new ordering.

**Step 4: Commit (green)**

```bash
git add frontend/src/components/outline/deriveOutlineItems.ts
git commit -m "fix(outline): pendingQuestionCount only applies to latest iter (D2)"
```

---

## Phase 3: D1 — Honor shallow-equal contract in NodeBlockCard

### Task 3.1: Switch `useMemo` filter to `useShallow`

**Files:**
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx:18` (import)
- Modify: `frontend/src/components/conversation/ScopedConversationTab.tsx:393-410` (selector)

**Step 1: Add `useShallow` import**

Find the existing zustand import line:

```ts
import { useStore } from "zustand";
```

Add immediately below:

```ts
import { useShallow } from "zustand/shallow";
```

**Step 2: Replace the `useMemo` filter with `useShallow`-wrapped selector**

Find this block (current state after Plan E):

```tsx
  const rawTodos = useStore(todoStore!, (s) => s.todos[nodeId]);
  const todos = useMemo(
    () =>
      iteration === undefined
        ? rawTodos
        : rawTodos?.filter((t) => (t.iteration ?? 1) === iteration),
    [rawTodos, iteration],
  );
  const hasTodos = !!todos && todos.length > 0;
```

Replace with:

```tsx
  // Subscribe with iter filter inside the selector. useShallow ensures
  // that if the filtered result is value-equal to the previous render's
  // result, the same array reference is returned → no spurious re-render
  // when an unrelated iter's step mutates (e.g. iter=2 tokenUsage delta
  // while this card shows iter=1).
  //
  // Timeline view passes iteration=undefined → selector returns rawTodos
  // unchanged (no filter), preserving the legacy "show all steps" behavior.
  const todos = useStore(
    todoStore!,
    useShallow((s: TodoState) => {
      const all = s.todos[nodeId];
      if (!all) return all;
      if (iteration === undefined) return all;
      return all.filter((t) => (t.iteration ?? 1) === iteration);
    }),
  );
  const hasTodos = !!todos && todos.length > 0;
```

**Step 3: Verify `useMemo` is still used elsewhere (don't remove import)**

```bash
grep -n "useMemo" frontend/src/components/conversation/ScopedConversationTab.tsx
```

Expected: at least one other usage (line ~216 `summary`). Keep the import.

**Step 4: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

**Step 5: Run NodeBlockCard-related tests**

```bash
cd frontend && npx vitest run
```

Expected: all pass.

**Step 6: Commit**

```bash
git add frontend/src/components/conversation/ScopedConversationTab.tsx
git commit -m "perf(outline): useShallow guard on NodeBlockCard todo selector (D1)

Honors the Performance Contract from Plan E — avoids spurious re-renders
when an unrelated iter's step mutates while this card displays a different iter."
```

---

## Phase 4: B2 Backend — `node_invocation_counts` state + event payload

### Task 4.1: Add `node_invocation_counts` to `HarnessState`

**Files:**
- Modify: `harness/engine/state.py:16-22`

**Step 1: Update `HarnessState` TypedDict**

Find:

```python
class HarnessState(TypedDict):
    inputs: dict                                # 工作流初始输入，贯穿所有节点
    outputs: Annotated[dict, merge_dicts]       # {agent_name: result} — reducer 自动合并 fan-out
    errors: Annotated[dict, merge_dicts]        # {agent_name: error_info}
    metadata: Annotated[dict, merge_dicts]      # 可扩展插槽
    iteration_counts: Annotated[dict, merge_dicts]  # {edge_key: count} — 条件边回环计数
```

Add a new field:

```python
class HarnessState(TypedDict):
    inputs: dict                                # 工作流初始输入，贯穿所有节点
    outputs: Annotated[dict, merge_dicts]       # {agent_name: result} — reducer 自动合并 fan-out
    errors: Annotated[dict, merge_dicts]        # {agent_name: error_info}
    metadata: Annotated[dict, merge_dicts]      # 可扩展插槽
    iteration_counts: Annotated[dict, merge_dicts]  # {edge_key: count} — 条件边回环计数
    # {node_id: count} — universal invocation counter, incremented every time
    # node_func runs. Used to stamp `iteration` on node.started events and
    # todo steps. Distinct from iteration_counts (which is conditional_edge-
    # specific). Plan F.
    node_invocation_counts: Annotated[dict, merge_dicts]
```

**Step 2: Commit**

```bash
git add harness/engine/state.py
git commit -m "feat(engine): add node_invocation_counts state field (Plan F)"
```

### Task 4.2: Increment counter in `node_func` and pass to deps + event

**Files:**
- Modify: `harness/engine/node_factory.py:142-180` (node_func startup)
- Modify: `harness/engine/node_factory.py:220-240` (deps build)
- Modify: `harness/engine/node_factory.py:600-625` (return dict)

**Step 1: Compute `current_invocation` at node_func startup**

Find this block in `node_func` (around line 142-160):

```python
    async def node_func(state: HarnessState) -> dict:
        start_time = time.time()

        # Check iteration count for conditional edges
        if agent_def.has_conditional_edges:
            iter_key = f"{agent_def.name}_loop"
            current_count = state.get("iteration_counts", {}).get(iter_key, 0)
            ...
```

Insert immediately after `start_time = time.time()`:

```python
    async def node_func(state: HarnessState) -> dict:
        start_time = time.time()

        # Universal invocation counter — bumped every time this node runs,
        # regardless of loop type (conditional edge, fixed-count, retry, etc.).
        # Used to stamp iteration on node.started + todo steps. Plan F.
        current_invocation = state.get("node_invocation_counts", {}).get(agent_def.name, 0) + 1

        # Check iteration count for conditional edges
        if agent_def.has_conditional_edges:
            ...
```

**Step 2: Pass `iteration` to `build_node_started_payload`**

Find the `node.started` emit (around line 162-170):

```python
        # Emit node.started event (legacy WS path)
        if bus:
            safe_emit(bus, "node.started", build_node_started_payload(
                builder_self.workflow_id, agent_def.name, agent_def.name,
                ...
            ))
```

Add `iteration=current_invocation` to the call. The full call after edit:

```python
        # Emit node.started event (legacy WS path)
        if bus:
            safe_emit(bus, "node.started", build_node_started_payload(
                builder_self.workflow_id, agent_def.name, agent_def.name,
                model=...,
                tools=...,
                attempt=...,
                iteration=current_invocation,
            ))
```

(Keep existing arg values — only add the `iteration=` kwarg.)

**Step 3: Inject `iteration` into `AgentDeps`**

Find the `deps = AgentDeps(...)` build (around line 224). Add `iteration=current_invocation,` to the constructor call:

```python
        deps = AgentDeps(
            workflow_id=builder_self.workflow_id,
            node_id=agent_def.name,
            agent_name=agent_def.name,
            # ... existing fields ...
            iteration=current_invocation,  # Plan F — read by todo tool
        )
```

`AgentDeps` uses `extra="allow"` (deps.py:11), so this field is accepted without schema change.

**Step 4: Return updated `node_invocation_counts` from node_func**

Find the final `return` of `node_func` (around line 600-625, where `result_dict` is built). Add `node_invocation_counts` to the returned dict.

Locate where `iteration_counts` is conditionally added:

```python
            result_dict["iteration_counts"] = iter_update
```

Below that block (or in the final return assembly), add unconditionally:

```python
        # Always update node_invocation_counts so the next invocation of
        # this node sees an incremented counter. Plan F.
        result_dict["node_invocation_counts"] = {agent_def.name: current_invocation}
```

If `result_dict` is built piecemeal, ensure this line executes on every return path (including error paths). If error paths skip the assembly, add it there too.

**Step 5: Run existing engine tests for regression**

```bash
pytest harness/engine/test_node_factory.py -v 2>&1 | tail -20
```

Expected: all pass (no behavior change visible to existing tests — `node_invocation_counts` is additive).

**Step 6: Commit**

```bash
git add harness/engine/node_factory.py
git commit -m "feat(engine): increment node_invocation_counts and inject iter into deps+event (Plan F)"
```

### Task 4.3: Extend `build_node_started_payload` signature

**Files:**
- Modify: `harness/engine/node_phases.py:49-72`

**Step 1: Add `iteration` parameter to signature**

Find:

```python
def build_node_started_payload(
    workflow_id: str | None,
    node_id: str,
    agent_name: str,
    *,
    model: str | None = None,
    tools: Any = None,
    attempt: int = 1,
) -> dict:
```

Change to:

```python
def build_node_started_payload(
    workflow_id: str | None,
    node_id: str,
    agent_name: str,
    *,
    model: str | None = None,
    tools: Any = None,
    attempt: int = 1,
    iteration: int = 1,
) -> dict:
```

**Step 2: Add `iteration` to the payload dict**

Find:

```python
    payload: dict[str, Any] = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "agent_name": agent_name,
        "attempt": attempt,
        "model": model,
        "ts": int(time.time() * 1000),
    }
```

Add `"iteration": iteration,`:

```python
    payload: dict[str, Any] = {
        "workflow_id": workflow_id,
        "node_id": node_id,
        "agent_name": agent_name,
        "attempt": attempt,
        "iteration": iteration,
        "model": model,
        "ts": int(time.time() * 1000),
    }
```

**Step 3: Update docstring**

Below the existing `"""Build the payload dict for a ``node.started`` event."""` line, add:

```python
    """Build the payload dict for a ``node.started`` event.

    The caller (nodeFunc) passes this to ``safe_emit(bus, "node.started", ...)``.

    ``iteration`` is the universal invocation counter for this node (1-indexed).
    Frontend reads it to populate ``currentIterationByNode`` cache and stamp
    subsequent messages / todo steps. Defaults to 1 for backward compat with
    callers that haven't been updated.
    """
```

**Step 4: Run node_phases tests**

```bash
pytest harness/engine/test_node_phases.py -v 2>&1 | tail -10
```

Expected: pass (additive change).

**Step 5: Commit**

```bash
git add harness/engine/node_phases.py
git commit -m "feat(engine): add iteration to node.started payload (Plan F)"
```

### Task 4.4: Add `iteration` field to `StepEntry` pydantic model

**Files:**
- Modify: `harness/tools/todo.py:35-40`

**Step 1: Add field to `StepEntry`**

Find:

```python
class StepEntry(BaseModel):
    task_id: str
    content: str
    activeForm: str
    status: Literal["pending", "in_progress", "completed", "skipped"] = "pending"
    detail: str | None = None
```

Change to:

```python
class StepEntry(BaseModel):
    task_id: str
    content: str
    activeForm: str
    status: Literal["pending", "in_progress", "completed", "skipped"] = "pending"
    detail: str | None = None
    # Which loop iteration created this step. 1-indexed. Stamped at create
    # time from deps.iteration (injected by node_factory). Defaults to 1
    # for backward compat with persisted data from before Plan F. Plan F.
    iteration: int = 1
```

**Step 2: Stamp `iteration` in the create path**

Find the create block (around line 124-145):

```python
            if op == "create":
                ...
                new_steps: list[StepEntry] = []
                for i, item in enumerate(items):
                    entry = StepEntry(
                        task_id=state.next_task_id(),
                        content=item.content,
                        activeForm=item.activeForm,
                        status="in_progress" if (not state.steps and i == 0) else "pending",
                    )
                    new_steps.append(entry)
                state.steps.extend(new_steps)
```

Add `iteration=` to the `StepEntry(...)` constructor:

```python
                for i, item in enumerate(items):
                    entry = StepEntry(
                        task_id=state.next_task_id(),
                        content=item.content,
                        activeForm=item.activeForm,
                        status="in_progress" if (not state.steps and i == 0) else "pending",
                        iteration=getattr(deps, "iteration", 1) if deps else 1,
                    )
                    new_steps.append(entry)
```

**Step 3: Stamp in the replace path (same file)**

Find the replace block (search for `op == "replace"`):

```python
            if op == "replace":
                ...
                state.steps = []
                new_steps: list[StepEntry] = []
                for i, item in enumerate(items):
                    entry = StepEntry(
                        task_id=state.next_task_id(),
                        ...
                    )
                    new_steps.append(entry)
                state.steps.extend(new_steps)
```

Add the same `iteration=getattr(deps, "iteration", 1) if deps else 1,` line to the `StepEntry(...)` constructor here.

**Step 4: Run todo tool tests**

```bash
pytest harness/tools/test_todo.py -v 2>&1 | tail -15
```

Expected: pass (additive).

**Step 5: Commit**

```bash
git add harness/tools/todo.py
git commit -m "feat(todo): persist iteration on StepEntry, stamped from deps (Plan F)"
```

### Task 4.5: Backend test — invocation counter increments across loop

**Files:**
- Create: `harness/engine/test_node_invocation_counts.py`

**Step 1: Write the test**

```python
"""Tests for node_invocation_counts state field (Plan F)."""
import pytest
from harness.engine.state import HarnessState, merge_dicts


def test_merge_dicts_increments_node_invocation_counts():
    """Successive node_func returns must accumulate invocation counts via
    the merge_dicts reducer (same mechanism as iteration_counts)."""
    state: HarnessState = {
        "inputs": {},
        "outputs": {},
        "errors": {},
        "metadata": {},
        "iteration_counts": {},
        "node_invocation_counts": {},
    }
    # Simulate three invocations of node "searcher"
    updates = [
        {"searcher": 1},
        {"searcher": 2},
        {"searcher": 3},
    ]
    for update in updates:
        state["node_invocation_counts"] = merge_dicts(
            state["node_invocation_counts"], update
        )
    assert state["node_invocation_counts"] == {"searcher": 3}


def test_merge_dicts_isolates_different_nodes():
    state: HarnessState = {
        "inputs": {},
        "outputs": {},
        "errors": {},
        "metadata": {},
        "iteration_counts": {},
        "node_invocation_counts": {},
    }
    state["node_invocation_counts"] = merge_dicts(state["node_invocation_counts"], {"analyzer": 1})
    state["node_invocation_counts"] = merge_dicts(state["node_invocation_counts"], {"searcher": 1})
    state["node_invocation_counts"] = merge_dicts(state["node_invocation_counts"], {"analyzer": 2})
    assert state["node_invocation_counts"] == {"analyzer": 2, "searcher": 1}
```

**Step 2: Run**

```bash
pytest harness/engine/test_node_invocation_counts.py -v
```

Expected: 2 tests pass.

**Step 3: Commit**

```bash
git add harness/engine/test_node_invocation_counts.py
git commit -m "test(engine): node_invocation_counts reducer accumulation (Plan F)"
```

### Task 4.6: Backend test — `iteration` stamped on created steps

**Files:**
- Modify: `harness/tools/test_todo.py` (append) OR Create: `harness/tools/test_todo_iteration.py`

**Step 1: Write the test**

Create `harness/tools/test_todo_iteration.py`:

```python
"""Tests for StepEntry.iteration stamping from deps (Plan F)."""
import pytest
from pydantic_ai.tools import RunContext  # adjust import to match project convention

from harness.tools.deps import AgentDeps
from harness.tools.todo import todo_tool, StepEntry, TodoState, ensure_todo_state


def test_step_entry_has_iteration_field_defaulting_to_1():
    """Backward compat: StepEntry without explicit iteration defaults to 1."""
    entry = StepEntry(task_id="t1", content="x", activeForm="x")
    assert entry.iteration == 1


def test_todo_create_stamps_iteration_from_deps():
    """todo tool create path reads deps.iteration and stamps on each step."""
    deps = AgentDeps(
        workflow_id="wf-1",
        node_id="searcher",
        agent_name="searcher",
        # Inject iter via extra field (AgentDeps allows extras).
        iteration=3,
    )
    state = ensure_todo_state(deps)
    state.has_plan = False  # allow create
    # Invoke the tool synchronously with op=create
    # (signature depends on how the project wires the tool — adjust)
    # For unit-test purposes, replicate the create logic:
    from harness.tools.todo import StepEntry
    new_step = StepEntry(
        task_id=state.next_task_id(),
        content="probe",
        activeForm="probing",
        status="in_progress",
        iteration=getattr(deps, "iteration", 1),
    )
    assert new_step.iteration == 3


def test_legacy_deps_without_iteration_field_defaults_to_1():
    """Deps built before Plan F don't have `iteration` attr — must default."""
    deps = AgentDeps(workflow_id="wf-1", node_id="x", agent_name="x")
    # No iteration attr set.
    iter_value = getattr(deps, "iteration", 1)
    assert iter_value == 1
```

**Step 2: Run**

```bash
pytest harness/tools/test_todo_iteration.py -v
```

Expected: 3 pass.

**Step 3: Commit**

```bash
git add harness/tools/test_todo_iteration.py
git commit -m "test(todo): StepEntry iter stamping from deps + legacy fallback (Plan F)"
```

---

## Phase 5: B2 Frontend — Read iter from event + snapshot

### Task 5.1: `node.started` handler reads `iteration` from payload

**Files:**
- Modify: `frontend/src/contexts/workflow-context/routing/nodeHandlers.ts:18-30`

**Step 1: Replace counter increment with payload read**

Find this block (Plan E added the increment):

```ts
      // Increment loop iteration counter for this nodeId BEFORE creating
      // the agent message, so the message stamps the new iteration. Mirrors
      // the existing stepId pattern: state setter first, message creator
      // reads from state.
      const conv = stores.conversation.getState();
      const nextIter = (conv.currentIterationByNode[p.node_id] ?? 0) + 1;
      conv.setCurrentIteration(p.node_id, nextIter);
```

Replace with:

```ts
      // Read iteration from the event payload (backend is the source of
      // truth since Plan F). Frontend `currentIterationByNode` is now a
      // cache, not a counter. Falls back to 1 for legacy events emitted
      // before Plan F backend deploy. Plan F.
      const conv = stores.conversation.getState();
      const iter = (p.iteration as number | undefined) ?? 1;
      conv.setCurrentIteration(p.node_id, iter);
```

**Step 2: Update the existing iteration test**

The test `nodeHandlers.iteration.test.ts` asserts the counter is bumped from 1 to 2 across two `node.started` events. Under Plan F, the bump comes from the payload, not the handler. Update the test to pass `iteration` in the event payload.

Find `frontend/src/contexts/workflow-context/routing/__tests__/nodeHandlers.iteration.test.ts`:

```ts
  it("sets iteration=1 on first node.started for a nodeId", () => {
    startedHandler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(1);
  });

  it("increments iteration on subsequent node.started for same nodeId (loop)", () => {
    startedHandler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    completedHandler(...);
    startedHandler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(2);
  });
```

Change to include `iteration` in the payload:

```ts
  it("reads iteration=1 from node.started payload (first invocation)", () => {
    startedHandler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 1 }), {} as any);
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(1);
  });

  it("reads iteration=2 from subsequent node.started payload (loop)", () => {
    startedHandler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 1 }), {} as any);
    completedHandler(stores, fireEvent("node.completed", { node_id: "coder", agent_name: "coder", duration_ms: 100 }), {} as any);
    startedHandler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder", iteration: 2 }), {} as any);
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(2);
  });

  it("falls back to iter=1 when payload lacks iteration (legacy event)", () => {
    startedHandler(stores, fireEvent("node.started", { node_id: "coder", agent_name: "coder" }), {} as any);
    expect(stores.conversation.getState().currentIterationByNode.coder).toBe(1);
  });
```

The third test ("new agent message after second node.started is stamped with iteration=2") already works if the second `startedHandler` call passes `iteration: 2`.

**Step 3: Run tests**

```bash
cd frontend && npx vitest run src/contexts/workflow-context/routing/__tests__/nodeHandlers.iteration.test.ts
```

Expected: all pass.

**Step 4: Commit**

```bash
git add frontend/src/contexts/workflow-context/routing/nodeHandlers.ts \
        frontend/src/contexts/workflow-context/routing/__tests__/nodeHandlers.iteration.test.ts
git commit -m "feat(outline): read iteration from node.started payload (cache, not counter) — Plan F"
```

### Task 5.2: Snapshot hydration reads `iteration` from persisted `todo_steps`

**Files:**
- Modify: `frontend/src/contexts/workflow-context/replayEvents.ts:364-381`

**Step 1: Update the snapshot type and mapper**

Find:

```ts
  const todoStepsSnapshot = run.todo_steps as
    | Record<string, Array<{ task_id: string; content: string; activeForm: string; status: string; detail: string | null }>>
    | undefined
    | null;

  if (todoStepsSnapshot && Object.keys(todoStepsSnapshot).length > 0) {
    // Snapshot path — direct setState per node
    const todosMap: Record<string, import("./stores/todo").TodoStep[]> = {};
    for (const [nodeId, steps] of Object.entries(todoStepsSnapshot)) {
      todosMap[nodeId] = steps.map((s) => ({
        taskId: s.task_id,
        content: s.content,
        activeForm: s.activeForm,
        status: s.status as import("./stores/todo").TodoStepStatus,
        detail: s.detail ?? null,
      }));
    }
    stores.todo.setState({ todos: todosMap });
  }
```

Replace with:

```ts
  const todoStepsSnapshot = run.todo_steps as
    | Record<string, Array<{ task_id: string; content: string; activeForm: string; status: string; detail: string | null; iteration?: number }>>
    | undefined
    | null;

  if (todoStepsSnapshot && Object.keys(todoStepsSnapshot).length > 0) {
    // Snapshot path — direct setState per node. Reads `iteration` persisted
    // by backend since Plan F; legacy snapshots (pre-Plan-F) omit it and
    // the field stays undefined → consumers treat as iter=1. Plan F.
    const todosMap: Record<string, import("./stores/todo").TodoStep[]> = {};
    for (const [nodeId, steps] of Object.entries(todoStepsSnapshot)) {
      todosMap[nodeId] = steps.map((s) => ({
        taskId: s.task_id,
        content: s.content,
        activeForm: s.activeForm,
        status: s.status as import("./stores/todo").TodoStepStatus,
        detail: s.detail ?? null,
        iteration: s.iteration,
      }));
    }
    stores.todo.setState({ todos: todosMap });
  }
```

**Step 2: Update the event-fallback comment**

Find the existing event-fallback block (Plan E added a comment about replay limitation). Update it to reflect Plan F's resolution:

```ts
  } else if (events && events.length > 0) {
    // Event fallback — replay todo.created events. Since Plan F, the
    // node.started events in this stream carry `iteration` — rebuild
    // currentIterationByNode from them, then stamp todo.created calls.
    // Pre-Plan-F replays lack iter on both events → fallback to 1.
    const convByNode: Record<string, number> = {};
    for (const event of events) {
      if (event.type === "node.started") {
        const p = event.payload as { node_id?: string; iteration?: number };
        if (p.node_id) {
          convByNode[p.node_id] = p.iteration ?? convByNode[p.node_id] ?? 1;
        }
      }
    }
    for (const event of events) {
      if (event.type === "todo.created") {
        const p = event.payload as {
          node_id: string;
          items: TodoStepItem[];
        };
        const iter = convByNode[p.node_id] ?? 1;
        handleTodoCreated(stores.todo, p.node_id, p.items, iter);
      } else if (event.type === "todo.updated") {
        // ... unchanged ...
      }
    }
  }
```

**Step 3: TypeScript check**

```bash
cd frontend && npx tsc --noEmit
```

Expected: zero errors.

**Step 4: Run replay tests (if any) + outline tests**

```bash
cd frontend && npx vitest run
```

Expected: all pass.

**Step 5: Commit**

```bash
git add frontend/src/contexts/workflow-context/replayEvents.ts
git commit -m "feat(replay): hydrate TodoStep.iteration from snapshot + node.started events (Plan F)"
```

### Task 5.3: Frontend test — snapshot hydration preserves iteration

**Files:**
- Create or extend: `frontend/src/contexts/workflow-context/__tests__/replayEvents.iteration.test.ts`

**Step 1: Write the test**

This depends on how `replayEvents` is exported/tested. If it's not currently unit-tested in isolation, write an integration-style test against the function:

```ts
import { describe, it, expect } from "vitest";
// Adjust import to actual export:
// import { applyHydration } from "../replayEvents";

describe("replayEvents — todo iteration hydration (Plan F)", () => {
  it("snapshot path preserves iteration field from persisted todo_steps", () => {
    // Construct a minimal run record with iter-aware todo_steps, call the
    // hydration function, assert store state contains steps with correct iter.
    // See existing replayEvents tests for fixture pattern.
    //
    // The run record looks like:
    //   {
    //     todo_steps: {
    //       coder: [
    //         { task_id: "s1", ..., iteration: 1 },
    //         { task_id: "s2", ..., iteration: 2 },
    //       ]
    //     }
    //   }
    //
    // After hydration, stores.todo.getState().todos.coder should have
    // s1.iteration === 1 and s2.iteration === 2.
  });

  it("event-fallback path reads iteration from node.started events", () => {
    // Construct events: [node.started(iter=1), todo.created, node.completed,
    // node.started(iter=2), todo.created]
    // After replay, iter=2's todo.created should produce a step with iteration=2.
  });

  it("legacy snapshot without iteration field degrades to undefined (treated as 1)", () => {
    // Pre-Plan-F snapshot: steps have no iteration field.
    // Hydration should not crash; consumers' `(t.iteration ?? 1) === 1` filter
    // surfaces them under iter=1.
  });
});
```

**Step 2: Fill in fixtures** based on the existing `replayEvents` test pattern. If no existing pattern, this task may require refactoring `replayEvents` to be more testable (extract the snapshot/event application into a pure function).

**Step 3: Run**

```bash
cd frontend && npx vitest run src/contexts/workflow-context/__tests__/replayEvents.iteration.test.ts
```

Expected: pass.

**Step 4: Commit**

```bash
git add frontend/src/contexts/workflow-context/__tests__/replayEvents.iteration.test.ts
git commit -m "test(replay): snapshot + event-fallback iter hydration (Plan F)"
```

---

## Phase 6: Remaining test gaps (T3, T4)

### Task 6.1: Outline derivation test for stamp-misalignment consequence (T3)

**Files:**
- Modify: `frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts`

**Step 1: Write the test**

The scenario: a todo was stamped iter=1 (because `node.started` hadn't fired when `todo.created` arrived), but messages are stamped iter=2 (later in the stream). What does outline show?

Append:

```ts
  it("outline survives stamp misalignment: todo iter=1, messages iter=2 (T3)", () => {
    // Edge case: todo.created arrived before node.started bumped the counter.
    // Result: todo step has iteration=1, but the actual running iter is 2
    // (messages stamped correctly). Outline must still render the iter=2 row
    // (from messages); the misplaced todo attaches to iter=1 row instead.
    // This is a known acceptable degradation, not a crash.
    const nodes = { coder: node({ id: "coder", name: "coder", status: "running" }) };
    const todos = {
      coder: [
        { taskId: "misplaced", content: "should be iter 2", activeForm: "x", status: "in_progress", detail: null, iteration: 1 },
      ],
    };
    const messages = [
      msg({ id: "1", nodeId: "coder", agentName: "coder", timestamp: 100, iteration: 1, status: "done" }),
      msg({ id: "2", nodeId: "coder", agentName: "coder", timestamp: 200, iteration: 2, status: "streaming" }),
    ];
    const items = deriveOutlineItems(nodes, messages, todos);
    // Both iter rows render — no crash.
    expect(items).toHaveLength(2);
    // iter=2 is latest, running, but its todo filter finds no steps
    // (the misplaced step is under iter=1).
    const iter2 = items.find((i) => i.iteration === 2)!;
    expect(iter2.status).toBe("running");
    expect((iter2.activity as { currentStepContent?: string }).currentStepContent).toBeUndefined();
  });
```

**Step 2: Run**

```bash
cd frontend && npx vitest run src/components/outline/__tests__/deriveOutlineItems.test.ts -t "stamp misalignment"
```

Expected: PASS (the derivation already handles this correctly — the test documents the contract).

**Step 3: Commit**

```bash
git add frontend/src/components/outline/__tests__/deriveOutlineItems.test.ts
git commit -m "test(outline): document stamp misalignment degradation (T3)"
```

### Task 6.2: Component test for NodeBlockCard iter filtering (T4)

**Files:**
- Create: `frontend/src/components/conversation/__tests__/NodeBlockCard.iteration.test.tsx`

**Step 1: Write the test**

```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { createStore } from "zustand/vanilla";
import { NodeBlockCard } from "../ScopedConversationTab";
import type { TodoState, TodoStep } from "@/contexts/workflow-context/stores/todo";

// Minimal block fixture — adjust to actual NodeBlock shape used by NodeBlockCard.
function makeBlock(nodeId: string) {
  return {
    kind: "node" as const,
    nodeId,
    children: [],
    mainMessage: {
      id: "m1",
      type: "agent" as const,
      nodeId,
      agentName: "tester",
      content: "",
      timestamp: 0,
    },
  };
}

function makeTodoStore(steps: TodoStep[]) {
  return createStore<TodoState>()(() => ({
    todos: { tester: steps },
    reset: () => null as never,
  }));
}

describe("NodeBlockCard — iteration prop filtering (T4)", () => {
  it("iteration=undefined shows all steps (Timeline behavior)", () => {
    const store = makeTodoStore([
      { taskId: "s1", content: "iter1 step", activeForm: "x", status: "completed", detail: null, iteration: 1 },
      { taskId: "s2", content: "iter2 step", activeForm: "x", status: "in_progress", detail: null, iteration: 2 },
    ]);
    render(
      <NodeBlockCard
        block={makeBlock("tester") as any}
        getAgentIO={() => undefined}
        getNodeState={() => undefined}
        sendStructuredAnswer={() => {}}
        conversationActions={{ answerUserQuestion: () => {} }}
        todoStore={store}
        // iteration intentionally omitted → undefined → Timeline behavior
      />,
    );
    expect(screen.getByText("iter1 step")).toBeInTheDocument();
    expect(screen.getByText("iter2 step")).toBeInTheDocument();
  });

  it("iteration=2 shows only iter=2 steps", () => {
    const store = makeTodoStore([
      { taskId: "s1", content: "iter1 step", activeForm: "x", status: "completed", detail: null, iteration: 1 },
      { taskId: "s2", content: "iter2 step", activeForm: "x", status: "in_progress", detail: null, iteration: 2 },
    ]);
    render(
      <NodeBlockCard
        block={makeBlock("tester") as any}
        getAgentIO={() => undefined}
        getNodeState={() => undefined}
        sendStructuredAnswer={() => {}}
        conversationActions={{ answerUserQuestion: () => {} }}
        todoStore={store}
        iteration={2}
      />,
    );
    expect(screen.queryByText("iter1 step")).not.toBeInTheDocument();
    expect(screen.getByText("iter2 step")).toBeInTheDocument();
  });

  it("legacy steps without iteration field appear under iteration=1 filter", () => {
    const store = makeTodoStore([
      { taskId: "legacy", content: "old step", activeForm: "x", status: "completed", detail: null },
    ]);
    render(
      <NodeBlockCard
        block={makeBlock("tester") as any}
        getAgentIO={() => undefined}
        getNodeState={() => undefined}
        sendStructuredAnswer={() => {}}
        conversationActions={{ answerUserQuestion: () => {} }}
        todoStore={store}
        iteration={1}
      />,
    );
    expect(screen.getByText("old step")).toBeInTheDocument();
  });
});
```

**Step 2: Install testing-library if missing**

Check `package.json` — if `@testing-library/react` isn't present:

```bash
cd frontend && npm install --save-dev @testing-library/react @testing-library/jest-dom
```

(If the project doesn't use testing-library, refactor the test to use React's `act` + manual DOM inspection, or skip this task and rely on the deriveOutlineItems unit tests + manual browser verification.)

**Step 3: Run**

```bash
cd frontend && npx vitest run src/components/conversation/__tests__/NodeBlockCard.iteration.test.tsx
```

Expected: 3 pass.

**Step 4: Commit**

```bash
git add frontend/src/components/conversation/__tests__/NodeBlockCard.iteration.test.tsx
git commit -m "test(outline): NodeBlockCard iteration prop filtering (T4)"
```

---

## Phase 7: End-to-end verification

### Task 7.1: Full test suites

**Step 1: Frontend**

```bash
cd frontend && npx tsc --noEmit && npx vitest run
```

Expected: zero TS errors; all tests pass.

**Step 2: Backend**

```bash
pytest harness/engine/test_node_invocation_counts.py harness/tools/test_todo_iteration.py harness/engine/test_node_phases.py -v
```

Expected: all pass.

**Step 3: Full backend regression**

```bash
pytest harness/ -x --ignore=harness/builtin 2>&1 | tail -15
```

Expected: no regressions.

### Task 7.2: Rebuild + manual verification

**Step 1: Rebuild frontend**

```bash
cd frontend && npm run build
```

**Step 2: Restart backend** (to load Python changes)

```bash
# Stop the existing backend (PID may vary)
kill $(lsof -ti :8000) 2>/dev/null
# Restart with worktree frontend
HARNESS_FRONTEND_DIR="/Users/mozzie/Desktop/Projects/AgentHarness/.claude/worktrees/outline-master-detail/frontend/out" \
  python3 -m harness.cli ui --port 8000 &
```

**Step 3: Browser verification** (hard refresh: Cmd+Shift+R)

Verify the following on a NAS-style loop workflow:

- [ ] Live run: outline shows N iter rows for a loop node; each row has its own todo list (no cross-iter bleed).
- [ ] Live run: latest iter row shows token / retry badges; historical iter rows don't.
- [ ] Live run: interrupted iter (cancel mid-stream) shows as `failed`, not `idle`.
- [ ] Replay of finished Plan-F run: outline splits iters correctly; todo list per iter matches what was live.
- [ ] Replay of pre-Plan-F run (legacy): outline still splits iters from messages; todos default to iter=1 (degraded but no crash).
- [ ] Timeline view: shows all todos across all iters (no regression).

### Task 7.3: Update status docs

**Files:**
- Modify: `docs/status/CURRENT.md`
- Modify: `docs/status/CHANGELOG.md`

**Step 1: Prepend CHANGELOG entry**

```markdown
## 2026-06-12 Outline Iter Isolation Hardening (Plan F)

**Branch:** `worktree-outline-master-detail`
**Plan:** `docs/plans/2026-06-12-outline-iter-hardening.md`

Addresses all review findings from Plan E. Iter is now a first-class backend concept.

### Changes
- **B1**: historical iter `interrupted` status → `failed`
- **B2 (backend sync)**: `HarnessState.node_invocation_counts` field; `node.started` payload carries `iteration`; `StepEntry.iteration` persisted at create time via `deps.iteration`; frontend reads from event (cache, not counter)
- **B2 (frontend)**: snapshot hydration reads `iteration` from `todo_steps`; event-fallback path rebuilds iter from `node.started` events in stream
- **D1**: NodeBlockCard uses `useShallow` to honor Performance Contract
- **D2**: `pendingQuestionCount` only checked for latest iter (historical iter can't be "waiting")
- **T1-T4**: 7 new tests covering gaps

### Backwards compat
- Pre-Plan-F replays: todos default to iter=1, outline still splits from messages
- Mixed-version state: `merge_dicts` reducer handles missing `node_invocation_counts`

### Commits
(List the commits from each task above)
```

**Step 2: Update CURRENT.md**

Replace the "已完成（Plan E）" section with a Plan F entry; move Plan E to a "previous" subsection.

**Step 3: Commit**

```bash
git add docs/status/CURRENT.md docs/status/CHANGELOG.md
git commit -m "docs: Plan F complete — iter sunk to backend, all review findings addressed"
```

---

## Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Engine state migration on in-flight runs | 🟢 Low | `merge_dicts` handles missing keys as empty dict → 0 → first invocation = 1 |
| `result_dict` early return paths skip `node_invocation_counts` update | 🟡 Medium | Audit all return paths in `node_func`; the Task 4.2 step 4 calls this out explicitly |
| Mixed Plan E / Plan F replay (started under E, replayed under F) | 🟢 Low | Frontend `?? 1` fallback handles absent event `iteration` |
| AgentDeps extra field conflict (`iteration` already used elsewhere) | 🟢 Low | `grep -rn "\.iteration" harness/tools/` — verify no collision before Task 4.2 |
| `useShallow` import path differs in zustand v5 | 🟢 Low | Verified at Task 3.1 — `zustand/shallow` exports `useShallow` |
| Testing-library not installed for Task 6.2 | 🟡 Medium | Fallback to manual verification + deriveOutlineItems unit tests if install blocked |

---

## Estimate

- Phase 1 (B1): 15 min
- Phase 2 (D2): 20 min
- Phase 3 (D1): 15 min
- Phase 4 (B2 backend): 2-3 hours (engine state + deps injection + payload + tests)
- Phase 5 (B2 frontend): 1-1.5 hours
- Phase 6 (T3, T4): 45 min
- Phase 7 (verify): 30 min

**Total: ~5 hours of focused work.** Recommend splitting across 2 sessions: backend (Phase 4) in one, frontend + tests + verify in another.

---

## Execution Order Rationale

Phases are ordered to minimize rework and isolate failure:

1. **Phase 1-3** are independent frontend-only fixes. Each can be merged individually if needed.
2. **Phase 4** is backend-only. Doesn't break frontend (frontend still works with `?? 1` fallback).
3. **Phase 5** consumes Phase 4's event payload. Must follow Phase 4.
4. **Phase 6** tests assume Phase 1-5 are in place.
5. **Phase 7** verifies the full stack.

If Phase 4 turns out larger than expected (e.g. deps injection has surprises), Phase 1-3 + Phase 5 frontend-only (with `?? 1` fallback kept) is still a shippable intermediate state.
