import { create } from "zustand";

export interface ConversationMessage {
  id: string;
  type: "agent" | "user" | "tool_call" | "system";
  nodeId?: string;
  agentName?: string;
  content: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: string;
  status?: "streaming" | "done" | "error" | "interrupted";
  /** For tool_call messages: "running" while tool executes, "done" when result arrives */
  toolStatus?: "running" | "done";
  toolDurationMs?: number;
  /** Intermediate output accumulated during bash execution */
  toolStreamingOutput?: string;
  durationMs?: number;
  timestamp: number;
}

export interface ConversationState {
  messages: ConversationMessage[];
  pendingQuestionId: string | null;
  pendingQuestionAgent: string | null;

  // Per-workflow cache for batch mode
  _cache: Record<string, { messages: ConversationMessage[]; pendingQuestionId: string | null; pendingQuestionAgent: string | null }>;
  _activeWid: string | null;

  // Actions
  addSystemMessage: (content: string) => void;
  addAgentMessage: (nodeId: string, agentName: string) => void;
  appendAgentText: (nodeId: string, text: string) => void;
  completeAgentMessage: (nodeId: string, agentName: string, durationMs?: number) => void;
  failAgentMessage: (nodeId: string, agentName: string, error: string, durationMs?: number) => void;
  addToolCall: (nodeId: string, agentName: string, toolName: string, toolArgs: Record<string, unknown>) => void;
  addToolResult: (nodeId: string, toolName: string, result: string) => void;
  appendToolOutput: (nodeId: string, toolName: string, line: string, stream: string) => void;
  addAgentQuestion: (questionId: string, question: string, agentName: string) => void;
  addUserMessage: (content: string) => void;
  clearPendingQuestion: (questionId: string) => void;
  interruptAgentMessage: (agentName: string) => void;
  resumeAgentMessage: (nodeId: string, agentName: string) => void;
  reset: () => void;

  // Cache management for batch mode
  saveToCache: (wid: string) => void;
  restoreFromCache: (wid: string) => boolean;
  setActiveWid: (wid: string | null) => void;
  clearCache: () => void;
  appendAgentTextToCache: (wid: string, nodeId: string, text: string, agentName: string) => void;
  addToolCallToCache: (wid: string, nodeId: string, agentName: string, toolName: string, toolArgs: Record<string, unknown>) => void;
  addToolResultToCache: (wid: string, nodeId: string, toolName: string, result: string) => void;
}

let msgCounter = 0;

const initialState = {
  messages: [] as ConversationMessage[],
  pendingQuestionId: null as string | null,
  pendingQuestionAgent: null as string | null,
  _cache: {} as Record<string, { messages: ConversationMessage[]; pendingQuestionId: string | null; pendingQuestionAgent: string | null }>,
  _activeWid: null as string | null,
};

export const useConversationStore = create<ConversationState>()((set) => ({
  ...initialState,

  addSystemMessage: (content) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: `msg-${++msgCounter}`,
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
            id: `msg-${++msgCounter}`,
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
            id: `msg-${++msgCounter}`,
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
      // Finalize any streaming agent message for this node — the text before
      // this tool call becomes its own message, and continued text after the
      // tool result will start a new streaming message.
      let msgs = [...state.messages];
      const streamingIdx = msgs.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
      );
      if (streamingIdx !== -1) {
        msgs[streamingIdx] = { ...msgs[streamingIdx], status: "done" as const };
      }

      return {
        messages: [
          ...msgs,
          {
            id: `msg-${++msgCounter}`,
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
          id: `msg-${++msgCounter}`,
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
          id: `msg-${++msgCounter}`,
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

  reset: () => {
    msgCounter = 0;
    return set({ ...initialState, _cache: {}, _activeWid: null });
  },

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
          id: `msg-${++msgCounter}`,
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
          id: `msg-${++msgCounter}`,
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
