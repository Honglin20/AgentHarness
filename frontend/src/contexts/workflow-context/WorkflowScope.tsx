/**
 * WorkflowScope - Context Provider wrapper
 *
 * WS lifecycle lives in WorkflowCenterPanel (stable parent).
 * WorkflowScope just provides per-workflow scoped stores via WorkflowProvider.
 * WSMethodContext is a real React context — no window globals.
 */

"use client";

import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from "react";
import { WorkflowProvider } from "./WorkflowContext";
import { getWorkflowManager } from "./WorkflowManager";
import type { WorkflowStores } from "./workflowStores";

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
  const prevWorkflowIdRef = useRef<string | null>(null);

  const stores = useMemo(() => {
    if (!workflowId) return null;
    return manager.getOrCreate(workflowId).stores;
  }, [manager, workflowId]);

  const setActiveWorkflowId = useMemo(
    () => (id: string | null) => manager.setActiveWorkflowId(id),
    [manager],
  );

  useEffect(() => {
    // Reset scoped stores when switching to a DIFFERENT workflow,
    // so a fresh WS replay populates clean state (no stacking).
    if (workflowId && workflowId !== prevWorkflowIdRef.current) {
      const entry = manager.getOrCreate(workflowId);
      resetAllStores(entry.stores);
    }
    prevWorkflowIdRef.current = workflowId;
    manager.setActiveWorkflowId(workflowId);
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

function resetAllStores(stores: WorkflowStores): void {
  stores.conversation.getState().reset();
  stores.output.getState().reset();
  stores.workflow.getState().reset();
  stores.chart.getState().reset();
  stores.toolCall.getState().reset();
  stores.agentIO.getState().reset();
  stores.chat.getState().reset();
  stores.span.getState().reset();
}
