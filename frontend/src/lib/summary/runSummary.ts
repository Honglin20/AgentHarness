import { useChartStore } from "@/stores/chartStore";
import { useWorkflowStore, type NodeState } from "@/stores/workflowStore";
import type { ChartPayload } from "@/types/events";

const LABEL = "Run Summary";

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
    data,
    columns: ["agent", "duration_ms"],
    x: "agent",
    y: "duration_ms",
  }];
}

function runOverviewTable(nodes: NodeState[]): ChartPayload[] {
  if (nodes.length === 0) return [];
  const rows = nodes.map((n) => ({
    agent: n.name,
    status: n.status,
    duration_ms: n.durationMs ?? 0,
    input: n.tokenUsage?.input ?? 0,
    output: n.tokenUsage?.output ?? 0,
    total: n.tokenUsage?.total ?? 0,
  }));
  return [{
    label: LABEL,
    title: "Run Overview",
    chart_type: "table",
    data: rows,
    columns: ["agent", "status", "duration_ms", "input", "output", "total"],
  }];
}

const summaryComputers: SummaryComputer[] = [
  tokensByAgent,
  durationByAgent,
  runOverviewTable,
];

export function computeRunSummary(): void {
  const nodes = Object.values(useWorkflowStore.getState().nodes);
  if (nodes.length === 0) return;
  const addChart = useChartStore.getState().addChart;
  for (const computer of summaryComputers) {
    for (const payload of computer(nodes)) addChart(payload);
  }
}
