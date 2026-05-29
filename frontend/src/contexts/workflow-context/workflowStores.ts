/**
 * Workflow Stores 工厂函数
 *
 * 为每个 workflow 创建独立的 store 实例
 * 使用 zustand/vanilla 以便在非 React 环境中使用
 */

import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type {
  ConversationMessage,
  ConversationState,
} from "@/stores/conversationStore";
import type { OutputState } from "@/stores/outputStore";
import type {
  WorkflowState,
  NodeState,
} from "@/stores/workflowStore";
import type {
  ChartState,
  ChartGroup,
} from "@/stores/chartStore";
import type {
  ToolCallRecord,
  ToolCallState,
} from "@/stores/toolCallStore";
import type { AgentIOData, AgentIOState } from "@/stores/agentIOStore";
import type { ChatMessage, ChatState } from "@/stores/chatStore";
import type {
  WorkflowStartedPayload,
  WorkflowCompletedPayload,
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
} from "@/types/events";

// ============================================================
// Helper: Message Counter
// ============================================================
interface MessageCounter {
  current: number;
  next: () => string;
}
function createMessageCounter(): MessageCounter {
  let current = 0;
  return {
    get current() { return current; },
    next: () => `msg-${++current}`,
  };
}

// ============================================================
// Helper: Tool Call ID Counter
// ============================================================
interface ToolCallCounter {
  current: number;
  next: () => string;
}
function createToolCallCounter(): ToolCallCounter {
  let current = 0;
  return {
    get current() { return current; },
    next: () => `tc-${++current}`,
  };
}

