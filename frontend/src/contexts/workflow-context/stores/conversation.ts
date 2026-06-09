import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { ConversationState, ConversationMessage } from "@/stores/conversationStore";
import { createIdCounter, type IdCounter } from "@/lib/idCounter";
import { createRafBatcher, type RafBatcher } from "@/lib/rafBatcher";
import { withCache, type StoreCache, type WithCacheOptions } from "@/lib/storeCache";

type ConversationCacheSnap = {
  messages: ConversationMessage[];
  pendingQuestionId: string | null;
  pendingQuestionAgent: string | null;
};

export interface ConversationStoreOptions {
  /**
   * Called when a state mutation happens that should be flushed to the
   * backend before workflow termination (so refresh doesn't lose state).
   * The store debounces calls by 500ms to coalesce rapid mutations.
   * Implementation is provided by WorkflowManager.
   */
  onPersist?: () => void;
}

const PERSIST_DEBOUNCE_MS = 500;

export function createConversationStore(
  workflowId: string,
  options: ConversationStoreOptions = {},
): StoreApi<ConversationState> {
  const msgCounter = createIdCounter("msg-");

  // Debounced persist trigger — coalesces rapid mutations (e.g. user
  // answering multiple questions in quick succession) into a single
  // PATCH /api/runs/{id}/conversation call.
  let persistTimer: ReturnType<typeof setTimeout> | null = null;
  const schedulePersist = () => {
    if (!options.onPersist) return;
    if (persistTimer) clearTimeout(persistTimer);
    persistTimer = setTimeout(() => {
      persistTimer = null;
      options.onPersist?.();
    }, PERSIST_DEBOUNCE_MS);
  };

  // Cache helper is assigned after the store is created.
  let cache: StoreCache;

  // Batchers are created after store so they can call store.setState.
  let textBatcher: RafBatcher<string, { text: string; nodeId: string }>;
  let thinkBatcher: RafBatcher<string, { text: string; nodeId: string }>;
  let flushTextBuf: () => void;

  // Only the data fields — method implementations live in createStore below
  // and override anything present here. Type is inferred from the literal so
  // we don't need no-op stubs for every action just to satisfy the type.
  const initialState = {
    messages: [] as ConversationMessage[],
    pendingQuestionId: null as string | null,
    pendingQuestionAgent: null as string | null,
    activeFollowupAgent: null as string | null,

    // Cache management (保留用于 batch 模式兼容)
    _cache: {} as ConversationState["_cache"],
    _activeWid: null as string | null,
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

    appendAgentText: (nodeId, text) => {
      textBatcher.push(nodeId, { text, nodeId }, (prev, next) => ({
        text: prev.text + next.text,
        nodeId: prev.nodeId,
      }));
    },

    appendAgentThinking: (nodeId, text) => {
      thinkBatcher.push(nodeId, { text, nodeId }, (prev, next) => ({
        text: prev.text + next.text,
        nodeId: prev.nodeId,
      }));
    },

    completeAgentMessage: (nodeId, agentName, durationMs) => {
      flushTextBuf(); // sync-flush buffered text before finalizing
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
      });
    },

    failAgentMessage: (nodeId, agentName, error, durationMs) => {
      flushTextBuf();
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
      });
    },

    addToolCall: (nodeId, agentName, toolName, toolArgs) => {
      flushTextBuf();
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
      });
    },

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
            type: "question",
            content: question,
            agentName,
            status: "pending",
            timestamp: Date.now(),
            questionId,
            questionHeader: null,
            questionOptions: null,
            questionMultiSelect: false,
            questionAllowCustomInput: true,
            questionInputType: "textarea",
            questionInputPlaceholder: null,
          },
        ],
      })),

    addUserQuestion: (payload) =>
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: `msg-${msgCounter.next()}`,
            type: "question",
            content: payload.question,
            agentName: payload.agent_name ?? "agent",
            nodeId: payload.node_id,
            status: "pending",
            timestamp: Date.now(),
            questionId: payload.question_id,
            questionHeader: payload.header ?? null,
            questionOptions: payload.options ?? null,
            questionMultiSelect: payload.multi_select ?? false,
            questionAllowCustomInput: payload.allow_custom_input ?? true,
            questionInputType: payload.input_type ?? "text",
            questionInputPlaceholder: payload.input_placeholder ?? null,
          },
        ],
      })),

    answerUserQuestion: (questionId, answer) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) => m.type === "question" && m.questionId === questionId && m.status === "pending",
        );
        if (idx === -1) return state;
        const messages = [...state.messages];
        messages[idx] = {
          ...messages[idx],
          status: "answered",
          questionAnswer: answer,
        };
        schedulePersist();
        return { messages };
      }),

    markQuestionTimeout: (questionId) =>
      set((state) => {
        const idx = state.messages.findLastIndex(
          (m) => m.type === "question" && m.questionId === questionId && m.status === "pending",
        );
        if (idx === -1) return state;
        const messages = [...state.messages];
        messages[idx] = { ...messages[idx], status: "timeout" };
        const clear = state.pendingQuestionId === questionId
          ? { pendingQuestionId: null, pendingQuestionAgent: null }
          : {};
        schedulePersist();
        return { messages, ...clear };
      }),

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
      set({ messages: [], pendingQuestionId: null, pendingQuestionAgent: null, activeFollowupAgent: null }),

    saveToCache: (wid) => cache.saveToCache(wid),

    restoreFromCache: (wid) => cache.restoreFromCache(wid),

    setActiveWid: (wid) => cache.setActiveWid(wid),

    clearCache: () => cache.clearCache(),

    appendAgentTextToCache: (wid, nodeId, text, agentName) => {
      const existing = cache.getCacheForWid(wid);
      const base = (existing ??
        (cache.setCacheForWid(wid, {
          messages: [],
          pendingQuestionId: null,
          pendingQuestionAgent: null,
        }) as ConversationCacheSnap)) as ConversationCacheSnap;

      const messages = [...base.messages]; // immutable copy
      const idx = messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming",
      );
      if (idx !== -1) {
        messages[idx] = { ...messages[idx], content: messages[idx].content + text };
      } else {
        messages.push({
          id: `msg-${msgCounter.next()}`,
          type: "agent",
          nodeId,
          agentName: agentName || "",
          content: text,
          status: "streaming",
          timestamp: Date.now(),
        });
      }
      cache.setCacheForWid(wid, { ...base, messages });
    },

    addToolCallToCache: (wid, nodeId, agentName, toolName, toolArgs) => {
      const existing = cache.getCacheForWid(wid);
      const base = (existing ??
        (cache.setCacheForWid(wid, {
          messages: [],
          pendingQuestionId: null,
          pendingQuestionAgent: null,
        }) as ConversationCacheSnap)) as ConversationCacheSnap;

      const messages = [
        ...base.messages,
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
      cache.setCacheForWid(wid, { ...base, messages });
    },

    addToolResultToCache: (wid, nodeId, toolName, result) => {
      const existing = cache.getCacheForWid(wid);
      const base = (existing ??
        (cache.setCacheForWid(wid, {
          messages: [],
          pendingQuestionId: null,
          pendingQuestionAgent: null,
        }) as ConversationCacheSnap)) as ConversationCacheSnap;

      const messages = [...base.messages]; // immutable copy
      const idx = messages.findLastIndex(
        (m) =>
          m.nodeId === nodeId &&
          m.type === "tool_call" &&
          m.toolName === toolName &&
          m.toolResult === undefined,
      );
      if (idx !== -1) {
        const msg = messages[idx];
        const elapsed = msg.timestamp ? Date.now() - msg.timestamp : undefined;
        messages[idx] = {
          ...msg,
          toolResult: result,
          toolStatus: "done",
          toolDurationMs: elapsed,
        };
        cache.setCacheForWid(wid, { ...base, messages });
      }
    },

    // Follow-up actions
    setActiveFollowupAgent: (name) => set({ activeFollowupAgent: name }),

    addFollowupUserMessage: (agentName, content) =>
      set((state) => ({
        messages: [
          ...state.messages,
          {
            id: `msg-${msgCounter.next()}`,
            type: "user",
            content,
            agentName,
            nodeId: `followup-${agentName}`,
            followup: true,
            timestamp: Date.now(),
          },
        ],
      })),

    addFollowupAgentMessage: (agentName) =>
      set((state) => {
        const nodeId = `followup-${agentName}`;
        const streamingIdx = state.messages.findLastIndex(
          (m) => m.nodeId === nodeId && m.status === "streaming" && m.followup
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
              followup: true,
              timestamp: Date.now(),
            },
          ],
        };
      }),
  }));

  (store as unknown as { _msgCounter: IdCounter })._msgCounter = msgCounter;

  // ConversationState lacks a string index signature, but withCache only relies
  // on its internal _cache/_activeWid plumbing and casts internally — so widen
  // the store to satisfy the Record<string, unknown> constraint without
  // touching the typed ConversationState interface. The options callbacks stay
  // typed against ConversationState for snapshot correctness.
  const cacheOptions: WithCacheOptions<ConversationState> = {
    extractSnapshot: (s) => ({
      messages: s.messages,
      pendingQuestionId: s.pendingQuestionId,
      pendingQuestionAgent: s.pendingQuestionAgent,
    }),
    applySnapshot: (_s, snap) => ({
      messages: (snap.messages as ConversationMessage[]) ?? [],
      pendingQuestionId: (snap.pendingQuestionId as string | null) ?? null,
      pendingQuestionAgent: (snap.pendingQuestionAgent as string | null) ?? null,
    }),
    makeEmptySnapshot: () => ({
      messages: [],
      pendingQuestionId: null,
      pendingQuestionAgent: null,
    }),
  };
  cache = withCache(
    store as unknown as StoreApi<Record<string, unknown>>,
    cacheOptions as unknown as WithCacheOptions<Record<string, unknown>>,
  );

  // Initialize batchers with store.setState now that store exists.
  textBatcher = createRafBatcher<string, { text: string; nodeId: string }>(
    (updates) => {
      store.setState((state) => {
        const messages = [...state.messages];
        let mutated = false;
        updates.forEach(({ nodeId: nid, text: t }) => {
          const idx = messages.findLastIndex(
            (m) => m.nodeId === nid && m.type === "agent" && m.status === "streaming"
          );
          if (idx !== -1) {
            messages[idx] = { ...messages[idx], content: messages[idx].content + t };
            mutated = true;
          } else {
            const lastMsg = messages[messages.length - 1];
            const agentName = lastMsg?.agentName ?? "";
            messages.push({
              id: msgCounter.next(),
              type: "agent",
              nodeId: nid,
              agentName,
              content: t,
              status: "streaming",
              timestamp: Date.now(),
            });
            mutated = true;
          }
        });
        return mutated ? { messages } : state;
      });
    },
  );

  thinkBatcher = createRafBatcher<string, { text: string; nodeId: string }>(
    (updates) => {
      store.setState((state) => {
        const messages = [...state.messages];
        let mutated = false;
        updates.forEach(({ nodeId: nid, text: t }) => {
          const idx = messages.findLastIndex(
            (m) => m.nodeId === nid && m.type === "agent" && m.status === "streaming"
          );
          if (idx !== -1) {
            messages[idx] = { ...messages[idx], thinking: (messages[idx].thinking ?? "") + t };
            mutated = true;
          }
        });
        return mutated ? { messages } : state;
      });
    },
  );

  flushTextBuf = () => textBatcher.flush();

  return store;
}
