/**
 * Workflow Scoped Hooks
 *
 * 提供访问 workflow-scoped stores 的 React hooks
 *
 * 这些 hooks 封装了 Context API，提供类似原始 store hooks 的 API
 */

import { useStore } from "zustand";
import { useShallow } from "zustand/shallow";
import { createStore } from "zustand/vanilla";
import { useWorkflowStore as getWorkflowStoreApi } from "./WorkflowContext";
import type {
  ConversationMessage,
  ConversationState,
} from "@/stores/conversationStore";
import type { OutputState } from "@/stores/outputStore";
import type { WorkflowState, NodeState } from "@/stores/workflowStore";
import { useWorkflowStore as useGlobalWorkflowStore } from "@/stores/workflowStore";
import type { ChartState, ChartGroup } from "@/stores/chartStore";
import type { ToolCallRecord, ToolCallState } from "@/stores/toolCallStore";
import type { AgentIOData, AgentIOState } from "@/stores/agentIOStore";
import type { ChatMessage, ChatState } from "@/stores/chatStore";
import type { StoreApi } from "zustand/vanilla";

// Dummy stores for when no workflow is active — keeps hooks unconditionally called.
//
// dummyWorkflowStore 在模块加载时从全局 workflowStore 拷贝初始状态并订阅其
// 变化保持同步。原因：setSelectedTemplate / previewTemplate 等动作写入全局
// useWorkflowStore（来自 DomainWorkflowsPage / DomainTutorialPage 等入口），
// 启动页（无 active workflow）需要通过 dummy 读到这些值；如果 dummy 是静态
// 默认值，ScopedCenterPanel 的 portal 判定会卡在原页面。
function makeDummy<T>(initial: T): StoreApi<T> {
  return createStore<T>(() => initial);
}
const dummyConversationStore = makeDummy<ConversationState>({ messages: [], pendingQuestionId: null, pendingQuestionAgent: null, activeFollowupAgent: null } as unknown as ConversationState);
const dummyOutputStore = makeDummy<OutputState>({ texts: {}, activeNodeId: null, workflowError: null } as unknown as OutputState);
const dummyWorkflowStore = makeDummy<WorkflowState>(useGlobalWorkflowStore.getState() as WorkflowState);
useGlobalWorkflowStore.subscribe((state) => {
  dummyWorkflowStore.setState(state as WorkflowState, true);
});
const dummyChartStore = makeDummy<ChartState>({ groups: {}, groupOrder: [] } as unknown as ChartState);
const dummyChatStore = makeDummy<ChatState>({ messages: [], pendingQuestionId: null } as unknown as ChatState);

// ============================================================
// Conversation Store Hooks
// ============================================================

/**
 * useScopedConversationStore
 *
 * 访问当前 workflow 的 conversation store
 */
export function useScopedConversationStore<T>(
  selector: (state: ConversationState) => T
): T {
  const store = getWorkflowStoreApi("conversation") ?? dummyConversationStore;
  return useStore(store, selector);
}

/**
 * useConversationMessages
 *
 * 快捷 hook：获取消息列表
 */
export function useConversationMessages(): ConversationMessage[] {
  return useScopedConversationStore((s) => s.messages);
}

/**
 * usePendingQuestion
 *
 * 快捷 hook：获取待处理问题
 */
export function usePendingQuestion(): {
  questionId: string | null;
  agentName: string | null;
} {
  return useScopedConversationStore(
    useShallow((s) => ({
      questionId: s.pendingQuestionId,
      agentName: s.pendingQuestionAgent,
    }))
  );
}

// ============================================================
// Output Store Hooks
// ============================================================

/**
 * useScopedOutputStore
 *
 * 访问当前 workflow 的 output store
 */
export function useScopedOutputStore<T>(selector: (state: OutputState) => T): T {
  const store = getWorkflowStoreApi("output") ?? dummyOutputStore;
  return useStore(store, selector);
}

/**
 * useWorkflowError
 *
 * 快捷 hook：获取 workflow 错误
 */
export function useWorkflowError(): string | null {
  return useScopedOutputStore((s) => s.workflowError);
}

/**
 * useActiveNodeId
 *
 * 快捷 hook：获取当前活跃节点 ID
 */
