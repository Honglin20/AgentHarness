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
import { hydrateStores } from "@/stores/hydration/hydrateReplay";

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
    // Live run — populate global workflowStore so page.tsx detects the
    // workflowId and switches to run layout. Scoped workflow store gets
    // populated by hydrateStores below along with conversation/agents/etc.
    useWorkflowStore.getState().setWorkflow(
      runId,
      full.workflow_name,
      full.dag ?? null,
    );

    // Critical: run the hydration pipeline so scoped stores reflect prior
    // events / conversation / outline / charts. Without this, clicking a
    // running workflow shows an empty conversation because WS only pushes
    // new events — anything that happened before WS connect is invisible.
    // Not calling showReplay because that would flip activeView to replay
    // and clobber the live-mode UX (ConnectionStatusBar, ChatInput).
    await hydrateStores(full, seq, () => _activateSeq);
    if (seq !== _activateSeq) return;

    useAppViewStore.getState().setRunMode("live");
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
