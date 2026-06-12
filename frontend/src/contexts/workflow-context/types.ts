/**
 * Workflow Context 类型定义
 */

import type { WSEvent } from "@/types/events";
import type { StoreApi } from "zustand/vanilla";

/**
 * Workflow 生命周期状态
 */
export type WorkflowLifecycleState =
  | "created"
  | "running"    // 正在前台运行
  | "background" // 在后台运行（已切换但仍在执行）
  | "completed"  // 已完成，状态已缓存
  | "idle";      // 即将销毁

/**
 * Workflow 运行状态
 */
export type WorkflowStatus = "idle" | "running" | "completed" | "failed" | "paused";

/**
 * 连接类型
 */
export type ConnectionType = "single" | "batch";

/**
 * 连接信息
 */
export interface ConnectionInfo {
  type: ConnectionType;
  ws: WebSocket | null;
  batchId: string | null;
}

/**
 * Workflow Stores 容器
 * 使用 StoreApi，可以在 React 环境外使用
 */
export interface WorkflowStores {
  conversation: StoreApi<import("@/stores/conversationStore").ConversationState>;
  output: StoreApi<import("@/stores/outputStore").OutputState>;
  workflow: StoreApi<import("@/stores/workflowStore").WorkflowState>;
  chart: StoreApi<import("@/stores/chartStore").ChartState>;
  toolCall: StoreApi<import("@/stores/toolCallStore").ToolCallState>;
  agentIO: StoreApi<import("@/stores/agentIOStore").AgentIOState>;
  span: StoreApi<import("@/stores/spanStore").SpanState>;
  todo: StoreApi<import("./stores/todo").TodoState>;
}

/**
 * WorkflowContext 值
 */
export interface WorkflowContextValue {
  /**
   * 当前活跃的 workflow ID
   */
  workflowId: string | null;

  /**
   * 当前 workflow 的 stores（如果存在）
   */
  stores: WorkflowStores | null;

  /**
   * 设置活跃的 workflow ID
   */
  setActiveWorkflowId: (id: string | null) => void;
}

/**
 * 清理级别
 */
export type CleanupLevel = "light" | "medium" | "aggressive";

/**
 * 事件到 Store 的映射
 */
export const EVENT_TO_STORES: Record<string, (keyof WorkflowStores)[]> = {
  "workflow.started": ["workflow"],
  "workflow.completed": ["workflow"],
  "workflow.error": ["workflow"],
  "workflow.cancelled": ["workflow"],

  "node.started": ["workflow", "conversation"],
  "node.completed": ["workflow", "conversation", "agentIO"],
  "node.failed": ["workflow", "conversation", "agentIO"],

  "agent.text_delta": ["output", "conversation"],
  "agent.tool_call": ["toolCall", "conversation"],
  "agent.tool_result": ["toolCall", "conversation"],
  "agent.tool_output_delta": ["conversation"],

  "chat.question": ["conversation"],
  "chat.answer": ["conversation"],

  "chart.render": ["chart"],
} as const;

/**
 * 事件处理器类型
 */
export type EventHandler<T extends WSEvent["type"]> = (
  payload: Extract<WSEvent, { type: T }>["payload"]
) => void;

/**
 * 配置选项
 */
export interface WorkflowManagerConfig {
  /**
   * 空闲清理阈值（毫秒），默认 5 分钟
   */
  idleCleanupThreshold?: number;

  /**
   * 最大 workflow 数量，超过后触发清理
   */
  maxWorkflows?: number;

  /**
   * 最大事件缓存大小
   */
  maxEventCacheSize?: number;
}