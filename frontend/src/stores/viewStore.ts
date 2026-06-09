import { create } from "zustand";
import type { RunRecord } from "./runHistoryStore";
import type { WSEvent } from "@/types/events";
import { useAgentIOStore } from "./agentIOStore";
import { useRunHistoryStore } from "./runHistoryStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { replayEventsToStores, loadLegacyRunData, loadRunFromPersistedData } from "@/contexts/workflow-context/replayEvents";

let _replaySeq = 0;

export type ActiveView =
  | { type: "live" }
  | { type: "replay"; runId: string; run: RunRecord };

interface ViewState {
  activeView: ActiveView;
  /** True while a replay view is being hydrated (lazy fetch + store fill).
   *  Consumed by ScopedCenterPanel to render a skeleton instead of stale
   *  content from the previous run. The name is historical — it covers all
   *  hydration, not just charts. */
  chartsLoading: boolean;
  showLive: () => void;
  /** Switch to a replay view immediately with a minimal run record. UI will
   *  render a skeleton while the caller fetches the full record and invokes
   *  showReplay. Use this from sidebar handlers to avoid the "previous run
   *  stays visible" feeling during fetch. */
  beginReplay: (runId: string, workflowName: string) => void;
  showReplay: (run: RunRecord) => void;
}

export const useViewStore = create<ViewState>()((set, get) => ({
  activeView: { type: "live" },
  chartsLoading: false,
  showLive: () => set({ activeView: { type: "live" } }),
  beginReplay: (runId, workflowName) => set({
    // Minimal run record — only the fields the UI needs to render header /
    // breadcrumb. Full record arrives via showReplay after fetchRun.
    activeView: {
      type: "replay",
      runId,
      run: { run_id: runId, workflow_name: workflowName } as RunRecord,
    },
    chartsLoading: true,
  }),
  showReplay: (run) => {
    const seq = ++_replaySeq;

    // Clear stale global agentIO data from previous runs
    useAgentIOStore.getState().reset();

    // Ensure scoped stores exist for this workflow
    const manager = getWorkflowManager();
    manager.getOrCreate(run.run_id);

    // Switch active view immediately if caller hasn't already (e.g. URL
    // direct open). If beginReplay was called first, activeView is already
    // on this run and we just bump chartsLoading to keep skeleton showing.
    const current = get().activeView;
    if (current.type !== "replay" || current.runId !== run.run_id) {
      set({
        activeView: { type: "replay", runId: run.run_id, run },
        chartsLoading: true,
      });
    } else {
      set({ chartsLoading: true });
    }

    const doReplay = (
      chartGroups: RunRecord["chart_groups"],
      eventsData: RunRecord["events"],
      conversationData: RunRecord["conversation"] | null,
    ) => {
      if (seq !== _replaySeq) return;
      const wsEvents = eventsData as WSEvent[] | undefined;
      const conv = conversationData ?? run.conversation ?? [];
      // PRIMARY: direct data restoration (not affected by buffer overflow)
      const hasPersistedData = run.agent_io && conv && run.dag && run.result?.trace;
      const merged = { ...run, chart_groups: chartGroups, conversation: conv };
      if (hasPersistedData) {
        loadRunFromPersistedData(run.run_id, merged, wsEvents);
      }
      // FALLBACK 1: event replay (runs with events but incomplete data)
      else if (wsEvents && wsEvents.length > 0) {
        replayEventsToStores(run.run_id, wsEvents);
      }
      // FALLBACK 2: legacy runs without events
      else {
        loadLegacyRunData(
          run.run_id,
          conv,
          chartGroups,
          run.dag,
          run.workflow_name,
          run.result,
        );
      }
      set({
        activeView: { type: "replay", runId: run.run_id, run: { ...merged, events: eventsData ?? undefined } },
        chartsLoading: false,
      });
    };

    // Load charts/events/conversation lazily if sidecar data exists.
    // Conversation was split out of the main /runs/{id} response to keep
    // switching snappy on long workflows — see server/_helpers.py.
    const needsLazyLoadCharts = (run._has_charts || run._has_events) && !run.chart_groups && !run.events;
    const needsLazyLoadConv = run._has_conversation && (!run.conversation || run.conversation.length === 0);
    if (needsLazyLoadCharts || needsLazyLoadConv) {
      const store = useRunHistoryStore.getState();
      Promise.all([
        needsLazyLoadCharts && run._has_charts ? store.fetchRunCharts(run.run_id) : Promise.resolve(run.chart_groups ?? null),
        needsLazyLoadCharts && run._has_events ? store.fetchRunEvents(run.run_id) : Promise.resolve(run.events ?? null),
        needsLazyLoadConv ? store.fetchRunConversation(run.run_id) : Promise.resolve(run.conversation ?? null),
      ]).then(([charts, events, conv]) => {
        if (seq !== _replaySeq) return;
        doReplay(charts, events ?? undefined, conv);
      }).catch(() => {
        if (seq !== _replaySeq) return;
        doReplay(null, undefined, null);
      });
    } else {
      doReplay(run.chart_groups ?? null, run.events ?? undefined as RunRecord["events"], run.conversation ?? null);
    }
  },
}));
