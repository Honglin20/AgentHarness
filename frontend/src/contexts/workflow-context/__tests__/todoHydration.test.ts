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