export function useActiveNodeId(): string | null {
  return useScopedOutputStore((s) => s.activeNodeId);
}

/**
 * useNodeTexts
 *
 * 快捷 hook：获取节点文本
 */
export function useNodeTexts(): Record<string, string> {
  return useScopedOutputStore((s) => s.texts);
}

// ============================================================
// Workflow Store Hooks
// ============================================================

/**
 * useScopedWorkflowStore
 *
 * 访问当前 workflow 的 workflow store。无 active workflow 时（启动页 / 选
 * template 阶段）回退到 dummyWorkflowStore —— 该 store 在模块加载时镜像
 * 全局 workflowStore，并订阅其变化保持同步。
 *
 * 这样设计是因为 setSelectedTemplate / previewTemplate 写入的是全局
 * useWorkflowStore，启动页需要读到这些值；同时只让 useScopedWorkflowStore
 * 订阅一个 store，避免 useShallow 的缓存 ref 在双 store 间被交替覆盖触发
 * 死循环（React error #185）。
 */
export function useScopedWorkflowStore<T>(selector: (state: WorkflowState) => T): T {
  const store = getWorkflowStoreApi("workflow") ?? dummyWorkflowStore;
  return useStore(store, selector);
}

/**
 * useWorkflowInfo
 *
 * 快捷 hook：获取 workflow 基本信息
 */
export function useWorkflowInfo(): {
  workflowId: string | null;
  workflowName: string | null;
  status: WorkflowState["status"];
} {
  return useScopedWorkflowStore(
    useShallow((s) => ({
      workflowId: s.workflowId,
      workflowName: s.workflowName,
      status: s.status,
    }))
  );
}

/**
 * useWorkflowNodes
 *
 * 快捷 hook：获取所有节点状态
 */
export function useWorkflowNodes(): Record<string, NodeState> {
  return useScopedWorkflowStore((s) => s.nodes);
}

/**
 * useNodeCount
 *
 * 快捷 hook：获取节点数量
 */
export function useNodeCount(): number {
  return useScopedWorkflowStore((s) => Object.keys(s.nodes).length);
}

/**
 * useWorkflowStatus
 *
 * 快捷 hook：获取 workflow 状态
 */
export function useWorkflowStatus(): WorkflowState["status"] {
  return useScopedWorkflowStore((s) => s.status);
}

/**
 * useSelectedNodeId
 *
 * 快捷 hook：获取选中节点 ID
 */
export function useSelectedNodeId(): string | null {
  return useScopedWorkflowStore((s) => s.selectedNodeId);
}

/**
 * useWorkflowDAG
 *
 * 快捷 hook：获取 DAG 结构
 */
export function useWorkflowDAG(): WorkflowState["dag"] {
  return useScopedWorkflowStore((s) => s.dag);
}

/**
 * useSelectedTemplate
 *
 * 快捷 hook：获取选中模板
 */
export function useSelectedTemplate(): WorkflowState["selectedTemplate"] {
  return useScopedWorkflowStore((s) => s.selectedTemplate);
}

// ============================================================
// Chart Store Hooks
// ============================================================

/**
 * useScopedChartStore
 *
 * 访问当前 workflow 的 chart store
 */
export function useScopedChartStore<T>(selector: (state: ChartState) => T): T {
  const store = getWorkflowStoreApi("chart") ?? dummyChartStore;
  return useStore(store, selector);
}

/**
 * useChartGroups
 *
 * 快捷 hook：获取所有图表分组
 */
export function useChartGroups(): { groups: Record<string, ChartGroup>; order: string[] } {
  return useScopedChartStore(
    useShallow((s) => ({
      groups: s.groups,
      order: s.groupOrder,
    }))
  );
}

/**
 * useLiveResultCount
 *
 * 快捷 hook：获取结果图表数量
 */
export function useLiveResultCount(): number {
  return useScopedChartStore((s) => s.groupOrder.length);
}

/**
 * useLiveAnalysisCount
 *
 * 快捷 hook：获取分析图表数量
 */
export function useLiveAnalysisCount(): number {
  return useScopedChartStore((s) => {
    let count = 0;
    for (const label of s.groupOrder) {
      if (s.groups[label]?.category === "analysis") count++;
    }
    return count;
  });
}

// ============================================================
// Chat Store Hooks
// ============================================================

