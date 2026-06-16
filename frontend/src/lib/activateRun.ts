/**
 * activateRun — single entry point for activating a run.
 *
 * Used by both history click and URL restore. Replaces the split path
 * in RunHistoryList.handleClickRun that only filled the GLOBAL store on
 * the running branch (leaving scoped stores empty → ScopedCenterPanel
 * fell through to the portal view).
 *
 * Race-safety: a module-level `_activateSeq` (mirrors viewStore's
 * `_replaySeq` pattern) discards stale post-await writes when a newer
 * activateRun supersedes this one. The module-level AbortController
 * cancels the in-flight fetch.
 *
 * Hydration flag (`WorkflowEntry.hydration`) drives the run-page loading
 * skeleton instead of the old `chartsLoading` overload, so the UI never
 * mistakes "loading" for "user is on the portal page".
 */

import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { useAppViewStore } from "@/stores/appView";
import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import { hydrateStores, hydratePhase1 } from "@/stores/hydration/hydrateReplay";

let _activateSeq = 0;
let _abortController: AbortController | null = null;

/**
 * Activate a run by id.
 *
 * Always:
 *   1. getOrCreate the scoped WorkflowEntry (so WS events aren't dropped
 *      if WS connects before hydration completes — eventRouter.ts:79-82
 *      silently drops events for unknown workflow ids).
 *   2. Set hydration → "hydrating", view → run, runMode → "replay-skeleton".
 *   3. Fetch the full run record (aborting any prior in-flight fetch).
 *
 * Then per status:
 *   - running: populate global workflowStore (so layout detects workflowId),
 *     run hydrateStores to fill scoped stores from sidecars (events /
 *     conversation / agents / charts that WS won't replay), then set
 *     runMode "live" so WS connects for new events.
 *   - other:   call showReplay(full) which owns the hydration pipeline
 *     (resetAllStores → hydrateStores) AND switches activeView to replay.
 *
 * Hydration → "hydrated" is set AFTER hydrateStores resolves so the UI
 * doesn't enter the hydrated render branch with empty scoped stores
 * (which would flash empty conversation before sidecars land).
 *
 * All post-await state writes are guarded by the seq counter so a
 * superseding activateRun can't have its writes clobbered by a stale one.
 */
export async function activateRun(runId: string): Promise<void> {
  const seq = ++_activateSeq;
  const manager = getWorkflowManager();

  // Step 1 — sync state setup BEFORE any await.
  manager.getOrCreate(runId);
  manager.setHydration(runId, "hydrating");
  useAppViewStore.getState().setView({ kind: "run", runId });
  useAppViewStore.getState().setRunMode("replay-skeleton");

  // Step 2 — abort prior in-flight, start fresh fetch.
  _abortController?.abort();
  const ac = new AbortController();
  _abortController = ac;

  let full;
  try {
    full = await useRunHistoryStore.getState().fetchRun(runId, ac.signal);
  } catch {
    if (seq === _activateSeq) manager.setHydration(runId, "failed");
    return;
  }

  // Stale check — bail if a newer activateRun superseded us.
  if (seq !== _activateSeq) return;

  if (!full) {
    manager.setHydration(runId, "failed");
    return;
  }

  if (full.status === "running") {
    // Surgical fix for "history → running switch doesn't update middle panel":
    // activateRun was only updating useAppViewStore + global workflowStore,
    // leaving useViewStore.activeView pointing at the prior replay runId.
    // useActiveWorkflowId (WorkflowCenterPanel.tsx:35-50) prioritises
    // useViewStore, so WorkflowScope wrapped the wrong workflowId and all
    // scoped hooks kept reading history's stores. showLive() resets the
    // replay state (resetAllStores on the prior runId + activeView → live)
    // so the fallback `return workflowId` branch returns the running id.
    // See docs/plans/2026-06-16-nas-run-findings-and-arch-issues.md #5.
    useViewStore.getState().showLive();

    // Live run — populate global workflowStore so page.tsx detects the
    // workflowId and switches to run layout.
    useWorkflowStore.getState().setWorkflow(
      runId,
      full.workflow_name,
      full.dag ?? null,
    );

    // Phase 1 (await): minimal data for instant UI feedback — workflow
    // store + outline sidecar. Keeps setHydration("hydrated") latency
    // bounded to ~100ms.
    await hydratePhase1(full);
    if (seq !== _activateSeq) return;

    useAppViewStore.getState().setRunMode("live");

    // WS (sinceSeq=0) replays all buffered events into scoped stores on
    // connect — conversation / charts / agents / outline are rebuilt from
    // the live event stream. NO phase 2 hydrateStores call: its internal
    // resetAllStores would race the WS stream and wipe just-delivered
    // events (review finding: agent output appears, vanishes, reappears
    // as phase 2 lands). For paused-resume runs where sidecars exist on
    // disk, those same events are still in the Bus buffer and reach the
    // store via WS — no HTTP sidecar fetch needed.
    //
    // Not calling showReplay either — it would flip activeView to replay
    // and clobber the live-mode UX (ConnectionStatusBar, ChatInput).
  } else {
    // Completed / failed / etc — showReplay owns hydration pipeline.
    useViewStore.getState().showReplay(full);
    useAppViewStore.getState().setRunMode("replay");
  }

  if (seq === _activateSeq) {
    manager.setHydration(runId, "hydrated");
  }
}

/**
 * Reset module-level state. Used by tests; not exported through the
 * public surface otherwise.
 */
export function _resetActivateRunStateForTests(): void {
  _activateSeq = 0;
  _abortController?.abort();
  _abortController = null;
}
