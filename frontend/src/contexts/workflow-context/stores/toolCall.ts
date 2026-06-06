import { createStore } from "zustand/vanilla";
import type { StoreApi } from "zustand/vanilla";
import type { ToolCallState } from "@/stores/toolCallStore";
import { createIdCounter, type IdCounter } from "@/lib/idCounter";

export function createToolCallStore(
  workflowId: string,
): StoreApi<ToolCallState> {
  const tcCounter = createIdCounter("tc-");

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

  (store as unknown as { _tcCounter: IdCounter })._tcCounter = tcCounter;

  return store;
}

export function getToolCallCounter(store: StoreApi<ToolCallState>): IdCounter {
  return (store as unknown as { _tcCounter: IdCounter })._tcCounter;
}