// ============================================================
// Conversation Store
// ============================================================
export function createConversationStore(
  workflowId: string,
): StoreApi<ConversationState> {
  const msgCounter = createMessageCounter();

  const initialState: ConversationState = {
    messages: [],
    pendingQuestionId: null,
    pendingQuestionAgent: null,

    // Cache management (保留用于 batch 模式兼容)
    _cache: {},
    _activeWid: null,

    // Actions (在事件层实现，这里提供基础实现)
    addSystemMessage: (content) => {
      /* Phase 2 实现 */
    },
    addAgentMessage: (nodeId, agentName) => {
      /* Phase 2 实现 */
    },
    appendAgentText: (nodeId, text) => {
      /* Phase 2 实现 */
    },
    appendAgentThinking: (nodeId, text) => {
      /* Phase 2 实现 */
    },
    completeAgentMessage: (nodeId, agentName, durationMs) => {
      /* Phase 2 实现 */
    },
    failAgentMessage: (nodeId, agentName, error, durationMs) => {
      /* Phase 2 实现 */
    },
    addToolCall: (nodeId, agentName, toolName, toolArgs) => {
      /* Phase 2 实现 */
    },
    addToolResult: (nodeId, toolName, result) => {
      /* Phase 2 实现 */
    },
    appendToolOutput: (nodeId, toolName, line, stream) => {
      /* Phase 2 实现 */
    },
    addAgentQuestion: (questionId, question, agentName) => {
      /* Phase 2 实现 */
    },
    addUserMessage: (content) => {
      /* Phase 2 实现 */
    },
    clearPendingQuestion: (questionId) => {
      /* Phase 2 实现 */
    },
    interruptAgentMessage: (agentName) => {
      /* Phase 2 实现 */
    },
    resumeAgentMessage: (nodeId, agentName) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },

    // Cache management
    saveToCache: (wid) => {
      /* Phase 2 实现 */
    },
    restoreFromCache: (wid) => false,
    setActiveWid: (wid) => {
      /* Phase 2 实现 */
    },
    clearCache: () => {
      /* Phase 2 实现 */
    },
    appendAgentTextToCache: (wid, nodeId, text, agentName) => {
      /* Phase 2 实现 */
    },
    addToolCallToCache: (wid, nodeId, agentName, toolName, toolArgs) => {
      /* Phase 2 实现 */
    },
    addToolResultToCache: (wid, nodeId, toolName, result) => {
      /* Phase 2 实现 */
    },
  };

  const store = createStore<ConversationState>()((set, get) => ({
    ...initialState,

    // 实际实现 (从全局 store 复制)
    addSystemMessage: (content) =>
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: `msg-${msgCounter.next()}`,
            type: "system",
            content,
            timestamp: Date.now(),
          },
        ],
      })),

    addAgentMessage: (nodeId, agentName) =>
      set((state) => {
        // Don't add another if one is already streaming for this nodeId
        const streamingIdx = state.messages.findLastIndex(
          (m) => m.nodeId === nodeId && m.status === "streaming"
        );
        if (streamingIdx !== -1) return state;

        return {
          messages: [
            ...state.messages,
            {
              id: `msg-${msgCounter.next()}`,
              type: "agent",
              nodeId,
              agentName,
              content: "",
              status: "streaming",
              timestamp: Date.now(),
            },
          ],
        };
      }),

    appendAgentText: (nodeId, text) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
        );
        if (idx !== -1) {
          const messages = [...state.messages];
          messages[idx] = { ...messages[idx], content: messages[idx].content + text };
          return { messages };
        }

        // No streaming message — auto-create one (text arriving after a tool call)
        const lastMsg = state.messages[state.messages.length - 1];
        const agentName = lastMsg?.agentName ?? "";
        return {
          messages: [
            ...state.messages,
            {
              id: `msg-${msgCounter.next()}`,
              type: "agent",
              nodeId,
              agentName,
              content: text,
              status: "streaming",
              timestamp: Date.now(),
            },
          ],
        };
      }),

    appendAgentThinking: (nodeId, text) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
        );
        if (idx !== -1) {
          const messages = [...state.messages];
          messages[idx] = { ...messages[idx], thinking: (messages[idx].thinking ?? "") + text };
          return { messages };
        }
        return state;
      }),

    completeAgentMessage: (nodeId, agentName, durationMs) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) => m.nodeId === nodeId && m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")
        );
        if (idx === -1) return state;

        const messages = [...state.messages];
        messages[idx] = {
          ...messages[idx],
          agentName,
          status: "done",
          durationMs,
        };
        return { messages };
      }),

    failAgentMessage: (nodeId, agentName, error, durationMs) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) => m.nodeId === nodeId && m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")
        );
        if (idx === -1) return state;

        const messages = [...state.messages];
        messages[idx] = {
          ...messages[idx],
          agentName,
          content: messages[idx].content + `\n\n**Error:** ${error}`,
          status: "error",
          durationMs,
        };
        return { messages };
      }),

    addToolCall: (nodeId, agentName, toolName, toolArgs) =>
      set((state) => {
        // Finalize any streaming agent message for this node
        let msgs = [...state.messages];
        const streamingIdx = msgs.findLastIndex(
          (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
        );
        if (streamingIdx !== -1) {
          if (!msgs[streamingIdx].content.trim() && !msgs[streamingIdx].thinking?.trim()) {
            // No text before this tool call — remove the empty placeholder
            // so the final output appears AFTER tool calls, not before.
            msgs.splice(streamingIdx, 1);
          } else {
            msgs[streamingIdx] = { ...msgs[streamingIdx], status: "done" as const };
          }
        }

        return {
          messages: [
            ...msgs,
            {
              id: `msg-${msgCounter.next()}`,
              type: "tool_call",
              nodeId,
              agentName,
              content: "",
              toolName,
              toolArgs,
              toolStatus: "running",
              timestamp: Date.now(),
            },
          ],
        };
      }),

    addToolResult: (nodeId, toolName, result) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) =>
            m.nodeId === nodeId &&
            m.type === "tool_call" &&
            m.toolName === toolName &&
            m.toolResult === undefined
        );
        if (idx === -1) return state;

        const messages = [...state.messages];
        const msg = messages[idx];
        const elapsed = msg.timestamp ? Date.now() - msg.timestamp : undefined;
        messages[idx] = { ...msg, toolResult: result, toolStatus: "done", toolDurationMs: elapsed };
        return { messages };
      }),

    appendToolOutput: (nodeId, toolName, line, stream) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) =>
            m.nodeId === nodeId &&
            m.type === "tool_call" &&
            m.toolName === toolName &&
            m.toolResult === undefined
        );
        if (idx === -1) return state;

        const messages = [...state.messages];
        const msg = messages[idx];
        const prev = msg.toolStreamingOutput ?? "";
        const text = stream === "stderr" ? `[stderr] ${line}` : line;
        messages[idx] = { ...msg, toolStreamingOutput: prev + text + "\n" };
        return { messages };
      }),

    addAgentQuestion: (questionId, question, agentName) =>
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: `msg-${msgCounter.next()}`,
            type: "agent",
            content: question,
            agentName,
            status: "done",
            timestamp: Date.now(),
          },
        ],
        pendingQuestionId: questionId,
        pendingQuestionAgent: agentName,
      })),

    addUserMessage: (content) =>
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: `msg-${msgCounter.next()}`,
            type: "user",
            content,
            timestamp: Date.now(),
          },
        ],
      })),

    clearPendingQuestion: (questionId) =>
      set((state) =>
        state.pendingQuestionId === questionId
          ? { pendingQuestionId: null, pendingQuestionAgent: null }
          : state
      ),

    interruptAgentMessage: (agentName) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) => m.type === "agent" && m.status === "streaming" && (m.agentName === agentName || m.nodeId === agentName)
        );
        if (idx === -1) return state;

        const messages = [...state.messages];
        messages[idx] = { ...messages[idx], status: "interrupted" };
        return { messages };
      }),

    resumeAgentMessage: (nodeId, agentName) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) => m.type === "agent" && m.status === "interrupted" && (m.nodeId === nodeId || m.agentName === agentName)
        );
        if (idx === -1) return state;

        const messages = [...state.messages];
        messages[idx] = { ...messages[idx], status: "streaming" };
        return { messages };
      }),

    reset: () =>
      set({ messages: [], pendingQuestionId: null, pendingQuestionAgent: null }),

    saveToCache: (wid) =>
      set((state) => {
        const { messages, pendingQuestionId, pendingQuestionAgent, _cache } = state;
        return {
          _cache: { ..._cache, [wid]: { messages, pendingQuestionId, pendingQuestionAgent } },
        };
      }),

    restoreFromCache: (wid) => {
      set((state) => {
        const { _cache } = state;
        const snap = _cache[wid];
        if (!snap) return state;
        return { messages: snap.messages, pendingQuestionId: snap.pendingQuestionId, pendingQuestionAgent: snap.pendingQuestionAgent };
      });
      return true;
    },

    setActiveWid: (wid) =>
      set((state) => {
        const _activeWid = state._activeWid;
        const _cache = state._cache;
        if (_activeWid) {
          return {
            ...state,
            _cache: { ..._cache, [_activeWid]: { messages: state.messages, pendingQuestionId: state.pendingQuestionId, pendingQuestionAgent: state.pendingQuestionAgent } },
          };
        }
        if (wid && _cache[wid]) {
          const snap = _cache[wid];
          return {
            ...state,
            messages: snap.messages,
            pendingQuestionId: snap.pendingQuestionId,
            pendingQuestionAgent: snap.pendingQuestionAgent,
            _activeWid: wid,
          };
        }
        return {
          ...state,
          messages: [],
          pendingQuestionId: null,
          pendingQuestionAgent: null,
          _activeWid: wid,
        };
      }),

    clearCache: () => set({ _cache: {}, _activeWid: null }),

    appendAgentTextToCache: (wid, nodeId, text, agentName) =>
      set((state) => {
        if (!state._cache[wid]) {
          state._cache[wid] = { messages: [], pendingQuestionId: null, pendingQuestionAgent: null };
        }
        const cache = state._cache[wid];
        const idx = cache.messages.findLastIndex(
          (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
        );
        if (idx !== -1) {
          state._cache[wid].messages[idx] = {
            ...cache.messages[idx],
            content: cache.messages[idx].content + text,
          };
          return { _cache: state._cache };
        }
        state._cache[wid].messages = [
          ...cache.messages,
          {
            id: `msg-${msgCounter.next()}`,
            type: "agent",
            nodeId,
            agentName: agentName || "",
            content: text,
            status: "streaming",
            timestamp: Date.now(),
          },
        ];
        return { _cache: state._cache };
      }),

    addToolCallToCache: (wid, nodeId, agentName, toolName, toolArgs) =>
      set((state) => {
        if (!state._cache[wid]) {
          state._cache[wid] = { messages: [], pendingQuestionId: null, pendingQuestionAgent: null };
        }
        state._cache[wid].messages = [
          ...state._cache[wid].messages,
          {
            id: `msg-${msgCounter.next()}`,
            type: "tool_call",
            nodeId,
            agentName,
            content: "",
            toolName,
            toolArgs,
            toolStatus: "running",
            timestamp: Date.now(),
          },
        ];
        return { _cache: state._cache };
      }),

    addToolResultToCache: (wid, nodeId, toolName, result) =>
      set((state) => {
        if (!state._cache[wid]) {
          state._cache[wid] = { messages: [], pendingQuestionId: null, pendingQuestionAgent: null };
        }
        const cache = state._cache[wid];
        const idx = cache.messages.findLastIndex(
          (m) => m.nodeId === nodeId && m.type === "tool_call" && m.toolName === toolName && m.toolResult === undefined
        );
        if (idx !== -1) {
          const msg = cache.messages[idx];
          const elapsed = msg.timestamp ? Date.now() - msg.timestamp : undefined;
          state._cache[wid].messages[idx] = {
            ...msg,
            toolResult: result,
            toolStatus: "done",
            toolDurationMs: elapsed,
          };
          return { _cache: state._cache };
        }
        return state;
      }),
  }));

  (store as unknown as { _msgCounter: MessageCounter })._msgCounter = msgCounter;

  return store;
}

