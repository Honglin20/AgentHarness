import { create } from "zustand";
import type { RunRecord } from "./runHistoryStore";
import type { WSEvent } from "@/types/events";
import { useAgentIOStore } from "./agentIOStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { replayEventsToStores, loadLegacyRunData } from "@/contexts/workflow-context/replayEvents";
import { computeRunSummary } from "@/lib/summary/runSummary";

export type ActiveView =
  | { type: "live" }
  | { type: "replay"; runId: string; run: RunRecord };

interface ViewState {
  activeView: ActiveView;
  showLive: () => void;
  showReplay: (run: RunRecord) => void;
}

export const useViewStore = create<ViewState>()((set) => ({
  activeView: { type: "live" },
  showLive: () => set({ activeView: { type: "live" } }),
  showReplay: (run) => {
    // Populate agentIOStore from persisted run data (backward compat)
    if (run.agent_io) {
      const store = useAgentIOStore.getState();
      for (const [nodeId, io] of Object.entries(run.agent_io)) {
        store.setAgentIO(nodeId, io.input_prompt ?? "", io.output_result, io.system_prompt);
      }
    }

    // Ensure scoped stores exist for this workflow
    const manager = getWorkflowManager();
    manager.getOrCreate(run.run_id);

    // New path: replay events into scoped stores
    // Backward compat: load legacy data directly
    if (run.events && run.events.length > 0) {
      replayEventsToStores(run.run_id, run.events as WSEvent[]);
    } else {
      loadLegacyRunData(
        run.run_id,
        run.conversation ?? [],
        run.chart_groups ?? null,
        run.dag,
        run.workflow_name,
        run.result,
      );
    }

    // Safety net: ensure DAG and status are set even if events lacked workflow.started
    const stores = manager.getStores(run.run_id);
    if (stores) {
      const wfState = stores.workflow.getState();
      if (!wfState.dag && run.dag) {
        wfState.handleWorkflowStarted({
          workflow_id: run.run_id,
          name: run.workflow_name,
          dag: run.dag,
          inputs: run.inputs,
        });
      }
      if (wfState.status === "idle") {
        wfState.handleWorkflowCompleted({
          workflow_id: run.run_id,
          status: run.status === "failed" ? "failed" : "completed",
        });
      }
      // Compute summary if charts are empty but we have nodes
      const chartState = stores.chart.getState();
      const hasAnalysis = chartState.groupOrder.some(
        (label) => chartState.groups[label]?.category === "analysis"
      );
      if (!hasAnalysis && Object.keys(wfState.nodes).length > 0) {
        const summaryNodes = Object.values(wfState.nodes);
        const addChart = chartState.addChart;
        computeRunSummary(summaryNodes, addChart, stores.span);
      }
    }

    set({ activeView: { type: "replay", runId: run.run_id, run } });
  },
}));
