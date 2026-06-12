/**
 * useAppViewUrlSync — single URL ↔ appViewStore sync point.
 *
 * Replaces both `useUrlState` (replaceState, params run/wid/wf/bench/task)
 * and `portalStore.syncUrl` (pushState, params view/domain/tutorial/api).
 * Those two competing systems caused the URL to carry mixed portal+run
 * params after navigating portal → run, which made refresh ambiguous.
 *
 * Responsibilities:
 *   1. Mount: parse URL → setView. If URL was legacy (?wid= / ?bench=),
 *      replaceState once to the new shape so the address bar is clean.
 *   2. Subscribe to appViewStore changes → serialize → replaceState.
 *      (replaceState, not pushState — URL reflects "current state", not
 *      a history stack. Forward/back is handled by popstate below.)
 *   3. popstate listener (browser back/forward) → parse URL → setView
 *      silently (no URL rewrite — popstate already came from URL change).
 *
 * Loop prevention: the `silent` flag suppresses the subscribe-side URL
 * write when setView was triggered by popstate or initial mount.
 *
 * Orthogonal state:
 *   - `tab` (conversation/results/analysis) is per-view UI state handled
 *     by syncTabToUrl / readTabFromUrl in appViewUrl.ts.
 */

"use client";

import { useEffect, useRef } from "react";
import { useAppViewStore } from "@/stores/appView";
import {
  parseUrlToAppView,
  appViewToUrlParams,
  APP_VIEW_PARAM,
} from "@/lib/appViewUrl";

// Keys that this hook owns. `tab` is intentionally NOT here — it's
// managed separately so it doesn't get clobbered when AppView changes.
const APPVIEW_OWNED_KEYS = [
  APP_VIEW_PARAM,
  "domain",
  "tutorial",
  "api",
  "wf",
  "id",
  "run", // legacy
  "wid", // legacy (consumed by parse, never re-emitted)
  "bench",
  "task",
] as const;

function buildUrlString(appViewParams: URLSearchParams): string {
  if (typeof window === "undefined") return "/";
  // Merge: take current URL, drop AppView-owned keys, copy new ones.
  // Preserves `tab` and any future orthogonal params.
  const current = new URLSearchParams(window.location.search);
  for (const key of APPVIEW_OWNED_KEYS) {
    current.delete(key);
  }
  for (const [key, value] of Array.from(appViewParams.entries())) {
    current.set(key, value);
  }
  const qs = current.toString();
  return qs ? `${window.location.pathname}?${qs}` : window.location.pathname;
}

export function useAppViewUrlSync(): void {
  // Silent flag — when true, appViewStore changes do NOT trigger a URL
  // rewrite. Set during initial mount restore and popstate handling.
  const silentRef = useRef(false);

  // Mount: parse URL → setView. Runs once.
  useEffect(() => {
    if (typeof window === "undefined") return;

    const params = new URLSearchParams(window.location.search);
    const { view, migratedFromLegacy } = parseUrlToAppView(params);

    // If we consumed legacy params, clean up the address bar with a
    // one-shot replaceState to the canonical shape. User bookmarks keep
    // working without permanently polluting the URL.
    if (migratedFromLegacy) {
      const newUrl = buildUrlString(appViewToUrlParams(view));
      window.history.replaceState({}, "", newUrl);
    }

    silentRef.current = true;
    useAppViewStore.getState().setView(view);
    silentRef.current = false;

    return () => {};
  }, []);

  // Subscribe: appViewStore → URL (replaceState).
  useEffect(() => {
    const unsub = useAppViewStore.subscribe((state) => {
      if (silentRef.current) return;
      if (typeof window === "undefined") return;
      const newUrl = buildUrlString(appViewToUrlParams(state.view));
      window.history.replaceState({}, "", newUrl);
    });
    return () => unsub();
  }, []);

  // popstate: browser back/forward → parse URL → setView (silent).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const onPopState = () => {
      const params = new URLSearchParams(window.location.search);
      const { view, migratedFromLegacy } = parseUrlToAppView(params);
      // Even on popstate, if the URL is legacy (e.g. user bookmark-loaded
      // then navigated), clean it up.
      if (migratedFromLegacy) {
        const newUrl = buildUrlString(appViewToUrlParams(view));
        window.history.replaceState({}, "", newUrl);
      }
      silentRef.current = true;
      useAppViewStore.getState().setView(view);
      silentRef.current = false;
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);
}