// ============================================================
// Output Store
// ============================================================
export function createOutputStore(
  workflowId: string,
): StoreApi<OutputState> {
  const initialState: OutputState = {
    texts: {},
    activeNodeId: null,
    workflowError: null,

    _cache: {},
    _activeWid: null,

    appendText: (nodeId, delta) => {
      /* Phase 2 实现 */
    },
    setActiveNode: (nodeId) => {
      /* Phase 2 实现 */
    },
    clearNode: (nodeId) => {
      /* Phase 2 实现 */
    },
    setWorkflowError: (error) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },

    saveToCache: (wid) => {
      /* Phase 2 实现 */
    },
    restoreFromCache: (wid) => false,
    setActiveWid: (wid) => {
      /* Phase 2 实现 */
    },
    clearCache: () => {
      /* Phase 2 实现 */
    },
  };

  return createStore<OutputState>()((set, get) => ({
    ...initialState,

    appendText: (nodeId, delta) =>
      set((state) => ({
        texts: {
          ...state.texts,
          [nodeId]: (state.texts[nodeId] ?? "") + delta,
        },
      })),

    setActiveNode: (nodeId) => set({ activeNodeId: nodeId }),

    clearNode: (nodeId) =>
      set((state) => {
        const { [nodeId]: _, ...rest } = state.texts;
        return {
          texts: rest,
          activeNodeId: state.activeNodeId === nodeId ? null : state.activeNodeId,
        };
      }),

    setWorkflowError: (error) => set({ workflowError: error }),

    reset: () => set({ texts: {}, activeNodeId: null, workflowError: null }),

    saveToCache: (wid) => {
      const { texts, activeNodeId, _cache } = get();
      _cache[wid] = { texts, activeNodeId };
      set({ _cache });
    },

    restoreFromCache: (wid) => {
      const snap = get()._cache[wid];
      if (!snap) return false;
      set({ texts: snap.texts, activeNodeId: snap.activeNodeId, _activeWid: wid });
      return true;
    },

    setActiveWid: (wid) => {
      const { _activeWid, _cache } = get();
      if (_activeWid) {
        _cache[_activeWid] = { texts: get().texts, activeNodeId: get().activeNodeId };
      }
      if (wid && _cache[wid]) {
        const snap = _cache[wid];
        set({ texts: snap.texts, activeNodeId: snap.activeNodeId, _activeWid: wid, _cache });
      } else {
        set({ texts: {}, activeNodeId: null, _activeWid: wid, _cache });
      }
    },

    clearCache: () => set({ _cache: {}, _activeWid: null }),
  }));
}

