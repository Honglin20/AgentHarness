import { create } from "zustand";

export interface ToolCallRecord {
  id: string;
  nodeId: string;
  agentName: string;
  toolName: string;
  args: Record<string, unknown>;
  /**
   * Pydantic-ai ToolCallPart.tool_call_id. Present on records created from
   * real WS tool_call events (the backend always emits it post-fix).
   * Undefined on legacy/historical records. Used by agent.tool_result
   * handler to find the originating record — falling back to name+undefined
   * would re-introduce the parallel-same-name cross-wiring bug.
   */
  toolCallId?: string;
  result?: string;
  timestamp: number;
}

export interface ToolCallState {
  // Records keyed by id
  records: Record<string, ToolCallRecord>;
  // Order of insertion
  order: string[];

  // Actions
  addToolCall: (id: string, nodeId: string, agentName: string, toolName: string, args: Record<string, unknown>, toolCallId: string) => void;
  addToolResult: (id: string, result: string) => void;
  reset: () => void;
}

const initialState = {
  records: {} as Record<string, ToolCallRecord>,
  order: [] as string[],
};

let _nextId = 0;
export function nextToolCallId(): string {
  return `tc-${++_nextId}`;
}

export const useToolCallStore = create<ToolCallState>()((set) => ({
  ...initialState,

  addToolCall: (id, nodeId, agentName, toolName, args, toolCallId) =>
    set((state) => {
      const record: ToolCallRecord = {
        id,
        nodeId,
        agentName,
        toolName,
        args,
        toolCallId,
        timestamp: Date.now(),
      };
      const exists = id in state.records;
      return {
        records: { ...state.records, [id]: record },
        order: exists ? state.order : [...state.order, id],
      };
    }),

  addToolResult: (id, result) =>
    set((state) => {
      const record = state.records[id];
      if (!record) return state;
      return {
        records: {
          ...state.records,
          [id]: { ...record, result },
        },
      };
    }),

  reset: () => {
    _nextId = 0;
    set(initialState);
  },
}));
