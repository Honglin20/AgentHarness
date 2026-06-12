import { create } from "zustand";

export interface QuestionOption {
  label: string;
  description?: string | null;
  value?: string | null;
}

export interface QuestionAnswer {
  selected: string[];
  customInput: string;
}

export interface ConversationMessage {
  id: string;
  type: "agent" | "user" | "tool_call" | "system" | "question";
  nodeId?: string;
  agentName?: string;
  content: string;
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: string;
  status?: "streaming" | "done" | "error" | "interrupted" | "pending" | "answered" | "timeout";
  /** For tool_call messages: "running" while tool executes, "done" when result arrives */
  toolStatus?: "running" | "done";
  toolDurationMs?: number;
  /** Intermediate output accumulated during bash execution */
  toolStreamingOutput?: string;
  /** Model's internal reasoning/thinking text (e.g. DeepSeek think process) */
  thinking?: string;
  durationMs?: number;
  timestamp: number;
  /**
   * ID of the TODO step this message belongs to. Set when the message is
   * created by reading `currentStepIdByNode[nodeId]` — i.e. the most
   * recent step that went `in_progress` on this node. Undefined when the
   * node has no active step (no todo tool usage, or step not yet started).
   *
   * Used by the conversation UI to group agent details under StepRows.
   */
  stepId?: string;

  /**
   * Which loop iteration of this node produced the message. 1-indexed.
   * Undefined for legacy data (treated as iteration 1 by consumers) and
   * for messages that aren't part of a node (system, user-typed).
   *
   * Stamped at creation time from `currentIterationByNode[nodeId]` — same
   * pattern as `stepId`. The state map + `setCurrentIteration` action
   * arrive in later tasks of the same plan; this field is the type-level
   * foundation that lets them stamp without further interface changes.
   */
  iteration?: number;

  // ── question-specific fields (type === "question") ──
  questionId?: string;
  questionHeader?: string | null;
  questionOptions?: QuestionOption[] | null;
  questionMultiSelect?: boolean;
  questionAllowCustomInput?: boolean;
  questionInputType?: "text" | "number" | "url" | "textarea";
  questionInputPlaceholder?: string | null;
  questionAnswer?: QuestionAnswer;

  // ── follow-up fields ──
  followup?: boolean;
}

export interface AgentQuestionPayload {
  question_id: string;
  agent_name?: string;
  node_id?: string;
  question: string;
  header?: string | null;
  options?: QuestionOption[] | null;
  multi_select?: boolean;
  allow_custom_input?: boolean;
  input_type?: "text" | "number" | "url" | "textarea";
  input_placeholder?: string | null;
}

export interface ConversationState {
  messages: ConversationMessage[];
  pendingQuestionId: string | null;
  pendingQuestionAgent: string | null;
  activeFollowupAgent: string | null;

  /**
   * nodeId → most recent TODO step that entered `in_progress` on this node.
   * Read by all add* actions to stamp `stepId` onto newly-created messages
   * so the conversation UI can group agent details under the right StepRow.
   *
   * Updated by `setCurrentStep` (called from todoHandlers on todo.updated
   * status=in_progress or auto_advance). **Never explicitly cleared** —
   * not on status=completed (so trailing agent output still tags to the
   * last step), not on node termination. The map is wiped only by
   * `reset()` (workflow switch / new run).
   *
   * Low-risk leak: if a DAG reuses a nodeId across instances (rare), the
   * second instance would inherit the first's stepId. Acceptable because
   * nodeId is typically unique per node instance in current architecture.
   */
  currentStepIdByNode: Record<string, string>;

  /**
   * nodeId → current loop iteration for that node. 1-indexed.
   *
   * **Cache, not counter** (Plan F): the value is hydrated from the
   * `node.started` event payload (backend-owned `node_invocation_counts`
   * state field). Frontend `setCurrentIteration` writes whatever the
   * event carried — no `+ 1` increment on the frontend.
   *
   * Each new message created on this node stamps `iteration` from this
   * cache at message-creation time. Pre-Plan-F replays (events without
   * `iteration`) default to 1 via the `?? 1` fallback in nodeHandlers.
   *
   * Not restored by `restoreFromCache` — acceptable because a restored
   * workflow's existing messages already carry their stamped `iteration`,
   * and the cache only matters for stamping *new* messages (which require
   * a fresh `node.started` to repopulate the cache anyway).
   */
  currentIterationByNode: Record<string, number>;

