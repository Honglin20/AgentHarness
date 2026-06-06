import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { ChatState } from "@/stores/chatStore";

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