// ============================================================
// Workflow Store
// ============================================================
export function createWorkflowStore(
  workflowId: string,
): StoreApi<WorkflowState> {
  const initialState: WorkflowState = {
    workflowId: workflowId,
    workflowName: null,
    status: "idle",
    nodes: {},
    dag: null,
    envelope: null,
    selectedNodeId: null,
    selectedTemplate: null,
    activeWorkflowId: workflowId,

    _cache: {},

    setWorkflow: (id, name, dag) => {
      /* Phase 2 实现 */
    },
    setSelectedNode: (id) => {
      /* Phase 2 实现 */
    },
    setSelectedTemplate: (template) => {
      /* Phase 2 实现 */
    },
    setActiveWorkflowId: (id) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },
    previewTemplate: (template) => {
      /* Phase 2 实现 */
    },
    clearPreview: () => {
      /* Phase 2 实现 */
    },

    handleWorkflowStarted: (payload) => {
      /* Phase 2 实现 */
    },
    handleWorkflowCompleted: (payload) => {
      /* Phase 2 实现 */
    },
    handleNodeStarted: (payload) => {
      /* Phase 2 实现 */
    },
    handleNodeCompleted: (payload) => {
      /* Phase 2 实现 */
    },
    handleNodeFailed: (payload) => {
      /* Phase 2 实现 */
    },

    saveToCache: (wid) => {
      /* Phase 2 实现 */
    },
    restoreFromCache: (wid) => false,
    updateNodeInCache: (wid, payload) => {
      /* Phase 2 实现 */
    },
    setActiveWid: (wid) => {
      /* Phase 2 实现 */
    },
    clearCache: () => {
      /* Phase 2 实现 */
    },
  };

  return createStore<WorkflowState>()((set, get) => ({
    ...initialState,

    setWorkflow: (id, name, dag) =>
      set({
        workflowId: id,
        workflowName: name,
        dag: (dag as WorkflowState["dag"]) ?? null,
        status: "running",
        nodes: {},
        selectedNodeId: null,
      }),

    setSelectedNode: (id) => set({ selectedNodeId: id }),

    setSelectedTemplate: (template) => set({ selectedTemplate: template }),

    setActiveWorkflowId: (id) => set({ activeWorkflowId: id }),

    reset: () =>
      set({
        workflowId: null,
        workflowName: null,
        status: "idle",
        nodes: {},
        selectedNodeId: null,
        selectedTemplate: null,
      }),

    previewTemplate: (template) =>
      set({
        workflowName: (template.name as string) ?? null,
        dag: (template.dag as WorkflowState["dag"]) ?? null,
      }),

    clearPreview: () =>
      set({
        workflowName: null,
        dag: null,
      }),

    handleWorkflowStarted: (payload) =>
      set((state) => ({
        status: "running" as const,
        workflowId: payload.workflow_id,
        workflowName: payload.name,
        dag: payload.dag ?? state.dag,
        envelope: payload.envelope ?? null,
      })),

    handleWorkflowCompleted: (payload) =>
      set({
        status: payload.status === "failed"
          ? ("failed" as const)
          : payload.status === "paused"
            ? ("paused" as const)
            : ("completed" as const),
      }),

    handleNodeStarted: (payload) =>
      set((state) => ({
        nodes: {
          ...state.nodes,
          [payload.node_id]: {
            id: payload.node_id,
            name: payload.agent_name,
            status: "running",
            attempt: payload.attempt,
            tools: payload.tools,
            model: payload.model,
          },
        },
      })),

    handleNodeCompleted: (payload) =>
      set((state) => ({
        nodes: {
          ...state.nodes,
          [payload.node_id]: {
            ...state.nodes[payload.node_id],
            id: payload.node_id,
            name: payload.agent_name,
            status: "success",
            durationMs: payload.duration_ms,
            tokenUsage: payload.token_usage,
          },
        },
      })),

    handleNodeFailed: (payload) =>
      set((state) => ({
        nodes: {
          ...state.nodes,
          [payload.node_id]: {
            ...state.nodes[payload.node_id],
            id: payload.node_id,
            name: payload.agent_name,
            status: payload.will_retry ? "retrying" : "failed",
            error: payload.error,
            durationMs: payload.duration_ms,
            attempt: payload.attempt,
            willRetry: payload.will_retry,
          },
        },
      })),

    saveToCache: (wid) => {
      const { nodes, status, workflowId, workflowName, dag, envelope, _cache } = get();
      _cache[wid] = { nodes, status, workflowId, workflowName, dag, envelope };
      set({ _cache });
    },

    restoreFromCache: (wid) => {
      const snap = get()._cache[wid];
      if (!snap) return false;
      set({
        nodes: snap.nodes,
        status: snap.status,
        workflowId: snap.workflowId,
        workflowName: snap.workflowName,
        dag: snap.dag,
        envelope: snap.envelope,
      });
      return true;
    },

    updateNodeInCache: (wid, payload) => {
      const _cache = { ...get()._cache };
      if (!_cache[wid]) {
        _cache[wid] = { nodes: {}, status: "running", workflowId: wid, workflowName: null, dag: null, envelope: null };
      }
      const snap = _cache[wid];
      const nodes = { ...snap.nodes };

      if ("status" in payload && "error" in payload && "will_retry" in payload) {
        // NodeFailedPayload
        const p = payload as unknown as NodeFailedPayload;
        nodes[p.node_id] = {
          ...nodes[p.node_id],
          id: p.node_id,
          name: p.agent_name,
          status: p.will_retry ? "retrying" : "failed",
          error: p.error,
          durationMs: p.duration_ms,
          attempt: p.attempt,
          willRetry: p.will_retry,
        };
      } else if ("duration_ms" in payload) {
        // NodeCompletedPayload
        const p = payload as unknown as NodeCompletedPayload;
        nodes[p.node_id] = {
          ...nodes[p.node_id],
          id: p.node_id,
          name: p.agent_name,
          status: "success",
          durationMs: p.duration_ms,
          tokenUsage: p.token_usage,
        };
      } else {
        // NodeStartedPayload
        const p = payload as unknown as NodeStartedPayload;
        nodes[p.node_id] = {
          id: p.node_id,
          name: p.agent_name,
          status: "running",
          attempt: p.attempt,
          tools: p.tools,
          model: p.model,
        };
      }

      _cache[wid] = { ...snap, nodes };
      set({ _cache });
    },

    setActiveWid: (wid) => {
      const cache = { ...get()._cache };
      const currentWid = get().workflowId;
      if (currentWid) {
        cache[currentWid] = {
          nodes: get().nodes,
          status: get().status,
          workflowId: get().workflowId,
          workflowName: get().workflowName,
          dag: get().dag,
          envelope: get().envelope,
        };
      }
      if (wid && cache[wid]) {
        const snap = cache[wid];
        set({
          nodes: snap.nodes,
          status: snap.status,
          workflowId: snap.workflowId,
          workflowName: snap.workflowName,
          dag: snap.dag,
          envelope: snap.envelope,
          _cache: cache,
        });
      } else {
        set({
          nodes: {},
          status: "idle" as const,
          workflowId: wid,
          workflowName: null,
          dag: null,
          envelope: null,
          _cache: cache,
        });
      }
    },

    clearCache: () => set({ _cache: {} }),
  }));
}

