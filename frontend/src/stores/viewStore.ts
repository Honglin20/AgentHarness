import { create } from "zustand";
import type { RunRecord } from "./runHistoryStore";
import type { WSEvent } from "@/types/events";
import { useAgentIOStore } from "./agentIOStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { replayEventsToStores, loadLegacyRunData, loadRunFromPersistedData } from "@/contexts/workflow-context/replayEvents";

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
    // Populate global agentIOStore from persisted run data (backward compat)
    if (run.agent_io) {
      const store = useAgentIOStore.getState();
      for (const [nodeId, io] of Object.entries(run.agent_io)) {
        store.setAgentIO(nodeId, io.input_prompt ?? "", io.output_result, io.system_prompt);
      }
    }

    // Ensure scoped stores exist for this workflow
    const manager = getWorkflowManager();
    manager.getOrCreate(run.run_id);

    // PRIMARY: direct data restoration (not affected by buffer overflow)
    const hasPersistedData = run.agent_io && run.conversation && run.dag && run.result?.trace;
    if (hasPersistedData) {
      loadRunFromPersistedData(run.run_id, run, run.events as WSEvent[] | undefined);
    }
    // FALLBACK 1: event replay (runs with events but incomplete data)
    else if (run.events && run.events.length > 0) {
      replayEventsToStores(run.run_id, run.events as WSEvent[]);
    }
    // FALLBACK 2: legacy runs without events
    else {
      loadLegacyRunData(
        run.run_id,
        run.conversation ?? [],
        run.chart_groups ?? null,
        run.dag,
        run.workflow_name,
        run.result,
      );
    }

    set({ activeView: { type: "replay", runId: run.run_id, run } });
  },
}));
