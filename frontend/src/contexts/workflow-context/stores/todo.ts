import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { TodoStepItem, TodoAutoAdvance } from "@/types/events";
// Re-export for callers that still need hydration fallback (legacy runs).
export type { TodoStepItem } from "@/types/events";

export type TodoStepStatus =
  | "pending"
  | "in_progress"
  | "completed"
  | "skipped"
  | "interrupted";

export interface TodoStep {
  taskId: string;
  content: string;
  activeForm: string;
  status: TodoStepStatus;
  detail: string | null;
  /** Per-step token accumulation, attributed from agent.usage_update deltas. */
  tokenUsage?: { input: number; output: number; total: number };
}

export interface TodoState {
  todos: Record<string, TodoStep[]>; // key = nodeId
  /** Reset to initial state. Used by resetAllStores() when the workflow scope changes. */
  reset: () => void;
}

export function createTodoStore(
  _workflowId: string,
): StoreApi<TodoState> {
  const store = createStore<TodoState>()(() => ({
    todos: {},
    reset: () => store.setState({ todos: {}, reset: store.getState().reset }),
  }));
  return store;
}

export function handleTodoCreated(
  store: StoreApi<TodoState>,
  nodeId: string,
  items: TodoStepItem[],
) {
  store.setState((state) => {
    const existing = state.todos[nodeId] || [];
    const existingIds = new Set(existing.map((s) => s.taskId));
    const newSteps: TodoStep[] = items
      .filter((item) => !existingIds.has(item.task_id))
      .map((item) => ({
        taskId: item.task_id,
        content: item.content,
        activeForm: item.activeForm,
        status: item.status,
        detail: item.detail ?? null,
      }));
    return {
      todos: {
        ...state.todos,
        [nodeId]: [...existing, ...newSteps],
      },
    };
  });
}

export function handleTodoUpdated(
  store: StoreApi<TodoState>,
  nodeId: string,
  taskId: string,
  status?: "in_progress" | "completed" | "skipped" | null,
  detail?: string | null,
  autoAdvance?: TodoAutoAdvance | null,
) {
  store.setState((state) => {
    const steps = state.todos[nodeId];
    if (!steps) return state;

    const updated = steps.map((s) => {
      if (s.taskId === taskId) {
        return {
          ...s,
          ...(status != null ? { status } : {}),
          ...(detail !== undefined ? { detail } : {}),
        };
      }
      if (autoAdvance && s.taskId === autoAdvance.next_task_id) {
        return { ...s, status: autoAdvance.status };
      }
      return s;
    });

    return {
      todos: { ...state.todos, [nodeId]: updated },
    };
  });
}

/**
 * Bulk-finish all non-terminal steps for a node. Server-side this is
 * triggered by `todo op='complete_remaining'` (e.g. agent finished goal
 * early and bulk-completed remaining steps).
 *
 * After this call, currentStepIdByNode[nodeId] should be cleared by the
 * event handler — there is no "current" step anymore.
 */
export function handleTodoBulkCompleted(
  store: StoreApi<TodoState>,
  nodeId: string,
  finalStatus: "completed" | "skipped",
  taskIds: string[],
  reason?: string | null,
): void {
  const idSet = new Set(taskIds);
  store.setState((state) => {
    const steps = state.todos[nodeId];
    if (!steps) return state;
    const updated = steps.map((s) =>
      idSet.has(s.taskId)
        ? { ...s, status: finalStatus, detail: reason ?? s.detail }
        : s,
    );
    return {
      todos: { ...state.todos, [nodeId]: updated },
    };
  });
}

/**
 * Replace the entire step list for a node. Server-side this is triggered by
 * `todo op='replace'` when the agent discovers the original plan was wrong.
 *
 * The old steps are discarded entirely (no merge); new step ids are
 * generated server-side.
 */
export function handleTodoReplaced(
  store: StoreApi<TodoState>,
  nodeId: string,
  items: TodoStepItem[],
): void {
  store.setState((state) => {
    const newSteps: TodoStep[] = items.map((item) => ({
      taskId: item.task_id,
      content: item.content,
      activeForm: item.activeForm,
      status: item.status,
      detail: item.detail ?? null,
    }));
    return {
      todos: {
        ...state.todos,
        [nodeId]: newSteps,
      },
    };
  });
}

/**
 * Attribute a token delta to a specific step. Called from the agent.usage_update
 * handler after computing the delta between consecutive cumulative totals.
 */
export function accumulateStepTokens(
  store: StoreApi<TodoState>,
  nodeId: string,
  taskId: string,
  delta: { input: number; output: number; total: number },
): void {
  store.setState((state) => {
    const steps = state.todos[nodeId];
    if (!steps) return state;
    const updated = steps.map((s) => {
      if (s.taskId !== taskId) return s;
      const prev = s.tokenUsage;
      return {
        ...s,
        tokenUsage: prev
          ? {
              input: prev.input + delta.input,
              output: prev.output + delta.output,
              total: prev.total + delta.total,
            }
          : { ...delta },
      };
    });
    return { todos: { ...state.todos, [nodeId]: updated } };
  });
}

/**
 * Force all in_progress steps for a node to a terminal status. Used during
 * hydration when the workflow is already finished but the persisted todo
 * events show some steps stuck in_progress (workflow was killed mid-step,
 * or trailing todo.updated events weren't captured in the buffer).
 *
 * NOTE: After ADR 2026-06-10-todo-step-gate-adr.md, normal-completion runs
 * no longer need this (step_gate validator enforces all-terminal at output
 * time). Kept as a defensive hydration fallback for legacy runs and for
 * workflows that errored mid-step.
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
