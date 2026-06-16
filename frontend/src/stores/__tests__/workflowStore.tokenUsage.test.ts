/**
 * workflowStore.setNodeUsage — stage 2 token-stats semantic split.
 *
 * Verifies the store correctly persists stage-2 fields (lastInput,
 * lastOutput, cumulativeCacheHit, lastCacheHit) when provided, AND
 * leaves them undefined when absent (old backend events).
 *
 * This is the load-bearing test for the BudgetBar Window-bar visibility
 * rule: BudgetBar hides the Window bar when lastInput is undefined, so
 * the store must NOT silently default it to cumulative.
 */

import { describe, it, expect, beforeEach } from "vitest";
import { useWorkflowStore } from "../workflowStore";

describe("setNodeUsage — stage 2 fields", () => {
  beforeEach(() => {
    useWorkflowStore.setState({ nodes: {} });
  });

  it("persists last_input / last_output / cache_hit / last_cache_hit when provided", () => {
    useWorkflowStore.getState().setNodeUsage(
      "agent_a",
      3,
      250,        // cumulative input
      30,         // cumulative output
      80,         // lastInput
      10,         // lastOutput
      15,         // cumulativeCacheHit
      5,          // lastCacheHit
    );

    const node = useWorkflowStore.getState().nodes["agent_a"];
    expect(node.requests).toBe(3);
    expect(node.tokenUsage).toEqual({
      input: 250,
      output: 30,
      total: 280,
      cumulativeInput: 250,
      cumulativeOutput: 30,
      lastInput: 80,
      lastOutput: 10,
      cumulativeCacheHit: 15,
      lastCacheHit: 5,
      cacheHit: 15,
    });
  });

  it("leaves last_* UNDEFINED when stage-2 fields absent (old backend events)", () => {
    // Critical: BudgetBar uses lastInput === undefined to detect "no stage-2
    // data" and hide the Window bar. If we defaulted lastInput to cumulative,
    // old runs would show misleading 125% red bars.
    useWorkflowStore.getState().setNodeUsage(
      "agent_a",
      3,
      250_000,    // huge cumulative
      30_000,
      // No stage-2 args
    );

    const node = useWorkflowStore.getState().nodes["agent_a"];
    expect(node.tokenUsage?.lastInput).toBeUndefined();
    expect(node.tokenUsage?.lastOutput).toBeUndefined();
    expect(node.tokenUsage?.lastCacheHit).toBeUndefined();
    // Cumulative fields still populated (legacy semantics preserved)
    expect(node.tokenUsage?.input).toBe(250_000);
    expect(node.tokenUsage?.cumulativeInput).toBe(250_000);
  });

  it("overwrites previous values on subsequent updates (cumulative grows, last tracks recent)", () => {
    useWorkflowStore.getState().setNodeUsage("agent_a", 1, 50, 5, 50, 5, 0, 0);
    useWorkflowStore.getState().setNodeUsage("agent_a", 2, 120, 12, 70, 7, 5, 5);

    const node = useWorkflowStore.getState().nodes["agent_a"];
    expect(node.tokenUsage?.cumulativeInput).toBe(120);  // grew
    expect(node.tokenUsage?.lastInput).toBe(70);         // replaced (most recent)
    expect(node.tokenUsage?.lastCacheHit).toBe(5);
  });
});
