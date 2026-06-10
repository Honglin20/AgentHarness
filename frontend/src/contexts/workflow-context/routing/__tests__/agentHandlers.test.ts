/**
 * Tests for PR-D agent handlers — workflow filtering + retry cap behavior.
 */

import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import type { WorkflowStores } from "@/contexts/workflow-context/types";
import type { WSEvent } from "@/types/events";
import { routeEvent } from "../index";

// Build a minimal stores mock — only the bits the PR-D handlers touch.
function makeStores(activeWorkflowId: string | null): WorkflowStores {
  const nodes: Record<string, any> = {};
  const workflowState: any = {
    workflowId: activeWorkflowId,
    nodes,
    pushRetryAttempt: vi.fn((nodeId: string, attempt: any) => {
      const existing = nodes[nodeId];
      const prev = existing?.retryAttempts ?? [];
      nodes[nodeId] = {
        ...existing,
        id: nodeId,
        status: "retrying",
        retryAttempts: [...prev, attempt].slice(-20),
      };
    }),
    setNodeUsage: vi.fn(),
    setClassifiedFailure: vi.fn(),
  };
  const workflow: any = {
    getState: () => workflowState,
    setState: vi.fn(),
    subscribe: vi.fn(),
    getInitialState: vi.fn(),
  };

  // Stub the other stores — routeEvent touches several but PR-D handlers
  // only call stores.workflow. Other handlers (e.g. agent.tool_call) may
  // run if we route the same event twice, but our tests route distinct
  // PR-D events only.
  const noopStore: any = {
    getState: () => ({}),
    setState: vi.fn(),
    subscribe: vi.fn(),
    getInitialState: vi.fn(),
  };

  return {
    workflow,
    conversation: noopStore,
    toolCall: noopStore,
    output: noopStore,
    chart: noopStore,
    chat: noopStore,
    todo: noopStore,
    span: noopStore,
    agentIO: noopStore,
    runHistory: noopStore,
  } as unknown as WorkflowStores;
}

function makeEvent<T extends string>(type: T, payload: any, seq = 1): WSEvent {
  return { type, ts: Date.now(), seq, payload } as WSEvent;
}

function makeCtx(): { mode: "live"; persistence: null; counter: { next(): string } } {
  let n = 0;
  return { mode: "live", persistence: null, counter: { next: () => `id-${++n}` } };
}

