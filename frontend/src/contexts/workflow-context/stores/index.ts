/**
 * Workflow Stores — barrel export
 *
 * Re-exports all individual store factories plus the container interface.
 */

import type { StoreApi } from "zustand/vanilla";
import type { ConversationState } from "@/stores/conversationStore";
import type { OutputState } from "@/stores/outputStore";
import type { WorkflowState } from "@/stores/workflowStore";
import type { ChartState } from "@/stores/chartStore";
import type { ToolCallState } from "@/stores/toolCallStore";
import type { AgentIOState } from "@/stores/agentIOStore";
import type { SpanState } from "@/stores/spanStore";
import type { IdCounter } from "@/lib/idCounter";

import { createConversationStore } from "./conversation";
import { createOutputStore } from "./output";
import { createWorkflowStore } from "./workflow";
import { createChartStore } from "./chart";
import { createToolCallStore, getToolCallCounter } from "./toolCall";
import { createAgentIOStore } from "./agentIO";
import { createSpanStore } from "./span";
import {
  createTodoStore,
  handleTodoCreated,
  handleTodoUpdated,
  handleTodoBulkCompleted,
  handleTodoReplaced,
  accumulateStepTokens,
} from "./todo";

// Re-export all imports
export {
  createConversationStore,
  createOutputStore,
  createWorkflowStore,
  createChartStore,
  createToolCallStore,
  getToolCallCounter,
  createAgentIOStore,
  createSpanStore,
  createTodoStore,
  handleTodoCreated,
  handleTodoUpdated,
  handleTodoBulkCompleted,
  handleTodoReplaced,
  accumulateStepTokens,
};

// Re-export types
export type { IdCounter } from "@/lib/idCounter";
export type { TodoState, TodoStep } from "./todo";

// ============================================================
// Workflow Stores Container
// ============================================================
export interface WorkflowStores {
  conversation: StoreApi<ConversationState>;
  output: StoreApi<OutputState>;
  workflow: StoreApi<WorkflowState>;
  chart: StoreApi<ChartState>;
  toolCall: StoreApi<ToolCallState>;
  agentIO: StoreApi<AgentIOState>;
  span: StoreApi<SpanState>;
  todo: StoreApi<import("./todo").TodoState>;
}

export interface CreateWorkflowStoresOptions {
  /** Persist callback for conversation store; see ConversationStoreOptions.onPersist. */
  onPersistConversation?: () => void;
}

export function createWorkflowStores(
  workflowId: string,
  options: CreateWorkflowStoresOptions = {},
): WorkflowStores {
  return {
    conversation: createConversationStore(workflowId, {
      onPersist: options.onPersistConversation,
    }),
    output: createOutputStore(workflowId),
    workflow: createWorkflowStore(workflowId),
    chart: createChartStore(workflowId),
    toolCall: createToolCallStore(workflowId),
    agentIO: createAgentIOStore(workflowId),
    span: createSpanStore(workflowId),
    todo: createTodoStore(workflowId),
  };
}

/**
 * 访问 store 内部计数器的辅助函数
 */
export function getMessageCounter(store: StoreApi<ConversationState>): IdCounter {
  return (store as unknown as { _msgCounter: IdCounter })._msgCounter;
}
