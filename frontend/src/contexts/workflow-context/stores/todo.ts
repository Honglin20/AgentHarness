import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { TodoStepItem, TodoAutoAdvance } from "@/types/events";

export interface TodoStep {
  taskId: string;
  content: string;
  activeForm: string;
  status: "pending" | "in_progress" | "completed";
  detail: string | null;
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
  status?: "in_progress" | "completed" | null,
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