// ============================================================
// Chart Store
// ============================================================
export function createChartStore(
  workflowId: string,
): StoreApi<ChartState> {
  const initialState: ChartState = {
    groups: {},
    groupOrder: [],

    addChart: (payload) => {
      /* Phase 2 实现 */
    },
    toggleCollapse: (label) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },
  };

  return createStore<ChartState>()((set, get) => ({
    ...initialState,

    addChart: (payload) =>
      set((state) => {
        const { label, title, chart_type, category } = payload;

        // Ensure group exists
        const groupExists = label in state.groups;
        const group: ChartGroup = groupExists
          ? { ...state.groups[label] }
          : { label, collapsed: false, category, charts: {}, table: null };

        // chart_type="table" stored as group's table (one per group max)
        if (chart_type === "table") {
          group.table = { columns: payload.columns, rows: payload.data };
        } else {
          // Same label + same title replaces existing chart (live update)
          group.charts = { ...group.charts, [title]: payload };
        }

        const newGroups = { ...state.groups, [label]: group };
        const newOrder = groupExists
          ? state.groupOrder
          : [...state.groupOrder, label];

        return { groups: newGroups, groupOrder: newOrder };
      }),

    toggleCollapse: (label) =>
      set((state) => {
        if (!(label in state.groups)) return state;
        return {
          groups: {
            ...state.groups,
            [label]: { ...state.groups[label], collapsed: !state.groups[label].collapsed },
          },
        };
      }),

    reset: () => set({ groups: {}, groupOrder: [] }),
  }));
}

