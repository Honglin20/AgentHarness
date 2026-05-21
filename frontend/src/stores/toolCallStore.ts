import { create } from "zustand";

export interface ToolCallRecord {
  id: string;
  nodeId: string;
  agentName: string;
  toolName: string;
  args: Record<string, unknown>;
  result?: string;
  timestamp: number;
}

export interface ToolCallState {
  // Records keyed by id
  records: Record<string, ToolCallRecord>;
  // Order of insertion
  order: string[];

  // Actions
  addToolCall: (id: string, nodeId: string, agentName: string, toolName: string, args: Record<string, unknown>) => void;
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

  addToolCall: (id, nodeId, agentName, toolName, args) =>
    set((state) => {
      const record: ToolCallRecord = {
        id,
        nodeId,
        agentName,
        toolName,
        args,
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
