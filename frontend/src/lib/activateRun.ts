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
import {
  hydrateStores,
  hydratePhase1,
  hydrateFromSnapshot,
  fetchSnapshot,
  hydrateOutlineSidecar,
} from "@/stores/hydration/hydrateReplay";
import { setHydratedCursor } from "@/contexts/workflow-context/routing";

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

    // Long-run replay Phase 1: fetch snapshot for O(1) hydrate.
    // If snapshot exists, hydrate scoped stores in a single pass and set
    // the WS since_seq cursor so the live WS stream only delivers events
    // after seq_cursor — no full-buffer replay on refresh.
    // Fallback (snapshot absent / fetch failed / stale): legacy path
    // (hydratePhase1 + WS subscribe(0) full replay). Old runs without
    // snapshot sidecar hit this branch.
    // See docs/plans/2026-06-16-long-run-replay-architecture.md.
    const snapshot = await fetchSnapshot(runId, ac.signal);
    if (seq !== _activateSeq) return;

    if (snapshot && typeof snapshot.seq_cursor === "number") {
      // Snapshot path — single-pass hydrate.
      hydrateFromSnapshot(snapshot);

      // Tell dedup.ts to skip any WS event with seq ≤ cursor (defensive —
      // since_seq=cursor should already prevent them, but late subscribers
      // racing the WS reconnect can see them).
      setHydratedCursor(runId, snapshot.seq_cursor);

      // WS connects with since_seq=cursor — only receives post-snapshot
      // events. useAppViewStore.wsSinceSeq is read by useWorkflowWS.
      useAppViewStore.getState().setWsSinceSeq(snapshot.seq_cursor);

      // hydrateFromSnapshot doesn't touch the outline store — fetch the
      // outline sidecar separately so the sidebar renders immediately
      // (sidecar is fresh-written by _save_incremental on each node
      // completion; before Fix 1 it only existed after final-save, which
      // never fired for interrupted runs). Best-effort: fetchRunOutline
      // returns null on 404, useAgentOutline falls back to deriveOutlineItems.
      // Fire-and-forget — seq guard above already protected pre-await writes;
      // a stale post-await write would land on a newer run's scoped store,
      // but hydrateOutlineSidecar fetches by runId (no scope capture), and
      // getOrCreate is a no-op if the entry already exists.
      void hydrateOutlineSidecar(runId);
    } else {
      // Legacy path — full WS replay from seq=0. Clear any stale cursor
      // from a prior run so dedup doesn't accidentally drop live events.
      setHydratedCursor(runId, null);
      useAppViewStore.getState().setWsSinceSeq(0);
      await hydratePhase1(full);
      if (seq !== _activateSeq) return;
    }

    useAppViewStore.getState().setRunMode("live");

    // WS now connects with the right since_seq (0 for legacy / cursor for
    // snapshot path). All live events flow through routing/routeEvent,
    // which dedups via isDuplicate (honors hydrated cursor).
    //
    // NO phase 2 hydrateStores call: its internal resetAllStores would
    // race the WS stream and wipe just-delivered events. For paused-resume
    // runs where sidecars exist on disk, those same events are still in
    // the Bus buffer and reach the store via WS — no HTTP sidecar fetch
    // needed.
    //
    // Not calling showReplay either — it would flip activeView to replay
    // and clobber the live-mode UX (ConnectionStatusBar, ChatInput).
  } else {
    // Completed / failed / etc — showReplay owns hydration pipeline.
    // Clear the WS cursor (replay doesn't use WS) + hydration watermark
    // so a later switch back to a running workflow starts clean.
    useAppViewStore.getState().setWsSinceSeq(0);
    setHydratedCursor(runId, null);
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
