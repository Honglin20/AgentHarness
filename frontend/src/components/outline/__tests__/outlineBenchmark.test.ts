/**
 * Benchmark: deriveOutlineItems (live / fallback path) vs outlineSummaryToItems
 * (new sidecar path).
 *
 * Constructs a synthetic long workflow (N agents × M iterations × K messages
 * per iter) and times both projections over many runs to amortize JIT.
 *
 * Run: `npm test -- --run outlineBenchmark`
 */
import { describe, it, expect } from "vitest";
import { deriveOutlineItems } from "../deriveOutlineItems";
import { outlineSummaryToItems } from "../outlineSummaryToItems";
import type { OutlineSummaryItem } from "@/stores/runHistoryStore";
import type { ConversationMessage } from "@/stores/conversationStore";
import type { NodeState } from "@/stores/workflowStore";
import type { TodoStep } from "@/contexts/workflow-context/stores/todo";

function buildFixture(agentCount: number, iterPerAgent: number, msgsPerIter: number) {
  const nodes: Record<string, NodeState> = {};
  const messages: ConversationMessage[] = [];
  const todos: Record<string, TodoStep[]> = {};
  const summary: OutlineSummaryItem[] = [];

  let ts = 1_000_000;
  let msgCounter = 0;
  let order = 0;

  for (let a = 0; a < agentCount; a++) {
    const nodeId = `agent_${a}`;
    nodes[nodeId] = {
      id: nodeId,
      name: nodeId,
      status: "success",
      durationMs: 1234,
      tokenUsage: { input: 1000, output: 500, total: 1500 },
      retryAttempts: [],
    } as unknown as NodeState;
    todos[nodeId] = [];

    for (let iter = 1; iter <= iterPerAgent; iter++) {
      const firstTs = ts;
      for (let m = 0; m < msgsPerIter; m++) {
        messages.push({
          id: `msg-${msgCounter++}`,
          type: "agent",
          nodeId,
          agentName: nodeId,
          content: `agent ${a} iter ${iter} message ${m}: `.repeat(20),
          status: "done",
          timestamp: ts++,
          iteration: iter,
        } as ConversationMessage);
      }
      const isLatest = iter === iterPerAgent;
      summary.push({
        key: `${nodeId}__iter${iter}`,
        node_id: nodeId,
        iteration: iter,
        is_latest_iter: isLatest,
        iter_count: iterPerAgent,
        name: nodeId,
        first_ts: firstTs,
        status: "completed",
        activity: { kind: "completed", durationMs: 1234 },
        badges: isLatest
          ? [{ kind: "tokens", text: "1.5k", title: "1000 in / 500 out" }]
          : [],
        order: order++,
      });
    }
  }

  return { nodes, messages, todos, summary };
}

function time(fn: () => void, runs: number): { avg: number; min: number; max: number; total: number } {
  // Warm-up
  for (let i = 0; i < 5; i++) fn();

  const samples: number[] = [];
  for (let i = 0; i < runs; i++) {
    const t0 = performance.now();
    fn();
    samples.push(performance.now() - t0);
  }
  samples.sort((a, b) => a - b);
  return {
    avg: samples.reduce((s, x) => s + x, 0) / samples.length,
    min: samples[0],
    max: samples[samples.length - 1],
    total: samples.reduce((s, x) => s + x, 0),
  };
}

describe("outline projection benchmark", () => {
  it("reports timings for NAS-scale workload (8 agents × 5 iter × 50 msgs)", () => {
    const { nodes, messages, todos, summary } = buildFixture(8, 5, 50);
    const runs = 50;

    const derive = time(
      () => deriveOutlineItems(nodes, messages, todos),
      runs,
    );
    const sidecar = time(
      () => outlineSummaryToItems(summary),
      runs,
    );

    // eslint-disable-next-line no-console
    console.log(`\n[outline benchmark] ${runs} runs each, workload=${messages.length} msgs / ${summary.length} outline items`);
    // eslint-disable-next-line no-console
    console.log(`  deriveOutlineItems (live/fallback): avg=${derive.avg.toFixed(3)}ms min=${derive.min.toFixed(3)}ms max=${derive.max.toFixed(3)}ms`);
    // eslint-disable-next-line no-console
    console.log(`  outlineSummaryToItems (sidecar):    avg=${sidecar.avg.toFixed(3)}ms min=${sidecar.min.toFixed(3)}ms max=${sidecar.max.toFixed(3)}ms`);
    // eslint-disable-next-line no-console
    console.log(`  speedup: ${(derive.avg / sidecar.avg).toFixed(1)}x`);

    // Sanity: both paths produce the same number of items.
    const deriveItems = deriveOutlineItems(nodes, messages, todos);
    const sidecarItems = outlineSummaryToItems(summary);
    expect(deriveItems.length).toBe(sidecarItems.length);

    // Sidecar MUST be materially faster on this workload.
    expect(sidecar.avg).toBeLessThan(derive.avg);
  });

  it("reports timings for stress workload (20 agents × 10 iter × 100 msgs)", () => {
    const { nodes, messages, todos, summary } = buildFixture(20, 10, 100);
    const runs = 20;

    const derive = time(
      () => deriveOutlineItems(nodes, messages, todos),
      runs,
    );
    const sidecar = time(
      () => outlineSummaryToItems(summary),
      runs,
    );

    // eslint-disable-next-line no-console
    console.log(`\n[outline benchmark — stress] ${runs} runs each, workload=${messages.length} msgs / ${summary.length} outline items`);
    // eslint-disable-next-line no-console
    console.log(`  deriveOutlineItems (live/fallback): avg=${derive.avg.toFixed(3)}ms`);
    // eslint-disable-next-line no-console
    console.log(`  outlineSummaryToItems (sidecar):    avg=${sidecar.avg.toFixed(3)}ms`);
    // eslint-disable-next-line no-console
    console.log(`  speedup: ${(derive.avg / sidecar.avg).toFixed(1)}x`);

    expect(sidecar.avg).toBeLessThan(derive.avg);
  });
});