  // Per-workflow cache for batch mode
  _cache: Record<string, { messages: ConversationMessage[]; pendingQuestionId: string | null; pendingQuestionAgent: string | null }>;
  _activeWid: string | null;

  // Actions
  addSystemMessage: (content: string) => void;
  addAgentMessage: (nodeId: string, agentName: string) => void;
  appendAgentText: (nodeId: string, text: string) => void;
  appendAgentThinking: (nodeId: string, text: string) => void;
  completeAgentMessage: (nodeId: string, agentName: string, durationMs?: number) => void;
  failAgentMessage: (nodeId: string, agentName: string, error: string, durationMs?: number) => void;
  addToolCall: (nodeId: string, agentName: string, toolName: string, toolArgs: Record<string, unknown>) => void;
  addToolResult: (nodeId: string, toolName: string, result: string) => void;
  appendToolOutput: (nodeId: string, toolName: string, line: string, stream: string) => void;
  addUserQuestion: (payload: AgentQuestionPayload) => void;
  answerUserQuestion: (questionId: string, answer: QuestionAnswer) => void;
  /**
   * Mark `stepId` as the active step for `nodeId`. Subsequent messages on
   * that node will be tagged with this stepId. Pass null to clear (used
   * on node termination / reset).
   */
  setCurrentStep: (nodeId: string, stepId: string | null) => void;
  setCurrentIteration: (nodeId: string, iteration: number) => void;
  markQuestionTimeout: (questionId: string) => void;
  /**
   * Mark every still-pending question as "interrupted". Called when the
   * workflow terminates (completed/error/cancelled) so the UI doesn't keep
   * showing a "select an option" prompt that can no longer affect anything.
   * Persists the change so refresh sees the interrupted state too.
   */
  markAllPendingQuestionsInterrupted: () => void;
  addUserMessage: (content: string) => void;
  clearPendingQuestion: (questionId: string) => void;
  interruptAgentMessage: (agentName: string) => void;
  resumeAgentMessage: (nodeId: string, agentName: string) => void;
  reset: () => void;

