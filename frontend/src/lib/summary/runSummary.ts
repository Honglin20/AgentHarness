import type { NodeState } from "@/stores/workflowStore";
import type { ChartPayload } from "@/types/events";
import { useSpanStore } from "@/stores/spanStore";

const LABEL = "Run Summary";
const CATEGORY = "analysis";

type AddChartFn = (payload: ChartPayload) => void;
type SummaryComputer = (nodes: NodeState[]) => ChartPayload[];

function tokensByAgent(nodes: NodeState[]): ChartPayload[] {
  const withTokens = nodes.filter((n) => n.tokenUsage);
  if (withTokens.length === 0) return [];
  const data: Record<string, unknown>[] = [];
  for (const n of withTokens) {
    data.push({ agent: n.name, kind: "input", tokens: n.tokenUsage!.input });
    data.push({ agent: n.name, kind: "output", tokens: n.tokenUsage!.output });
  }
  return [{
    label: LABEL,
    title: "Tokens by Agent",
    chart_type: "bar",
    category: CATEGORY,
    data,
    columns: ["agent", "kind", "tokens"],
    x: "agent",
    y: "tokens",
    hue: "kind",
  }];
}

function durationByAgent(nodes: NodeState[]): ChartPayload[] {
  const withDuration = nodes.filter((n) => n.durationMs != null);
  if (withDuration.length === 0) return [];
  const data = withDuration.map((n) => ({
    agent: n.name,
    duration_ms: n.durationMs,
  }));
  return [{
    label: LABEL,
    title: "Duration (ms) by Agent",
    chart_type: "bar",
    category: CATEGORY,
    data,
    columns: ["agent", "duration_ms"],
    x: "agent",
    y: "duration_ms",
  }];
}

function costByAgent(nodes: NodeState[]): ChartPayload[] {
  const withCost = nodes.filter((n) => n.costUsd != null && n.costUsd > 0);
  if (withCost.length === 0) return [];
  const data = withCost.map((n) => ({
    agent: n.name,
    cost_usd: n.costUsd,
  }));
  return [{
    label: LABEL,
    title: "Cost (USD) by Agent",
    chart_type: "bar",
    category: CATEGORY,
    data,
    columns: ["agent", "cost_usd"],
    x: "agent",
    y: "cost_usd",
  }];
}

function ttftByAgent(nodes: NodeState[]): ChartPayload[] {
  const withTTFT = nodes.filter((n) => n.ttftMs != null && n.ttftMs > 0);
  if (withTTFT.length === 0) return [];
  const data = withTTFT.map((n) => ({
    agent: n.name,
    ttft_ms: n.ttftMs,
  }));
  return [{
    label: LABEL,
    title: "Time to First Token (ms)",
    chart_type: "bar",
    category: CATEGORY,
    data,
    columns: ["agent", "ttft_ms"],
    x: "agent",
    y: "ttft_ms",
  }];
}

function stepsByAgent(nodes: NodeState[]): ChartPayload[] {
  const withSteps = nodes.filter((n) => n.toolCallCount != null && n.toolCallCount > 0);
  if (withSteps.length === 0) return [];
  const data: Record<string, unknown>[] = [];
  for (const n of withSteps) {
    data.push({ agent: n.name, kind: "tool", count: n.toolCallCount });
    if (n.llmCallCount != null && n.llmCallCount > 0) {
      data.push({ agent: n.name, kind: "llm", count: n.llmCallCount });
    }
  }
  if (data.length === 0) return [];
  return [{
    label: LABEL,
    title: "Steps by Agent",
    chart_type: "bar",
    category: CATEGORY,
    data,
    columns: ["agent", "kind", "count"],
    x: "agent",
    y: "count",
    hue: "kind",
  }];
}

function executionTimeline(_nodes: NodeState[]): ChartPayload[] {
  const rows = useSpanStore.getState().computeWaterfallData();
  if (rows.length === 0) return [];

  return [{
    label: LABEL,
    title: "Execution Timeline",
    chart_type: "waterfall",
    category: CATEGORY,
    data: rows as unknown as Record<string, unknown>[],
    columns: ["agent", "start_ms", "duration_ms", "kind", "label"],
  }];
}

function runOverviewTable(nodes: NodeState[]): ChartPayload[] {
  if (nodes.length === 0) return [];
  const rows = nodes.map((n) => ({
    agent: n.name,
    status: n.status,
    duration_ms: n.durationMs ?? 0,
    ttft_ms: n.ttftMs ?? 0,
    input: n.tokenUsage?.input ?? 0,
    output: n.tokenUsage?.output ?? 0,
    total: n.tokenUsage?.total ?? 0,
    cost_usd: n.costUsd ?? 0,
    steps: n.toolCallCount ?? 0,
  }));
  return [{
    label: LABEL,
    title: "Run Overview",
    chart_type: "table",
    category: CATEGORY,
    data: rows,
    columns: ["agent", "status", "duration_ms", "ttft_ms", "input", "output", "total", "cost_usd", "steps"],
  }];
}

const summaryComputers: SummaryComputer[] = [
  tokensByAgent,
  durationByAgent,
  costByAgent,
  ttftByAgent,
  stepsByAgent,
  executionTimeline,
  runOverviewTable,
];

/** Compute summary charts and write them via the provided addChart function. */
export function computeRunSummary(
  nodes: NodeState[],
  addChart: AddChartFn,
): void {
  if (nodes.length === 0) return;
  for (const computer of summaryComputers) {
    for (const payload of computer(nodes)) addChart(payload);
  }
}