describe("PR-D agent handlers — workflow filtering", () => {
  beforeEach(() => {
    vi.resetModules();
  });

  it("agent.retry_attempted writes to store + toasts when workflow matches", async () => {
    const { routeEvent } = await import("../index");
    const { toast } = await import("sonner");
    const toastSpy = vi.spyOn(toast, "warning").mockImplementation(() => ({}) as any);

    const stores = makeStores("wf-active");
    routeEvent(
      stores,
      makeEvent("agent.retry_attempted", {
        workflow_id: "wf-active",
        node_id: "agent_a",
        agent_name: "agent_a",
        attempt: 1,
        max_attempts: 3,
        category: "server_error",
        reason: "HTTP 503",
        delay_s: 1.0,
        retry_after_s: null,
      }),
      makeCtx(),
    );

    expect(stores.workflow.getState().pushRetryAttempt).toHaveBeenCalledWith(
      "agent_a",
      expect.objectContaining({ attempt: 1, category: "server_error" }),
    );
    expect(toastSpy).toHaveBeenCalledTimes(1);
    expect(toastSpy.mock.calls[0][0]).toContain("agent_a");
    toastSpy.mockRestore();
  });

  it("agent.retry_attempted skips when workflow_id ≠ active (background wf)", async () => {
    const { routeEvent } = await import("../index");
    const { toast } = await import("sonner");
    const toastSpy = vi.spyOn(toast, "warning").mockImplementation(() => ({}) as any);

    const stores = makeStores("wf-active");
    routeEvent(
      stores,
      makeEvent("agent.retry_attempted", {
        workflow_id: "wf-background",  // different from active
        node_id: "agent_b",
        agent_name: "agent_b",
        attempt: 1,
        max_attempts: 3,
        category: "rate_limit",
        reason: "429",
        delay_s: 2.0,
        retry_after_s: 2.0,
      }),
      makeCtx(),
    );

    expect(stores.workflow.getState().pushRetryAttempt).not.toHaveBeenCalled();
    expect(toastSpy).not.toHaveBeenCalled();
    toastSpy.mockRestore();
  });

  it("agent.usage_update skips when workflow_id ≠ active", async () => {
    const { routeEvent } = await import("../index");
    const stores = makeStores("wf-active");
    routeEvent(
      stores,
      makeEvent("agent.usage_update", {
        workflow_id: "wf-background",
        node_id: "agent_b",
        agent_name: "agent_b",
        requests: 5,
        input_tokens: 100,
        output_tokens: 50,
        total_tokens: 150,
      }),
      makeCtx(),
    );
    expect(stores.workflow.getState().setNodeUsage).not.toHaveBeenCalled();
  });

  it("agent.failed_with_classified_reason skips when workflow_id ≠ active", async () => {
    const { routeEvent } = await import("../index");
    const stores = makeStores("wf-active");
    routeEvent(
      stores,
      makeEvent("agent.failed_with_classified_reason", {
        workflow_id: "wf-background",
        node_id: "agent_b",
        agent_name: "agent_b",
        category: "usage_exceeded",
        reason: "limit hit",
        error_type: "UsageLimitExceeded",
        message: "request_limit exceeded",
        attempts_used: 1,
        max_attempts: 3,
      }),
      makeCtx(),
    );
    expect(stores.workflow.getState().setClassifiedFailure).not.toHaveBeenCalled();
  });

  it("agent.failed_with_classified_reason does NOT toast (user preference: inline only)", async () => {
    const { routeEvent } = await import("../index");
    const { toast } = await import("sonner");
    const errorSpy = vi.spyOn(toast, "error").mockImplementation(() => ({}) as any);
    const warningSpy = vi.spyOn(toast, "warning").mockImplementation(() => ({}) as any);

    const stores = makeStores("wf-active");
    routeEvent(
      stores,
      makeEvent("agent.failed_with_classified_reason", {
        workflow_id: "wf-active",
        node_id: "agent_a",
        agent_name: "agent_a",
        category: "server_error",
        reason: "503 after 3 attempts",
        error_type: "ModelHTTPError",
        message: "503",
        attempts_used: 3,
        max_attempts: 3,
      }),
      makeCtx(),
    );

    expect(stores.workflow.getState().setClassifiedFailure).toHaveBeenCalled();
    expect(errorSpy).not.toHaveBeenCalled();
    expect(warningSpy).not.toHaveBeenCalled();
    errorSpy.mockRestore();
    warningSpy.mockRestore();
  });
});

describe("PR-D retry attempt cap (sanity guard against future max_attempts increases)", () => {
  it("pushRetryAttempt caps stored attempts at 20", () => {
    const stores = makeStores("wf-active");
    const nodeId = "agent_a";
    // Push 25 retry attempts — only the last 20 should be retained
    for (let i = 1; i <= 25; i++) {
      stores.workflow.getState().pushRetryAttempt(nodeId, {
        attempt: i,
        maxAttempts: 30,
        category: "server_error",
        reason: `fail ${i}`,
        delayS: 1.0,
        retryAfterS: null,
        ts: Date.now(),
      });
    }
    const stored = stores.workflow.getState().nodes[nodeId]?.retryAttempts;
    expect(stored).toHaveLength(20);
    // First 5 (attempts 1-5) dropped, last 20 (attempts 6-25) kept
    expect(stored?.[0].attempt).toBe(6);
    expect(stored?.[19].attempt).toBe(25);
  });
});