// ============================================================
// Tool Call Store
// ============================================================
export function createToolCallStore(
  workflowId: string,
): StoreApi<ToolCallState> {
  const tcCounter = createToolCallCounter();

  const initialState: ToolCallState = {
    records: {},
    order: [],

    addToolCall: (id, nodeId, agentName, toolName, args) => {
      /* Phase 2 实现 */
    },
    addToolResult: (id, result) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },
  };

  const store = createStore<ToolCallState>()((set, get) => ({
    ...initialState,

    addToolCall: (id, nodeId, agentName, toolName, args) => {
      if (id in get().records) return;
      set((state) => ({
        records: {
          ...state.records,
          [id]: {
            id,
            nodeId,
            agentName,
            toolName,
            args,
            timestamp: Date.now(),
          },
        },
        order: [...state.order, id],
      }));
    },

    addToolResult: (id, result) => {
      const record = get().records[id];
      if (!record) return;
      set((state) => ({
        records: {
          ...state.records,
          [id]: { ...record, result },
        },
      }));
    },

    reset: () => set({ records: {}, order: [] }),
  }));

  (store as unknown as { _tcCounter: ToolCallCounter })._tcCounter = tcCounter;

  return store;
}

// ============================================================
// Agent IO Store
// ============================================================
export function createAgentIOStore(
  workflowId: string,
): StoreApi<AgentIOState> {
  const initialState: AgentIOState = {
    data: {},

    setAgentIO: (nodeId, inputPrompt, outputResult, systemPrompt) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },
  };

  return createStore<AgentIOState>()((set) => ({
    ...initialState,

    setAgentIO: (nodeId, inputPrompt, outputResult, systemPrompt) =>
      set((state) => ({
        data: {
          ...state.data,
          [nodeId]: {
            inputPrompt,
            outputResult,
            systemPrompt,
          },
        },
      })),

    reset: () => set({ data: {} }),
  }));
}

