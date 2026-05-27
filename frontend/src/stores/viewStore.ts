import { create } from "zustand";
import type { RunRecord } from "./runHistoryStore";
import { useAgentIOStore } from "./agentIOStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { replayEventsToStores, loadLegacyRunData } from "@/contexts/workflow-context/replayEvents";

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
    if ((run as any).events && (run as any).events.length > 0) {
      replayEventsToStores(run.run_id, (run as any).events);
    } else {
      loadLegacyRunData(run.run_id, run.conversation ?? [], run.chart_groups ?? null);
    }

    set({ activeView: { type: "replay", runId: run.run_id, run } });
  },
}));
