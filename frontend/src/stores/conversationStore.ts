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
  status?: "streaming" | "done" | "error";
  durationMs?: number;
  timestamp: number;
}

export interface ConversationState {
  messages: ConversationMessage[];
  pendingQuestionId: string | null;
  pendingQuestionAgent: string | null;

  // Actions
  addSystemMessage: (content: string) => void;
  addAgentMessage: (nodeId: string, agentName: string) => void;
  appendAgentText: (nodeId: string, text: string) => void;
  completeAgentMessage: (nodeId: string, agentName: string, durationMs?: number) => void;
  failAgentMessage: (nodeId: string, agentName: string, error: string, durationMs?: number) => void;
  addToolCall: (nodeId: string, agentName: string, toolName: string, toolArgs: Record<string, unknown>) => void;
  addToolResult: (nodeId: string, toolName: string, result: string) => void;
  addAgentQuestion: (questionId: string, question: string, agentName: string) => void;
  addUserMessage: (content: string) => void;
  clearPendingQuestion: (questionId: string) => void;
  reset: () => void;
}

let msgCounter = 0;

const initialState = {
  messages: [] as ConversationMessage[],
  pendingQuestionId: null as string | null,
  pendingQuestionAgent: null as string | null,
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
      if (idx === -1) return state;

      const messages = [...state.messages];
      messages[idx] = { ...messages[idx], content: messages[idx].content + text };
      return { messages };
    }),

  completeAgentMessage: (nodeId, agentName, durationMs) =>
    set((state) => {
      const idx = state.messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
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
        (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
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
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: `msg-${++msgCounter}`,
          type: "tool_call",
          nodeId,
          agentName,
          content: "",
          toolName,
          toolArgs,
          timestamp: Date.now(),
        },
      ],
    })),

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
      messages[idx] = { ...messages[idx], toolResult: result };
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

  reset: () => {
    msgCounter = 0;
    return set(initialState);
  },
}));