// ============================================================
// Chat Store
// ============================================================
export function createChatStore(
  workflowId: string,
): StoreApi<ChatState> {
  const initialState: ChatState = {
    messages: [],
    pendingQuestionId: null,

    addAgentQuestion: (questionId, question) => {
      /* Phase 2 实现 */
    },
    addUserAnswer: (questionId, answer) => {
      /* Phase 2 实现 */
    },
    reset: () => {
      /* Phase 2 实现 */
    },
  };

  return createStore<ChatState>()((set) => ({
    ...initialState,

    addAgentQuestion: (questionId, question) =>
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: `chat-${questionId}`,
            role: "agent",
            content: question,
            questionId,
            timestamp: Date.now(),
          },
        ],
        pendingQuestionId: questionId,
      })),

    addUserAnswer: (questionId, answer) =>
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: `chat-answer-${questionId}`,
            role: "user",
            content: answer,
            questionId,
            timestamp: Date.now(),
          },
        ],
        pendingQuestionId: null,
      })),

    reset: () => set({ messages: [], pendingQuestionId: null }),
  }));
}

// ============================================================
// Span Store
// ============================================================
export function createSpanStore(
  workflowId: string,
): StoreApi<import("@/stores/spanStore").SpanState> {
  const initialState: import("@/stores/spanStore").SpanState = {
    spans: {},
    workflowStartTs: null,

    startSpan: (payload) => {
      /* Phase 2 实现 */
    },
    endSpan: (spanId, ts) => {
      /* Phase 2 实现 */
    },
    setWorkflowStartTs: (ts) => {
      /* Phase 2 实现 */
    },
    computeWaterfallData: () => [],
    reset: () => {
      /* Phase 2 实现 */
    },
  };

  return createStore<import("@/stores/spanStore").SpanState>()((set, get) => ({
    ...initialState,

    startSpan: (payload) =>
      set((state) => ({
        spans: {
          ...state.spans,
          [payload.span_id]: {
            spanId: payload.span_id,
            agentName: payload.agent_name,
            spanType: payload.span_type,
            startTs: payload.ts,
            endTs: null,
            model: payload.model,
            toolName: payload.tool_name,
          },
        },
      })),

    endSpan: (spanId, ts) => {
      const span = get().spans[spanId];
      if (!span) return;
      set((state) => ({
        spans: {
          ...state.spans,
          [spanId]: { ...span, endTs: ts },
        },
      }));
    },

    setWorkflowStartTs: (ts) => set({ workflowStartTs: ts }),

    computeWaterfallData: () => {
      const { spans, workflowStartTs } = get();
      if (!workflowStartTs) return [];

      const rows: import("@/stores/spanStore").WaterfallRow[] = [];
      for (const span of Object.values(spans)) {
        if (span.endTs === null) continue;
        rows.push({
          agent: span.agentName,
          start_ms: Math.max(0, span.startTs - workflowStartTs),
          duration_ms: span.endTs - span.startTs,
          kind: span.spanType,
          label: span.spanType === "llm" ? (span.model ?? "LLM") : (span.toolName ?? "tool"),
        });
      }
      return rows;
    },

    reset: () => set({ spans: {}, workflowStartTs: null }),
  }));
}

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
  chat: StoreApi<ChatState>;
  span: StoreApi<import("@/stores/spanStore").SpanState>;
}

export function createWorkflowStores(workflowId: string): WorkflowStores {
  return {
    conversation: createConversationStore(workflowId),
    output: createOutputStore(workflowId),
    workflow: createWorkflowStore(workflowId),
    chart: createChartStore(workflowId),
    toolCall: createToolCallStore(workflowId),
    agentIO: createAgentIOStore(workflowId),
    chat: createChatStore(workflowId),
    span: createSpanStore(workflowId),
  };
}

/**
 * 访问 store 内部计数器的辅助函数
 */
export function getMessageCounter(store: StoreApi<ConversationState>): MessageCounter {
  return (store as unknown as { _msgCounter: MessageCounter })._msgCounter;
}

export function getToolCallCounter(store: StoreApi<ToolCallState>): ToolCallCounter {
  return (store as unknown as { _tcCounter: ToolCallCounter })._tcCounter;
}