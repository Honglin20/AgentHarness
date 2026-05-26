/**
 * WorkflowContext - Context 隔离架构
 *
 * 为每个 workflow 提供独立的 store 实例
 */

import { createContext, useContext, useMemo, type ReactNode } from "react";
import type { WorkflowStores, WorkflowContextValue } from "./types";

/**
 * WorkflowContext
 *
 * 提供当前活跃 workflow 的 stores 和切换方法
 */
const WorkflowContext = createContext<WorkflowContextValue | null>(null);

/**
 * WorkflowProvider
 *
 * Context Provider，由 WorkflowManager 管理
 */
interface WorkflowProviderProps {
  workflowId: string | null;
  stores: WorkflowStores | null;
  setActiveWorkflowId: (id: string | null) => void;
  children: ReactNode;
}

export function WorkflowProvider({
  workflowId,
  stores,
  setActiveWorkflowId,
  children,
}: WorkflowProviderProps) {
  const value = useMemo(
    () => ({ workflowId, stores, setActiveWorkflowId }),
    [workflowId, stores, setActiveWorkflowId],
  );

  return (
    <WorkflowContext.Provider value={value}>
      {children}
    </WorkflowContext.Provider>
  );
}

/**
 * useWorkflowContext
 *
 * 获取当前 workflow 的 context
 */
export function useWorkflowContext(): WorkflowContextValue {
  const context = useContext(WorkflowContext);
  if (!context) {
    throw new Error(
      "useWorkflowContext must be used within WorkflowProvider. " +
      "Make sure your component is wrapped by WorkflowScope or WorkflowManager."
    );
  }
  return context;
}

/**
 * useWorkflowContextSafe
 *
 * 获取当前 workflow 的 context，返回 null 如果不在 Provider 内
 */
export function useWorkflowContextSafe(): WorkflowContextValue | null {
  return useContext(WorkflowContext);
}

/**
 * useWorkflowStores
 *
 * 获取当前 workflow 的 stores
 * 返回 null 如果没有 active workflow
 */
export function useWorkflowStores(): WorkflowStores | null {
  const { stores } = useWorkflowContext();
  return stores;
}

/**
 * useWorkflowStore
 *
 * 获取单个 store 的实例
 *
 * @example
 * ```tsx
 * const conversationStore = useWorkflowStore("conversation");
 * const messages = useStore(conversationStore, (s) => s.messages);
 * ```
 */
export function useWorkflowStore<K extends keyof WorkflowStores>(
  name: K,
): WorkflowStores[K] | null {
  const stores = useWorkflowStores();
  return stores ? stores[name] : null;
}