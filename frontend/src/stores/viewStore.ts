import { create } from "zustand";
import type { RunRecord } from "./runHistoryStore";
import type { WSEvent } from "@/types/events";
import { useAgentIOStore } from "./agentIOStore";
import { useRunHistoryStore } from "./runHistoryStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { replayEventsToStores, loadLegacyRunData, loadRunFromPersistedData } from "@/contexts/workflow-context/replayEvents";

export type ActiveView =
  | { type: "live" }
  | { type: "replay"; runId: string; run: RunRecord };

interface ViewState {
  activeView: ActiveView;
  chartsLoading: boolean;
  showLive: () => void;
  showReplay: (run: RunRecord) => void;
}

export const useViewStore = create<ViewState>()((set, get) => ({
  activeView: { type: "live" },
  chartsLoading: false,
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

    const doReplay = (chartGroups: RunRecord["chart_groups"], eventsData: RunRecord["events"]) => {
      const wsEvents = eventsData as WSEvent[] | undefined;
      // PRIMARY: direct data restoration (not affected by buffer overflow)
      const hasPersistedData = run.agent_io && run.conversation && run.dag && run.result?.trace;
      if (hasPersistedData) {
        loadRunFromPersistedData(run.run_id, { ...run, chart_groups: chartGroups }, wsEvents);
      }
      // FALLBACK 1: event replay (runs with events but incomplete data)
      else if (wsEvents && wsEvents.length > 0) {
        replayEventsToStores(run.run_id, wsEvents);
      }
      // FALLBACK 2: legacy runs without events
      else {
        loadLegacyRunData(
          run.run_id,
          run.conversation ?? [],
          chartGroups,
          run.dag,
          run.workflow_name,
          run.result,
        );
      }
      set({
        activeView: { type: "replay", runId: run.run_id, run: { ...run, chart_groups: chartGroups, events: eventsData ?? undefined } },
        chartsLoading: false,
      });
    };

    // Load charts/events lazily if sidecar data exists
    const needsLazyLoad = (run._has_charts || run._has_events) && !run.chart_groups && !run.events;
    if (needsLazyLoad) {
      set({ chartsLoading: true });
      const store = useRunHistoryStore.getState();
      Promise.all([
        run._has_charts ? store.fetchRunCharts(run.run_id) : Promise.resolve(null),
        run._has_events ? store.fetchRunEvents(run.run_id) : Promise.resolve(null),
      ]).then(([charts, events]) => {
        doReplay(charts, events ?? undefined);
      }).catch(() => {
        doReplay(null, undefined);
      });
    } else {
      doReplay(run.chart_groups ?? null, run.events ?? undefined as RunRecord["events"]);
    }
  },
}));
