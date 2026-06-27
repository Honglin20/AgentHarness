/**
 * P2-T8: workflowStore error/retry/status handler acceptance tests.
 *
 * Locks the contract that the new actions (handleWorkflowError /
 * pushExecutorError / pushApiRetry / pushStatusUpdate) update NodeState
 * correctly:
 *   - handleWorkflowError sweeps orphan running nodes (matches
 *     handleWorkflowCompleted behavior)
 *   - handleWorkflowError stamps error on failed_node when the payload
 *     carries one
 *   - pushExecutorError stashes the structured failure without flipping
 *     lifecycle status (node.failed still owns that)
 *   - pushApiRetry / pushStatusUpdate stash the latest values
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useWorkflowStore } from "../workflowStore";
import type {
  WorkflowErrorPayload,
  ExecutorErrorPayload,
  ApiRetryPayload,
  StatusUpdatePayload,
  NodeStartedPayload,
} from "@/types/events";

const SAMPLE_WID = "wf-test";

function startNode(nodeId: string, agentName: string = nodeId) {
  useWorkflowStore.getState().handleNodeStarted({
    node_id: nodeId,
    agent_name: agentName,
    attempt: 1,
  } as NodeStartedPayload);
}

function reset() {
  useWorkflowStore.setState({
    workflowId: SAMPLE_WID,
    workflowName: "test",
    status: "running",
    nodes: {},
    dag: null,
    envelope: null,
    fitnessHistory: [],
    currentIter: null,
    conversationIterFilter: null,
    activeWorkflowId: SAMPLE_WID,
  });
}

describe("P2-T8 workflowStore error event handlers", () => {
  beforeEach(() => reset());

  // -------------------------------------------------------------------------
  // handleWorkflowError
  // -------------------------------------------------------------------------

  describe("handleWorkflowError", () => {
    it("sets workflow status to failed", () => {
      const payload: WorkflowErrorPayload = {
        workflow_id: SAMPLE_WID,
        error: "boom",
        error_type: "RuntimeError",
      };
      useWorkflowStore.getState().handleWorkflowError(payload);
      expect(useWorkflowStore.getState().status).toBe("failed");
    });

    it("sweeps orphan running nodes on failure", () => {
      startNode("agent-a");
      startNode("agent-b");
      // Both running — sweep should mark them failed
      useWorkflowStore.getState().handleWorkflowError({
        workflow_id: SAMPLE_WID, error: "boom", error_type: "RuntimeError",
      });
      expect(useWorkflowStore.getState().nodes["agent-a"].status).toBe("failed");
      expect(useWorkflowStore.getState().nodes["agent-b"].status).toBe("failed");
    });

    it("stamps error on failed_node when payload carries one", () => {
      startNode("greeter");
      useWorkflowStore.getState().handleWorkflowError({
        workflow_id: SAMPLE_WID,
        error: "claude exited code=1",
        error_type: "ExecutorError",
        executor: "claude-code",
        phase: "spawn",
        stderr_tail: "Error: invalid token",
        failed_node: "greeter",
      });
      const node = useWorkflowStore.getState().nodes["greeter"];
      expect(node.status).toBe("failed");
      expect(node.error).toBe("claude exited code=1");
      expect(node.errorType).toBe("ExecutorError");
    });

    it("synthesizes NodeState when failed_node is unknown", () => {
      // Edge case: payload names a node that never emitted node.started
      // (e.g. workflow crashed mid-spawn before node.started was emitted)
      useWorkflowStore.getState().handleWorkflowError({
        workflow_id: SAMPLE_WID,
        error: "spawn crashed",
        error_type: "RuntimeError",
        failed_node: "ghost",
      });
      const node = useWorkflowStore.getState().nodes["ghost"];
      expect(node).toBeDefined();
      expect(node?.status).toBe("failed");
      expect(node?.error).toBe("spawn crashed");
    });

    it("does not touch nodes when no failed_node in payload", () => {
      startNode("agent-a");
      useWorkflowStore.getState().handleWorkflowError({
        workflow_id: SAMPLE_WID,
        error: "workflow setup crashed",
        error_type: "RuntimeError",
        // no failed_node
      });
      // agent-a swept to failed (orphan sweep), but no extra ghost node added
      expect(Object.keys(useWorkflowStore.getState().nodes)).toEqual(["agent-a"]);
    });
  });

  // -------------------------------------------------------------------------
  // pushExecutorError
  // -------------------------------------------------------------------------

  describe("pushExecutorError", () => {
    it("stashes executorError on the node WITHOUT flipping lifecycle status", () => {
      startNode("greeter");
      // Node currently "running"
      expect(useWorkflowStore.getState().nodes["greeter"].status).toBe("running");

      const payload: ExecutorErrorPayload = {
        workflow_id: SAMPLE_WID,
        node_id: "greeter",
        agent_name: "greeter",
        executor: "claude-code",
        phase: "spawn",
        error_type: "ClaudeSubprocessExit",
        error_message: "claude exited code=1",
        stderr_tail: "Error: invalid token",
        exit_code: 1,
        timed_out: false,
        ts: 1234567890,
      };
      useWorkflowStore.getState().pushExecutorError("greeter", payload);

      const node = useWorkflowStore.getState().nodes["greeter"];
      expect(node.executorError).toEqual(payload);
      // Lifecycle status UNCHANGED — node.failed (from node_factory except)
      // still owns the lifecycle transition.
      expect(node.status).toBe("running");
    });

    it("synthesizes node if it does not exist yet", () => {
      const payload: ExecutorErrorPayload = {
        workflow_id: SAMPLE_WID,
        node_id: "ghost",
        agent_name: "ghost",
        executor: "claude-code",
        phase: "stream",
        error_type: "ClaudeStreamError",
        error_message: "rate limited",
        timed_out: false,
        ts: 1,
      };
      useWorkflowStore.getState().pushExecutorError("ghost", payload);
      const node = useWorkflowStore.getState().nodes["ghost"];
      expect(node).toBeDefined();
      expect(node?.executorError).toEqual(payload);
      expect(node?.status).toBe("failed");
    });
  });

  // -------------------------------------------------------------------------
  // pushApiRetry
  // -------------------------------------------------------------------------

  describe("pushApiRetry", () => {
    it("stashes lastApiRetry on the node", () => {
      startNode("analyzer");
      const p1: ApiRetryPayload = {
        node_id: "analyzer", agent_name: "analyzer",
        retry_count: 1, max_retries: 3, wait_seconds: 2,
      };
      const p2: ApiRetryPayload = {
        node_id: "analyzer", agent_name: "analyzer",
        retry_count: 2, max_retries: 3, wait_seconds: 4,
      };
      useWorkflowStore.getState().pushApiRetry("analyzer", p1);
      useWorkflowStore.getState().pushApiRetry("analyzer", p2);
      expect(useWorkflowStore.getState().nodes["analyzer"].lastApiRetry).toEqual(p2);
    });
  });

  // -------------------------------------------------------------------------
  // pushStatusUpdate
  // -------------------------------------------------------------------------

  describe("pushStatusUpdate", () => {
    it("stashes lastStatus on the node without flipping lifecycle", () => {
      startNode("scout");
      const p: StatusUpdatePayload = {
        node_id: "scout", agent_name: "scout",
        status: "thinking", duration_ms: 250,
      };
      useWorkflowStore.getState().pushStatusUpdate("scout", p);
      const node = useWorkflowStore.getState().nodes["scout"];
      expect(node.lastStatus).toEqual(p);
      expect(node.status).toBe("running"); // lifecycle unchanged
    });
  });
});