  // Follow-up actions
  setActiveFollowupAgent: (name: string | null) => void;
  addFollowupUserMessage: (agentName: string, content: string) => void;
  addFollowupAgentMessage: (agentName: string) => void;

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

// RAF batching for streaming text updates — coalesces multiple deltas per frame
let _textBuf = new Map<string, { text: string; nodeId: string }>();
let _rafSeq = 0; // monotonic counter to invalidate stale RAF callbacks
let _rafPending = false;

const initialState = {
  messages: [] as ConversationMessage[],
  pendingQuestionId: null as string | null,
  pendingQuestionAgent: null as string | null,
  activeFollowupAgent: null as string | null,
  currentStepIdByNode: {} as Record<string, string>,
  currentIterationByNode: {} as Record<string, number>,
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

  appendAgentText: (nodeId, text) => {
    const existing = _textBuf.get(nodeId);
    _textBuf.set(nodeId, { text: (existing?.text ?? "") + text, nodeId });
    if (!_rafPending) {
      _rafPending = true;
      const rafSeq = ++_rafSeq;
      requestAnimationFrame(() => {
        if (rafSeq !== _rafSeq) return; // stale — sync flush already applied this text
        const updates = new Map(_textBuf);
        _textBuf.clear();
        _rafPending = false;
        if (updates.size === 0) return;
        set((state) => {
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
              // Auto-create streaming message
              const lastMsg = messages[messages.length - 1];
              const agentName = lastMsg?.agentName ?? "";
              messages.push({
                id: `msg-${++msgCounter}`,
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
      });
    }
  },

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
      // Sync flush any pending RAF text for this nodeId before completing
      const pending = _textBuf.get(nodeId);
      if (pending) _textBuf.delete(nodeId);
      _rafSeq++; // invalidate any pending RAF callback

      const idx = state.messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")
      );
      if (idx === -1) return state;

      const messages = [...state.messages];
      messages[idx] = {
        ...messages[idx],
        content: messages[idx].content + (pending?.text ?? ""),
        agentName,
        status: "done",
        durationMs,
      };
      return { messages };
    }),

  failAgentMessage: (nodeId, agentName, error, durationMs) =>
    set((state) => {
      // Sync flush any pending RAF text for this nodeId before failing
      const pending = _textBuf.get(nodeId);
      if (pending) _textBuf.delete(nodeId);
      _rafSeq++; // invalidate any pending RAF callback

      const idx = state.messages.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && (m.status === "streaming" || m.status === "interrupted")
      );
      if (idx === -1) return state;

      const messages = [...state.messages];
      messages[idx] = {
        ...messages[idx],
        content: messages[idx].content + (pending?.text ?? "") + `\n\n**Error:** ${error}`,
        agentName,
        status: "error",
        durationMs,
      };
      return { messages };
    }),

  addToolCall: (nodeId, agentName, toolName, toolArgs) =>
    set((state) => {
      // Sync flush any pending RAF text for this nodeId
      const pending = _textBuf.get(nodeId);
      if (pending) _textBuf.delete(nodeId);
      _rafSeq++; // invalidate any pending RAF callback

      // Finalize any streaming agent message for this node — the text before
      // this tool call becomes its own message, and continued text after the
      // tool result will start a new streaming message.
      let msgs = [...state.messages];
      const streamingIdx = msgs.findLastIndex(
        (m) => m.nodeId === nodeId && m.type === "agent" && m.status === "streaming"
      );
      if (streamingIdx !== -1) {
        // Flush pending text into the streaming message before finalizing
        msgs[streamingIdx] = {
          ...msgs[streamingIdx],
          content: msgs[streamingIdx].content + (pending?.text ?? ""),
        };
        if (!msgs[streamingIdx].content.trim() && !msgs[streamingIdx].thinking?.trim()) {
          // No text was written before this tool call — remove the empty
          // placeholder so the final output (from node.completed) appears
          // AFTER the tool calls instead of before them.
          msgs.splice(streamingIdx, 1);
        } else {
          msgs[streamingIdx] = { ...msgs[streamingIdx], status: "done" as const };
        }
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

  addUserQuestion: (payload) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: `msg-${++msgCounter}`,
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
      return { messages };
    }),

  markAllPendingQuestionsInterrupted: () =>
    set((state) => {
      let touched = false;
      const messages = state.messages.map((m) => {
        if (m.type === "question" && m.status === "pending") {
          touched = true;
          return { ...m, status: "interrupted" as const };
        }
        return m;
      });
      if (!touched && state.pendingQuestionId === null) return state;
      return {
        messages,
        pendingQuestionId: null,
        pendingQuestionAgent: null,
      };
    }),

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
    return set({ ...initialState, _cache: {}, _activeWid: null, currentStepIdByNode: {}, currentIterationByNode: {} });
  },

  setCurrentStep: (nodeId, stepId) =>
    set((state) => {
      if (stepId === null) {
        if (!(nodeId in state.currentStepIdByNode)) return state;
        const next = { ...state.currentStepIdByNode };
        delete next[nodeId];
        return { currentStepIdByNode: next };
      }
      if (state.currentStepIdByNode[nodeId] === stepId) return state;
      return {
        currentStepIdByNode: { ...state.currentStepIdByNode, [nodeId]: stepId },
      };
    }),

  setCurrentIteration: (nodeId, iteration) =>
    set((state) => {
      if (state.currentIterationByNode[nodeId] === iteration) return state;
      return {
        currentIterationByNode: { ...state.currentIterationByNode, [nodeId]: iteration },
      };
    }),

  setActiveFollowupAgent: (name) => set({ activeFollowupAgent: name }),

  addFollowupUserMessage: (agentName, content) =>
    set((state) => ({
      messages: [
        ...state.messages,
        {
          id: `msg-${++msgCounter}`,
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
            id: `msg-${++msgCounter}`,
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
