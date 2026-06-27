/**
 * handleWorkflowCompleted — orphan running-node sweep.
 *
 * Regression test for the "backend failed but Outline shows working" bug.
 *
 * Root cause: server/runner.py emits only workflow.error/workflow.completed
 * on a workflow-level failure — it does NOT emit node.failed for whatever
 * node was mid-execution. handleWorkflowCompleted used to only update the
 * top-level `status`, leaving nodes[id].status stuck on "running". The
 * Outline view derives status from node.status, so it showed "working"
 * forever while the history bar (fed by the persisted run record) showed
 * "failed".
 *
 * Fix: handleWorkflowCompleted now calls sweepOrphanRunning to flip any
 * running/retrying node to "failed" when the workflow itself failed.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useWorkflowStore, type NodeState } from "../workflowStore";

function makeNode(id: string, status: NodeState["status"]): NodeState {
  return { id, name: id, status };
}

describe("handleWorkflowCompleted — orphan running-node sweep", () => {
  beforeEach(() => {
    useWorkflowStore.setState({
      nodes: {},
      status: "running",
      workflowId: "wf-1",
    });
  });

  it("marks running/retrying nodes as failed when workflow fails", () => {
    useWorkflowStore.setState({
      nodes: {
        done_agent: makeNode("done_agent", "success"),
        mid_agent: makeNode("mid_agent", "running"),
        retry_agent: makeNode("retry_agent", "retrying"),
      },
    });

    useWorkflowStore.getState().handleWorkflowCompleted({
      workflow_id: "wf-1",
      status: "failed",
    });

    const nodes = useWorkflowStore.getState().nodes;
    expect(useWorkflowStore.getState().status).toBe("failed");
    // Already-terminal node untouched.
    expect(nodes.done_agent.status).toBe("success");
    // Orphans swept to failed with an error stamp.
    expect(nodes.mid_agent.status).toBe("failed");
    expect(nodes.mid_agent.error).toBe("Workflow terminated");
    expect(nodes.retry_agent.status).toBe("failed");
    expect(nodes.retry_agent.error).toBe("Workflow terminated");
  });

  it("preserves existing node error when sweeping", () => {
    useWorkflowStore.setState({
      nodes: {
        mid_agent: { ...makeNode("mid_agent", "running"), error: "original err" },
      },
    });

    useWorkflowStore.getState().handleWorkflowCompleted({
      workflow_id: "wf-1",
      status: "failed",
    });

    // Existing error must not be overwritten by the generic message.
    expect(useWorkflowStore.getState().nodes.mid_agent.status).toBe("failed");
    expect(useWorkflowStore.getState().nodes.mid_agent.error).toBe("original err");
  });

  it("does NOT sweep running nodes on paused/interrupted (resume must continue them)", () => {
    useWorkflowStore.setState({
      nodes: {
        mid_agent: makeNode("mid_agent", "running"),
      },
    });

    useWorkflowStore.getState().handleWorkflowCompleted({
      workflow_id: "wf-1",
      status: "paused",
    });

    expect(useWorkflowStore.getState().status).toBe("paused");
    // Running node left intact — resume needs to pick it back up.
    expect(useWorkflowStore.getState().nodes.mid_agent.status).toBe("running");
    expect(useWorkflowStore.getState().nodes.mid_agent.error).toBeUndefined();
  });

  it("defensively sweeps on completed (no error stamp)", () => {
    useWorkflowStore.setState({
      nodes: {
        mid_agent: makeNode("mid_agent", "running"),
      },
    });

    useWorkflowStore.getState().handleWorkflowCompleted({
      workflow_id: "wf-1",
      status: "completed",
    });

    expect(useWorkflowStore.getState().status).toBe("completed");
    // Swept to failed (terminal) but WITHOUT a failure message — completed
    // is defensive, not an actual failure.
    expect(useWorkflowStore.getState().nodes.mid_agent.status).toBe("failed");
    expect(useWorkflowStore.getState().nodes.mid_agent.error).toBeUndefined();
  });

  it("is a no-op when no running/retrying nodes exist", () => {
    useWorkflowStore.setState({
      nodes: {
        done_agent: makeNode("done_agent", "success"),
        fail_agent: makeNode("fail_agent", "failed"),
      },
    });

    useWorkflowStore.getState().handleWorkflowCompleted({
      workflow_id: "wf-1",
      status: "failed",
    });

    const nodes = useWorkflowStore.getState().nodes;
    expect(nodes.done_agent.status).toBe("success");
    expect(nodes.fail_agent.status).toBe("failed");
  });
});
