// frontend/src/contexts/workflow-context/__tests__/replayEvents.iteration.test.ts
//
// Locks the Plan F contract that `iteration` survives the replay/hydration
// paths in loadRunFromPersistedData:
//   - snapshot path: iteration persisted in run.todo_steps surfaces on TodoStep
//   - event-fallback path: iteration is rebuilt from node.started events in
//     the stream and stamped onto todo.created-derived steps
//   - legacy data (no iteration field anywhere) degrades gracefully to
//     undefined, which consumers treat as iter=1
//
// Approach: integration test against the public loadRunFromPersistedData
// entry point with real scoped stores (same pattern as todoHydration.test.ts).
// The snapshot/event-fallback mapping is inline in loadRunFromPersistedData
// and not worth extracting for testability alone — exercising the public
// surface is more honest about the actual contract.
import { describe, it, expect, beforeEach } from "vitest";
import { loadRunFromPersistedData } from "../replayEvents";
import { getWorkflowManager } from "../WorkflowManager";

function makeBaseRun(workflowId: string) {
  return {
    conversation: [],
    dag: { nodes: ["coder"], edges: [] },
    result: {
      outputs: {},
      errors: {},
      trace: [
        { agent_name: "coder", status: "success", duration_ms: 100, error: null },
      ],
    },
    chart_groups: null,
  } as any;
}

describe("loadRunFromPersistedData — iteration hydration (Plan F)", () => {
  beforeEach(() => {
    getWorkflowManager().reset();
  });

  describe("snapshot path", () => {
    it("preserves iteration field from persisted todo_steps", () => {
      const workflowId = "iter-snap-1";
      const run = {
        ...makeBaseRun(workflowId),
        todo_steps: {
          coder: [
            {
              task_id: "s1",
              content: "first-pass step",
              activeForm: "Doing s1",
              status: "completed",
              detail: null,
              iteration: 1,
            },
            {
              task_id: "s2",
              content: "second-pass step",
              activeForm: "Doing s2",
              status: "completed",
              detail: null,
              iteration: 2,
            },
          ],
        },
      } as any;

      loadRunFromPersistedData(workflowId, run, undefined);

      const todos = getWorkflowManager().getStores(workflowId)!.todo.getState().todos;
      expect(todos.coder).toHaveLength(2);
      expect(todos.coder[0].iteration).toBe(1);
      expect(todos.coder[1].iteration).toBe(2);
    });

    it("legacy snapshot without iteration field degrades to undefined (treated as 1 by consumers)", () => {
      // Pre-Plan-F snapshot: steps have no iteration field. Hydration must
      // not crash, and consumers' `(t.iteration ?? 1) === n` filter must
      // surface them under iter=1.
      const workflowId = "iter-snap-legacy";
      const run = {
        ...makeBaseRun(workflowId),
        todo_steps: {
          coder: [
            {
              task_id: "s1",
              content: "legacy step",
              activeForm: "Doing s1",
              status: "completed",
              detail: null,
              // no iteration field
            },
          ],
        },
      } as any;

      loadRunFromPersistedData(workflowId, run, undefined);

      const steps = getWorkflowManager().getStores(workflowId)!.todo.getState().todos.coder;
      expect(steps).toHaveLength(1);
      // iteration is undefined (not coerced to 1 at the store layer — that
      // coercion lives in consumers, intentionally).
      expect(steps[0].iteration).toBeUndefined();
      // Consumer-side filter surfaces it under iter=1.
      const iter1 = steps.filter((s) => (s.iteration ?? 1) === 1);
      expect(iter1).toHaveLength(1);
    });
  });

  describe("event-fallback path", () => {
    it("reads iteration from node.started events and stamps todo.created steps", () => {
      // No todo_steps snapshot → forces the event-fallback path. The
      // stream carries two node.started events with iteration=1 then 2,
      // each followed by a todo.created. Rebuilt convByNode map should
      // stamp the second batch of steps with iteration=2.
      const workflowId = "iter-evt-1";
      const run = makeBaseRun(workflowId);
      const events = [
        {
          type: "node.started",
          payload: {
            workflow_id: workflowId,
            node_id: "coder",
            agent_name: "coder",
            iteration: 1,
          },
        },
        {
          type: "todo.created",
          payload: {
            workflow_id: workflowId,
            node_id: "coder",
            items: [
              { task_id: "s1", content: "pass-1 a", active_form: "A", status: "completed", detail: null },
              { task_id: "s2", content: "pass-1 b", active_form: "B", status: "completed", detail: null },
            ],
          },
        },
        {
          type: "node.completed",
          payload: {
            workflow_id: workflowId,
            node_id: "coder",
            agent_name: "coder",
            duration_ms: 100,
            status: "success",
          },
        },
        {
          type: "node.started",
          payload: {
            workflow_id: workflowId,
            node_id: "coder",
            agent_name: "coder",
            iteration: 2,
          },
        },
        {
          type: "todo.created",
          payload: {
            workflow_id: workflowId,
            node_id: "coder",
            items: [
              { task_id: "s3", content: "pass-2 a", active_form: "C", status: "in_progress", detail: null },
              { task_id: "s4", content: "pass-2 b", active_form: "D", status: "in_progress", detail: null },
            ],
          },
        },
      ] as any[];

      loadRunFromPersistedData(workflowId, run, events);

      const steps = getWorkflowManager().getStores(workflowId)!.todo.getState().todos.coder;
      expect(steps).toHaveLength(4);
      const byTask = Object.fromEntries(steps.map((s) => [s.taskId, s.iteration]));
      expect(byTask.s1).toBe(1);
      expect(byTask.s2).toBe(1);
      expect(byTask.s3).toBe(2);
      expect(byTask.s4).toBe(2);
    });

    it("legacy events without iteration on node.started fall back to iter=1", () => {
      // Pre-Plan-F event stream: node.started has no iteration field.
      // convByNode map should default to 1, and todo.created steps inherit
      // that default.
      const workflowId = "iter-evt-legacy";
      const run = makeBaseRun(workflowId);
      const events = [
        {
          type: "node.started",
          payload: {
            workflow_id: workflowId,
            node_id: "coder",
            agent_name: "coder",
            // no iteration field
          },
        },
        {
          type: "todo.created",
          payload: {
            workflow_id: workflowId,
            node_id: "coder",
            items: [
              { task_id: "s1", content: "legacy", active_form: "L", status: "completed", detail: null },
            ],
          },
        },
      ] as any[];

      loadRunFromPersistedData(workflowId, run, events);

      const steps = getWorkflowManager().getStores(workflowId)!.todo.getState().todos.coder;
      expect(steps).toHaveLength(1);
      // handleTodoCreated receives iter=1 from the convByNode fallback and
      // stamps it explicitly (unlike the snapshot path, which leaves it
      // undefined for legacy data — the two paths differ here intentionally:
      // the snapshot path preserves what was persisted, the event-fallback
      // path applies a defaulted stamp at creation time).
      expect(steps[0].iteration).toBe(1);
    });
  });
});
