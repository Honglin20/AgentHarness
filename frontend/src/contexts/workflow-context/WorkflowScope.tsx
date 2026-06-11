/**
 * WorkflowScope — pure DI container for per-workflow scoped stores.
 *
 * WS lifecycle lives in WorkflowCenterPanel (stable parent).
 * WorkflowScope just provides the scoped stores via WorkflowProvider.
 * WSMethodContext is a real React context — no window globals.
 *
 * Reset responsibility has been moved out of this component (see fix plan
 * 2026-05-30): reset now happens at data write entries:
 *   - live: routeEvent on `workflow.started` (with idempotent guard)
 *   - replay: replayEventsToStores entry calls resetAllStores
 * This eliminates the Bug A: refresh-then-history blank-panel regression
 * (the previous reset effect wiped data that replayEventsToStores had just
 * populated, before React handed control back to the renderer).
 */

"use client";

import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";
import { WorkflowProvider } from "./WorkflowContext";
import { getWorkflowManager } from "./WorkflowManager";
import { loadRunFromPersistedData } from "./replayEvents";
import { fetchWithAuth } from "@/lib/api";
import type { WSEvent } from "@/types/events";
import { useViewStore } from "@/stores/viewStore";

// ============================================================
// WSMethodContext — React context for WebSocket send methods
// ============================================================

interface WSMethods {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStructuredAnswer: (questionId: string, answer: { selected: string[]; customInput: string }) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
  sendGuidance: (guidance: string) => void;
  sendFollowup: (agentName: string, question: string) => void;
}

const WSMethodContext = createContext<WSMethods | null>(null);

export function WSMethodProvider({
  sendAnswer,
  sendStructuredAnswer,
  sendStopAndRegenerate,
  sendGuidance,
  sendFollowup,
  children,
}: WSMethods & { children: ReactNode }) {
  const value = useMemo(
    () => ({ sendAnswer, sendStructuredAnswer, sendStopAndRegenerate, sendGuidance, sendFollowup }),
    [sendAnswer, sendStructuredAnswer, sendStopAndRegenerate, sendGuidance, sendFollowup],
  );
  return (
    <WSMethodContext.Provider value={value}>
      {children}
    </WSMethodContext.Provider>
  );
}

export function useWSMethods(): WSMethods {
  const ctx = useContext(WSMethodContext);
  if (!ctx) {
    throw new Error(
      "useWSMethods must be used within WSMethodProvider. " +
      "Make sure WorkflowCenterPanel wraps the tree with WSMethodProvider."
    );
  }
  return ctx;
}

// ============================================================
// WorkflowScope
// ============================================================

interface WorkflowScopeProps {
  workflowId: string | null;
  children: ReactNode;
}

export function WorkflowScope({ workflowId, children }: WorkflowScopeProps) {
  const manager = useMemo(() => getWorkflowManager(), []);

  const stores = useMemo(() => {
    if (!workflowId) return null;
    return manager.getOrCreate(workflowId).stores;
  }, [manager, workflowId]);

  const setActiveWorkflowId = useMemo(
    () => (id: string | null) => manager.setActiveWorkflowId(id),
    [manager],
  );

  useEffect(() => {
    // Tell the manager which workflow is active for cross-cutting reads.
    // Reset responsibility lives at data write entries (see file header).
    manager.setActiveWorkflowId(workflowId);
  }, [manager, workflowId]);

  // ── REST pre-populate on page refresh ────────────────────────────────
  //
  // On full-page refresh, scoped stores are empty. This effect fetches
  // persisted run data via REST and populates stores so the UI is never
  // blank, even when the server event buffer has overflowed.
  //
  // Coordination with showReplay (sidebar click / URL restore):
  //   chartsLoading is a reactive dependency. When showReplay activates
  //   (sets chartsLoading = true), React's effect cleanup automatically
  //   cancels any in-flight fetch via the `cancelled` flag. The guard
  //   at the top also prevents new fetches from starting. This eliminates
  //   the race where both paths call resetAllStores() concurrently and
  //   one clears the other's populated data.
  const chartsLoading = useViewStore((s) => s.chartsLoading);
  const prepopulatedRef = useRef<string | null>(null);

  useEffect(() => {
    if (!workflowId || !stores) return;

    // Already pre-populated (showReplay / batch / prior WS cycle).
    if (prepopulatedRef.current === workflowId) return;
    if (stores.workflow.getState().dag) return;

    // showReplay owns hydration — do not race with it.
    if (chartsLoading) return;

    let cancelled = false;

    (async () => {
      try {
        const res = await fetchWithAuth(`/api/runs/${workflowId}`);
        if (!res.ok || cancelled) return;
        const run = await res.json();

        if (cancelled || stores.workflow.getState().dag) return;

        // Lazy-load charts / events / conversation if stored in sidecar files.
        let conv = run.conversation;
        let chartGroups = run.chart_groups;
        let eventsData: WSEvent[] | undefined;
        const needsConv = run._has_conversation && (!conv || conv.length === 0);

        if (run._has_charts || run._has_events || needsConv) {
          const [charts, events, convData] = await Promise.all([
            run._has_charts
              ? fetchWithAuth(`/api/runs/${workflowId}/charts`).then(async (r) => r.ok ? r.json() : null)
              : Promise.resolve(null),
            run._has_events
              ? fetchWithAuth(`/api/runs/${workflowId}/events`).then(async (r) => r.ok ? r.json() : null)
              : Promise.resolve(null),
            needsConv
              ? fetchWithAuth(`/api/runs/${workflowId}/conversation`).then(async (r) => r.ok ? r.json() : null)
              : Promise.resolve(null),
          ]);
          if (cancelled) return;
          chartGroups = charts ?? chartGroups;
          eventsData = events ?? undefined;
          conv = convData ?? conv;
        }

        const hasPersistedData = run.agent_io && conv && conv.length > 0 && run.dag && run.result?.trace;

        if (cancelled || stores.workflow.getState().dag) return;

        if (hasPersistedData) {
          loadRunFromPersistedData(workflowId, { ...run, chart_groups: chartGroups, conversation: conv }, eventsData);
        } else if (eventsData && eventsData.length > 0) {
          const { replayEventsToStores } = await import("./replayEvents");
          if (!cancelled) replayEventsToStores(workflowId, eventsData);
        }

        if (!cancelled) prepopulatedRef.current = workflowId;
      } catch (err) {
        // For completed runs there is no WS fallback — log so the blank
        // panel is traceable instead of silently swallowed.
        console.warn("[WorkflowScope] pre-populate failed for", workflowId, err);
      }
    })();

    return () => { cancelled = true; };
  }, [workflowId, stores, chartsLoading]);

  // Mark prepopulated when stores get data from an external source
  // (showReplay, WS events), so the pre-populate effect doesn't re-fire.
  useEffect(() => {
    if (!workflowId || !stores) return;
    if (stores.workflow.getState().dag && prepopulatedRef.current !== workflowId) {
      prepopulatedRef.current = workflowId;
    }
  }, [workflowId, stores]);

  if (!stores) {
    return (
      <WorkflowProvider
        workflowId={null}
        stores={null}
        setActiveWorkflowId={setActiveWorkflowId}
      >
        {children}
      </WorkflowProvider>
    );
  }

  return (
    <WorkflowProvider
      workflowId={workflowId}
      stores={stores}
      setActiveWorkflowId={setActiveWorkflowId}
    >
      {children}
    </WorkflowProvider>
  );
}
