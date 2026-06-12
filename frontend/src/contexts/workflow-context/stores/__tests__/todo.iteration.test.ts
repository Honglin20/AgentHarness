import { describe, it, expect } from "vitest";
import {
  createTodoStore,
  handleTodoCreated,
  handleTodoReplaced,
  handleTodoUpdated,
  type TodoStep,
} from "../todo";
import type { TodoStepItem } from "@/types/events";

function step(partial: Partial<TodoStepItem>): TodoStepItem {
  return {
    task_id: partial.task_id ?? "t1",
    content: partial.content ?? "step",
    activeForm: partial.activeForm ?? "stepping",
    status: partial.status ?? "in_progress",
    detail: partial.detail ?? null,
  };
}

describe("TodoStep.iteration stamping", () => {
  it("handleTodoCreated stamps iteration on each new step", () => {
    const store = createTodoStore("wf-1");
    handleTodoCreated(store, "coder", [step({ task_id: "s1" })], 2);
    expect(store.getState().todos.coder[0].iteration).toBe(2);
  });

  it("handleTodoCreated with iter=1 stamps 1 (normal first iteration)", () => {
    const store = createTodoStore("wf-1");
    handleTodoCreated(store, "coder", [step({ task_id: "s1" })], 1);
    expect(store.getState().todos.coder[0].iteration).toBe(1);
  });

  it("second handleTodoCreated with higher iter doesn't disturb existing steps' iter", () => {
    // Loop scenario: iter=1 creates s1+s2, iter=2 creates s3+s4. Existing
    // steps (s1, s2) must retain iteration=1 — the stamp is at creation
    // time, not retroactively rewritten.
    const store = createTodoStore("wf-1");
    handleTodoCreated(
      store,
      "coder",
      [step({ task_id: "s1" }), step({ task_id: "s2" })],
      1,
    );
    handleTodoCreated(
      store,
      "coder",
      [step({ task_id: "s3" }), step({ task_id: "s4" })],
      2,
    );
    const steps = store.getState().todos.coder;
    expect(steps.find((s) => s.taskId === "s1")?.iteration).toBe(1);
    expect(steps.find((s) => s.taskId === "s2")?.iteration).toBe(1);
    expect(steps.find((s) => s.taskId === "s3")?.iteration).toBe(2);
    expect(steps.find((s) => s.taskId === "s4")?.iteration).toBe(2);
  });

  it("handleTodoReplaced stamps iteration on replacement steps", () => {
    // Replace wipes old steps and stamps the new ones with the given iter.
    const store = createTodoStore("wf-1");
    handleTodoCreated(store, "coder", [step({ task_id: "old" })], 1);
    handleTodoReplaced(store, "coder", [step({ task_id: "new" })], 2);
    const steps = store.getState().todos.coder;
    expect(steps).toHaveLength(1);
    expect(steps[0].taskId).toBe("new");
    expect(steps[0].iteration).toBe(2);
  });

  it("handleTodoUpdated preserves iteration (status change only)", () => {
    // Updates mutate existing steps in-place; iteration was set at
    // creation time and must not be touched by status/detail updates.
    const store = createTodoStore("wf-1");
    handleTodoCreated(store, "coder", [step({ task_id: "s1" })], 2);
    handleTodoUpdated(store, "coder", "s1", "completed", null, null);
    expect(store.getState().todos.coder[0].iteration).toBe(2);
    expect(store.getState().todos.coder[0].status).toBe("completed");
  });

  it("legacy steps without iteration are filtered as iter=1 by consumers", () => {
    // Simulates persisted data from before this PR (snapshot hydration
    // path in replayEvents.ts). Consumer code uses `(t.iteration ?? 1) === n`.
    const store = createTodoStore("wf-1");
    store.setState({
      todos: {
        coder: [
          {
            taskId: "legacy",
            content: "old",
            activeForm: "old",
            status: "completed",
            detail: null,
          } as TodoStep,
        ],
      },
    });
    const iter1Steps = store
      .getState()
      .todos.coder.filter((t) => (t.iteration ?? 1) === 1);
    const iter2Steps = store
      .getState()
      .todos.coder.filter((t) => (t.iteration ?? 1) === 2);
    expect(iter1Steps).toHaveLength(1);
    expect(iter2Steps).toHaveLength(0);
  });
});