/**
 * useScopedChatStore
 *
 * 访问当前 workflow 的 chat store
 */
export function useScopedChatStore<T>(selector: (state: ChatState) => T): T {
  const store = getWorkflowStoreApi("chat") ?? dummyChatStore;
  return useStore(store, selector);
}

/**
 * useChatMessages
 *
 * 快捷 hook：获取 chat 消息列表
 */
export function useChatMessages(): ChatMessage[] {
  return useScopedChatStore((s) => s.messages);
}

// ============================================================
// Workflow Context Hooks
// ============================================================

import { useWorkflowContext } from "./WorkflowContext";

/**
 * useWorkflowId
 *
 * 获取当前 workflow ID
 */
export function useWorkflowId(): string | null {
  const { workflowId } = useWorkflowContext();
  return workflowId;
}

/**
 * useIsWorkflowActive
 *
 * 检查是否有活跃的 workflow
 */
export function useIsWorkflowActive(): boolean {
  const { workflowId } = useWorkflowContext();
  return workflowId !== null;
}

// ============================================================
// Store Actions Helpers
// ============================================================

/**
 * 获取 conversation store 的 actions（用于事件处理）
 */
export function getConversationActions(store: StoreApi<ConversationState>) {
  return store.getState();
}

/**
 * 获取 output store 的 actions（用于事件处理）
 */
export function getOutputActions(store: StoreApi<OutputState>) {
  return store.getState();
}

/**
 * 获取 workflow store 的 actions（用于事件处理）
 */
export function getWorkflowActions(store: StoreApi<WorkflowState>) {
  return store.getState();
}

/**
 * 获取 chart store 的 actions（用于事件处理）
 */
export function getChartActions(store: StoreApi<ChartState>) {
  return store.getState();
}

/**
 * 获取 tool call store 的 actions（用于事件处理）
 */
export function getToolCallActions(store: StoreApi<ToolCallState>) {
  return store.getState();
}

/**
 * 获取 agent IO store 的 actions（用于事件处理）
 */
export function getAgentIOActions(store: StoreApi<AgentIOState>) {
  return store.getState();
}

/**
 * 获取 chat store 的 actions（用于事件处理）
 */
export function getChatActions(store: StoreApi<ChatState>) {
  return store.getState();
}

/**
 * Cache store action objects by store reference.
 * Zustand actions are stable function references defined once in the creator.
 * Stores are created once per workflow (useMemo in WorkflowScope), so the
 * cached object is stable across renders.
 */
const actionCache = new WeakMap<StoreApi<any>, any>();

function getStableActions<T>(store: StoreApi<T>): T {
  if (!actionCache.has(store)) {
    actionCache.set(store, store.getState());
  }
  return actionCache.get(store);
}

/**
 * useWorkflowActions
 *
 * 获取当前 workflow store 的 actions（用于调用方法）
 */
export function useWorkflowActions() {
  const store = getWorkflowStoreApi("workflow");
  if (!store) return {} as ReturnType<typeof getStableActions<WorkflowState>>;
  return getStableActions(store);
}

/**
 * useOutputActions
 *
 * 获取当前 output store 的 actions（用于调用方法）
 */
export function useOutputActions() {
  const store = getWorkflowStoreApi("output");
  if (!store) return {} as ReturnType<typeof getStableActions<OutputState>>;
  return getStableActions(store);
}

/**
 * useConversationActions
 *
 * 获取当前 conversation store 的 actions（用于调用方法）
 */
export function useConversationActions() {
  const store = getWorkflowStoreApi("conversation");
  if (!store) return {} as ReturnType<typeof getStableActions<ConversationState>>;
  return getStableActions(store);
}

/**
 * useChartActions
 *
 * 获取当前 chart store 的 actions（用于调用方法）
 */
export function useChartActions() {
  const store = getWorkflowStoreApi("chart");
  if (!store) return {} as ReturnType<typeof getStableActions<ChartState>>;
  return getStableActions(store);
}

/**
 * useChatActions
 *
 * 获取当前 chat store 的 actions（用于调用方法）
 */
export function useChatActions() {
  const store = getWorkflowStoreApi("chat");
  if (!store) return {} as ReturnType<typeof getStableActions<ChatState>>;
  return getStableActions(store);
}