/**
 * AppView ↔ URL serialization.
 *
 * Single source of truth for how the AppView discriminated union maps
 * to URL query params. Pure functions — no side effects, no globals —
 * so they're trivially testable.
 *
 * URL shape (mutually exclusive `view` param):
 *   ?view=portal                                  → portal-home
 *   ?view=workflows&domain=X                      → workflows
 *   ?view=tutorial&domain=X&tutorial=T            → tutorial
 *   ?view=api-doc&domain=X&api=A                  → api-doc
 *   ?view=template&wf=Y[&domain=X]                → template-preview
 *   ?view=run&id=R                                → run
 *   ?view=bench&bench=B[&task=T]                  → benchmark
 *   (empty)                                       → portal-home
 *
 * Legacy migration (parse-time, one-shot replaceState by caller):
 *   ?wid=R(&wf=...)                               → run, id=R
 *   ?bench=B(&task=T)                             → benchmark, benchId=B
 *
 * `tab` is orthogonal (per-view UI state) and intentionally NOT
 * round-tripped by these functions — it's handled by syncTabToUrl /
 * readTabFromUrl below.
 */

import type { AppView } from "@/stores/appView";

export const APP_VIEW_PARAM = "view";

/**
 * Parse URL search params into an AppView.
 *
 * Recognizes both the new `?view=...` shape and legacy `?wid=` / `?bench=`
 * shapes. Returns `{ view, migratedFromLegacy }` so the caller can do a
 * one-shot `replaceState` to clean up the URL when legacy params were
 * consumed — keeps user bookmarks working without permanently polluting
 * the URL with mixed-shape params.
 */
export function parseUrlToAppView(
  params: URLSearchParams,
): { view: AppView; migratedFromLegacy: boolean } {
  // Legacy shape: ?wid=R(&wf=...)
  const wid = params.get("wid");
  if (wid) {
    return {
      view: { kind: "run", runId: wid },
      migratedFromLegacy: true,
    };
  }

  // Legacy shape: ?bench=B(&task=T)
  const legacyBench = params.get("bench");
  const legacyTask = params.get("task");
  if (legacyBench) {
    return {
      view: {
        kind: "benchmark",
        benchId: legacyBench,
        taskId: legacyTask ?? undefined,
      },
      migratedFromLegacy: true,
    };
  }

  // New shape: ?view=...
  const view = params.get(APP_VIEW_PARAM);
  const domain = params.get("domain") ?? "";

  switch (view) {
    case "portal":
      return { view: { kind: "portal-home" }, migratedFromLegacy: false };

    case "workflows":
      if (!domain) return { view: { kind: "portal-home" }, migratedFromLegacy: false };
      return {
        view: { kind: "workflows", domainId: domain },
        migratedFromLegacy: false,
      };

    case "tutorial": {
      const tutorial = params.get("tutorial");
      if (!domain || !tutorial) {
        return { view: { kind: "portal-home" }, migratedFromLegacy: false };
      }
      return {
        view: { kind: "tutorial", domainId: domain, tutorialId: tutorial },
        migratedFromLegacy: false,
      };
    }

    case "api-doc": {
      const api = params.get("api");
      if (!domain || !api) {
        return { view: { kind: "portal-home" }, migratedFromLegacy: false };
      }
      return {
        view: { kind: "api-doc", domainId: domain, apiName: api },
        migratedFromLegacy: false,
      };
    }

    case "template": {
      const wf = params.get("wf");
      if (!wf) return { view: { kind: "portal-home" }, migratedFromLegacy: false };
      return {
        view: {
          kind: "template-preview",
          workflowName: wf,
          domainId: domain || undefined,
        },
        migratedFromLegacy: false,
      };
    }

    case "run": {
      const id = params.get("id");
      if (!id) return { view: { kind: "portal-home" }, migratedFromLegacy: false };
      return {
        view: { kind: "run", runId: id },
        migratedFromLegacy: false,
      };
    }

    case "bench": {
      const bench = params.get("bench");
      const task = params.get("task");
      if (!bench) return { view: { kind: "portal-home" }, migratedFromLegacy: false };
      return {
        view: { kind: "benchmark", benchId: bench, taskId: task ?? undefined },
        migratedFromLegacy: false,
      };
    }

    default:
      // No view param (or unrecognized) → portal home.
      return { view: { kind: "portal-home" }, migratedFromLegacy: false };
  }
}

/**
 * Serialize an AppView into URL search params.
 *
 * Returns a fresh URLSearchParams — caller decides whether to merge
 * with the current URL (e.g., to preserve `tab`) or use as-is.
 */
export function appViewToUrlParams(view: AppView): URLSearchParams {
  const params = new URLSearchParams();
  switch (view.kind) {
    case "portal-home":
      // Empty params = portal home. Drop the explicit ?view=portal to
      // keep the URL minimal on the default landing.
      break;
    case "workflows":
      params.set(APP_VIEW_PARAM, "workflows");
      params.set("domain", view.domainId);
      break;
    case "tutorial":
      params.set(APP_VIEW_PARAM, "tutorial");
      params.set("domain", view.domainId);
      params.set("tutorial", view.tutorialId);
      break;
    case "api-doc":
      params.set(APP_VIEW_PARAM, "api-doc");
      params.set("domain", view.domainId);
      params.set("api", view.apiName);
      break;
    case "template-preview":
      params.set(APP_VIEW_PARAM, "template");
      params.set("wf", view.workflowName);
      if (view.domainId) params.set("domain", view.domainId);
      break;
    case "run":
      params.set(APP_VIEW_PARAM, "run");
      params.set("id", view.runId);
      break;
    case "benchmark":
      params.set(APP_VIEW_PARAM, "bench");
      params.set("bench", view.benchId);
      if (view.taskId) params.set("task", view.taskId);
      break;
  }
  return params;
}

/**
 * Serialize AppView to a query string (e.g., `?view=run&id=R`).
 * Empty string for portal-home.
 */
export function appViewToSearch(view: AppView): string {
  const params = appViewToUrlParams(view);
  const qs = params.toString();
  return qs ? `?${qs}` : "";
}

// ── Orthogonal tab state helpers ──────────────────────────────────────
//
// `tab` is per-view UI state (conversation / results / analysis). It
// travels in the URL independently of AppView so a refresh preserves
// the active tab without crowding AppView itself.

export function readTabFromUrl(): string | undefined {
  if (typeof window === "undefined") return undefined;
  return new URLSearchParams(window.location.search).get("tab") ?? undefined;
}

export function syncTabToUrl(tab: string): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  url.searchParams.set("tab", tab);
  window.history.replaceState({}, "", url.pathname + url.search);
}
