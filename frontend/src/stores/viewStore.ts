import { create } from "zustand";
import type { RunRecord } from "./runHistoryStore";
import { useAgentIOStore } from "./agentIOStore";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { resetAllStores } from "@/contexts/workflow-context/routing/utils";
import { useOutlineStore } from "@/components/outline/outlineStore";
import {
  hydrateStores,
} from "./hydration/hydrateReplay";

let _replaySeq = 0;

/**
 * The currently-active center panel view.
 *
 * Three variants — kept as a discriminated union so consumers must narrow
 * before accessing run-specific fields. Previously `beginReplay` produced
 * a partial `{ run_id, workflow_name } as RunRecord` which lied to the
 * type system; the skeleton variant makes that "we know the run id and
 * name but not the full record yet" state explicit and type-safe.
 */
export type ActiveView =
  | { type: "live" }
  | {
      type: "replay-skeleton";
      runId: string;
      /** Workflow name from the sidebar entry — enough for header / breadcrumb rendering. */
      workflowName: string;
    }
  | { type: "replay"; runId: string; run: RunRecord };

/** True for both skeleton and full replay — anything that isn't "live". */
type ReplayView = Extract<ActiveView, { runId: string }>;
export function isReplayView(view: ActiveView): view is ReplayView {
  return view.type === "replay" || view.type === "replay-skeleton";
}

/** The run id when replaying (skeleton or full), else null. */
export function getActiveRunId(view: ActiveView): string | null {
  return view.type === "live" ? null : view.runId;
}

/**
 * Workflow name when replaying. Skeleton has it directly; full replay
 * reads from the run record. Returns null for live view.
 */
export function getActiveWorkflowName(view: ActiveView): string | null {
  if (view.type === "live") return null;
  if (view.type === "replay-skeleton") return view.workflowName;
  return view.run.workflow_name;
}

/**
 * The full RunRecord, only available after `showReplay` has hydrated.
 * Returns null for skeleton and live. Use this when the consumer needs
 * `agents_snapshot` / `result` / `dag` / etc — those fields don't exist
 * on the skeleton.
 */
export function getActiveRun(view: ActiveView): RunRecord | null {
  return view.type === "replay" ? view.run : null;
}

interface ViewState {
  activeView: ActiveView;
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
  showLive: () => {
    const current = get().activeView;
    if (isReplayView(current)) {
      const manager = getWorkflowManager();
      const scoped = manager.getOrCreate(current.runId);
      resetAllStores(scoped.stores);
      // Reset outline selection (but preserve viewMode preference).
      useOutlineStore.getState().reset();
    }
    set({ activeView: { type: "live" } });
  },
  beginReplay: (runId, workflowName) => set({
    // Skeleton view — we know the run id and workflow name (from the
    // sidebar entry) but haven't fetched the full record yet. The UI
    // renders a loading skeleton while showReplay hydrates.
    activeView: { type: "replay-skeleton", runId, workflowName },
  }),
  showReplay: (run) => {
    const seq = ++_replaySeq;

    // Clear stale global agentIO data from previous runs
    useAgentIOStore.getState().reset();

    // Ensure scoped stores exist for this workflow, then RESET them
    // synchronously BEFORE the UI switches. Without this, the previous
    // run's conversation/workflow/etc data leaks into the new run during
    // the async hydration window (hydrateStores runs after the set()
    // below). P0-A fix.
    const manager = getWorkflowManager();
    const scoped = manager.getOrCreate(run.run_id);
    resetAllStores(scoped.stores);

    // Reset outline selection (but preserve viewMode preference) so the
    // previous run's selected agent doesn't bleed into the new run.
    useOutlineStore.getState().reset();

    // Promote skeleton → full replay immediately. The UI switches off the
    // skeleton placeholder as soon as the run record is in hand; lazy
    // sidecar hydration continues in the background and the final
    // setState (with merged data) lands when it completes.
    set({
      activeView: { type: "replay", runId: run.run_id, run },
    });

    // Hydration pipeline (see stores/hydration/hydrateReplay.ts):
    //   loadSidecars → decideStrategy → applyHydration
    // The seq guard discards stale results if a newer showReplay call
    // supersedes this one.
    hydrateStores(run, seq, () => _replaySeq).then((merged) => {
      if (seq !== _replaySeq) return;
      if (merged !== run) {
        set({
          activeView: { type: "replay", runId: run.run_id, run: merged },
        });
      }
    });
  },
}));
