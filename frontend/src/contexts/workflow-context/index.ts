/**
 * Workflow Context - Context 隔离架构
 *
 * 导出所有公共 API
 */

// Context
export {
  WorkflowProvider,
  useWorkflowContext,
  useWorkflowContextSafe,
  useWorkflowStores,
  useWorkflowStore,
} from "./WorkflowContext";
export type { WorkflowContextValue } from "./types";

// Hooks
export {
  useScopedConversationStore,
  useConversationMessages,
  usePendingQuestion,
  useScopedOutputStore,
  useWorkflowError,
  useActiveNodeId,
  useNodeTexts,
  useScopedChatStore,
  useChatMessages,
  useScopedChartStore,
  useChartGroups,
  useLiveResultCount,
  useLiveAnalysisCount,
  useScopedWorkflowStore,
  useWorkflowInfo,
  useWorkflowNodes,
  useNodeCount,
  useWorkflowStatus,
  useSelectedNodeId,
  useWorkflowDAG,
  useSelectedTemplate,
  useWorkflowId,
  useIsWorkflowActive,
  getConversationActions,
  getOutputActions,
  getWorkflowActions,
  getChartActions,
  getToolCallActions,
  getAgentIOActions,
  getChatActions,
  useWorkflowActions,
  useOutputActions,
  useConversationActions,
  useChartActions,
  useChatActions,
} from "./hooks";

// Event routing (Phase 2)
export { dispatchSingleEvent, dispatchBatchEvent } from "./eventRouter";
export { useScopedWorkflowEvents, setActiveWorkflowId } from "./useWorkflowEvents";
export type { ScopedWorkflowEventsReturn } from "./useWorkflowEvents";

// Scope
export { WorkflowScope, WSMethodProvider, getWSMethods } from "./WorkflowScope";

// WebSocket (stable parent-level)
export { useWorkflowWS } from "./useWorkflowWS";
export type { WorkflowWSReturn } from "./useWorkflowWS";

// Manager
export { getWorkflowManager } from "./WorkflowManager";
export type { WorkflowEntry } from "./WorkflowManager";

// Store 工厂
export {
  createWorkflowStores,
  createConversationStore,
  createOutputStore,
  createWorkflowStore,
  createChartStore,
  createToolCallStore,
  createAgentIOStore,
  createChatStore,
  getMessageCounter,
  getToolCallCounter,
} from "./workflowStores";
export type { WorkflowStores } from "./workflowStores";

// 类型
export type {
  WorkflowLifecycleState,
  WorkflowStatus,
  ConnectionType,
  ConnectionInfo,
  CleanupLevel,
  EventHandler,
  WorkflowManagerConfig,
} from "./types";
export { EVENT_TO_STORES } from "./types";
export type { WorkflowStores as WorkflowStoresType } from "./types";