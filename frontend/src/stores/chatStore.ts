import { create } from "zustand";

export interface ChatMessage {
  id: string;
  role: "agent" | "user";
  content: string;
  questionId?: string;
  timestamp: number;
}

export interface ChatState {
  messages: ChatMessage[];
  pendingQuestionId: string | null;

  // Actions
  addAgentQuestion: (questionId: string, question: string) => void;
  addUserAnswer: (questionId: string, answer: string) => void;
  reset: () => void;
}

const initialState = {
  messages: [] as ChatMessage[],
  pendingQuestionId: null as string | null,
};

export const useChatStore = create<ChatState>()((set) => ({
  ...initialState,

  addAgentQuestion: (questionId, question) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: `agent-${questionId}`,
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
          id: `user-${questionId}`,
          role: "user",
          content: answer,
          questionId,
          timestamp: Date.now(),
        },
      ],
      // Clear pending only if this answers the current pending question
      pendingQuestionId:
        state.pendingQuestionId === questionId
          ? null
          : state.pendingQuestionId,
    })),

  reset: () => set(initialState),
}));
