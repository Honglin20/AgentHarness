/**
 * AppView — URL-derived "which page am I on" state.
 *
 * Single source of truth for page routing. Replaces the implicit
 * portal/run/template distinction that was previously inferred from
 * workflowStore + selectedTemplate + activeView, which conflated
 * "user is on the portal page" with "scoped store is briefly empty
 * during hydration" (the root cause of the refresh-returns-to-portal
 * bug).
 *
 * `view` is the URL-derived page kind. `runMode` is a runtime sub-state
 * that is ONLY meaningful when `view.kind === "run"` — it controls WS
 * connect/disconnect and which hydration path activateRun took.
 */

import { create } from "zustand";

export type AppView =
  | { kind: "portal-home" }
  | { kind: "workflows"; domainId: string }
  | { kind: "tutorial"; domainId: string; tutorialId: string }
  | { kind: "api-doc"; domainId: string; apiName: string }
  | { kind: "template-preview"; workflowName: string; domainId?: string }
  | { kind: "run"; runId: string }
  | { kind: "benchmark"; benchId: string; taskId?: string };

/**
 * Run-mode sub-state. Only meaningful when `view.kind === "run"`.
 *
 * - "live"           — actively running workflow, WS connected
 * - "replay-skeleton" — runId known, full record fetch in flight
 * - "replay"          — full run record loaded, hydration pipeline complete
 */
export type RunMode = "live" | "replay-skeleton" | "replay";

interface AppViewState {
  view: AppView;
  runMode: RunMode;
  /**
   * WS since_seq cursor for the currently-active run.
   *
   * - 0 (default): subscribe replays the entire bus buffer (legacy behavior)
   * - >0: subscribe only fetches events with seq > cursor (snapshot-hydrated)
   *
   * Set by activateRun after a successful snapshot hydrate, so the live WS
   * stream doesn't re-deliver events already reflected in the snapshot.
   * Reset to 0 whenever the active run changes (so a stale cursor from a
   * prior run doesn't accidentally clip the new run's replay).
   *
   * See docs/plans/2026-06-16-long-run-replay-architecture.md Phase 1.
   */
  wsSinceSeq: number;
  setView: (view: AppView) => void;
  setRunMode: (mode: RunMode) => void;
  setWsSinceSeq: (seq: number) => void;
}

export const useAppViewStore = create<AppViewState>((set) => ({
  view: { kind: "portal-home" },
  runMode: "live",
  wsSinceSeq: 0,
  setView: (view) =>
    set((s) =>
      s.view === view
        ? s
        : {
            view,
            // Reset runMode + wsSinceSeq when leaving the run view; entering
            // callers (activateRun, useWorkflowLaunch) set them explicitly.
            runMode:
              view.kind === "run" ? s.runMode : ("live" as RunMode),
            // Reset cursor on view change so a stale cursor from a prior run
            // doesn't clip the new run's WS replay. activateRun sets the
            // correct cursor after snapshot hydrate succeeds.
            wsSinceSeq: view.kind === "run" ? s.wsSinceSeq : 0,
          }
    ),
  setRunMode: (runMode) => set({ runMode }),
  setWsSinceSeq: (wsSinceSeq) =>
    set({ wsSinceSeq: Number.isFinite(wsSinceSeq) && wsSinceSeq > 0 ? wsSinceSeq : 0 }),
}));
