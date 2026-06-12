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
  setView: (view: AppView) => void;
  setRunMode: (mode: RunMode) => void;
}

export const useAppViewStore = create<AppViewState>((set) => ({
  view: { kind: "portal-home" },
  runMode: "live",
  setView: (view) =>
    set((s) =>
      s.view === view
        ? s
        : {
            view,
            // Reset runMode when leaving the run view; entering callers
            // (activateRun, useWorkflowLaunch) set the appropriate mode
            // explicitly.
            runMode:
              view.kind === "run" ? s.runMode : ("live" as RunMode),
          }
    ),
  setRunMode: (runMode) => set({ runMode }),
}));
