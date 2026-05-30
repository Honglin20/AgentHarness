/**
 * WorkflowScope - Context Provider wrapper
 *
 * WS lifecycle lives in WorkflowCenterPanel (stable parent).
 * WorkflowScope just provides per-workflow scoped stores via WorkflowProvider.
 * WSMethodContext is a real React context — no window globals.
 */

"use client";

import { createContext, useContext, useEffect, useMemo, type ReactNode } from "react";
import { WorkflowProvider } from "./WorkflowContext";
import { getWorkflowManager } from "./WorkflowManager";
import { replayEventsToStores, loadLegacyRunData } from "./replayEvents";
import { fetchWithAuth } from "@/lib/api";

// ============================================================
// WSMethodContext — React context for WebSocket send methods
// ============================================================

interface WSMethods {
  sendAnswer: (questionId: string, answer: string) => void;
  sendStopAndRegenerate: (agentName: string, partialOutput: string, userGuidance: string) => void;
}

const WSMethodContext = createContext<WSMethods | null>(null);

export function WSMethodProvider({
  sendAnswer,
  sendStopAndRegenerate,
  children,
}: WSMethods & { children: ReactNode }) {
  const value = useMemo(
    () => ({ sendAnswer, sendStopAndRegenerate }),
    [sendAnswer, sendStopAndRegenerate],
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
    manager.setActiveWorkflowId(workflowId);
  }, [manager, workflowId]);

  // REST fallback: if WS events haven't populated stores after 5s, fetch from API.
  // Only restores data for completed/failed runs — never overwrites a running workflow,
  // since WS events will eventually arrive and a stale REST snapshot would cause a
  // visual "restart" glitch.
  useEffect(() => {
    if (!workflowId) return;
    let cancelled = false;

    const timer = setTimeout(async () => {
      const stores = manager.getStores(workflowId);
      if (!stores || cancelled) return;

      // Don't overwrite if we already have a DAG and the workflow is in a terminal state
      const wfState = stores.workflow.getState();
      if (wfState.dag && (wfState.status === "completed" || wfState.status === "failed" || wfState.status === "paused")) return;
      // Also don't overwrite if we have a DAG and nodes are being populated (WS events arriving)
      if (wfState.dag && Object.keys(wfState.nodes).length > 0) return;

      console.warn(
        `[WorkflowScope] REST fallback triggered for ${workflowId} — WS did not deliver DAG within 5s`
      );

      try {
        const r = await fetchWithAuth(`/api/runs/${workflowId}`);
        if (!r.ok || cancelled) return;
        const data = await r.json();

        // Re-check after async gap — WS events may have arrived
        if (stores.workflow.getState().dag) {
          console.info(`[WorkflowScope] REST fallback cancelled for ${workflowId} — DAG arrived during fetch`);
          return;
        }

        // Never restore a running workflow — WS will deliver live data.
        // Only restore completed/failed/paused runs (historical replay).
        if (data.status === "running") {
          console.info(`[WorkflowScope] REST fallback skipped for ${workflowId} — run is still running, waiting for WS`);
          return;
        }

        if (data.events?.length) {
          replayEventsToStores(workflowId, data.events);
        } else {
          loadLegacyRunData(workflowId, data.conversation ?? [], data.chart_groups ?? null);
        }

        // Set DAG/status if still missing
        const wf = stores.workflow.getState();
        if (!wf.dag && data.dag) {
          wf.handleWorkflowStarted({
            workflow_id: workflowId,
            name: data.workflow_name,
            dag: data.dag,
            inputs: data.inputs,
          });
        }
        if (data.status === "completed" || data.status === "failed") {
          stores.workflow.getState().handleWorkflowCompleted({
            workflow_id: workflowId,
            status: data.status === "failed" ? "failed" : "completed",
          });
        }
      } catch {}
    }, 5000);

    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [manager, workflowId]);

  if (!stores) return <>{children}</>;

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
