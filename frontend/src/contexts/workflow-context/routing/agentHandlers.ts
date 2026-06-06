/**
 * Agent streaming event handlers.
 */

import type { EventHandler } from "./types";
import type {
  AgentTextDeltaPayload,
  AgentToolCallPayload,
  AgentToolResultPayload,
  AgentThinkingDeltaPayload,
  AgentToolOutputDeltaPayload,
} from "@/types/events";
import { payload } from "./utils";

export const agentHandlers: [string, EventHandler][] = [
  [
    "agent.text_delta",
    (stores, event, _ctx) => {
      const p = payload<AgentTextDeltaPayload>(event);
      stores.output.getState().appendText(p.node_id, p.text);
      stores.conversation.getState().appendAgentText(p.node_id, p.text);
    },
  ],

  [
    "agent.thinking_delta",
    (stores, event, _ctx) => {
      const p = payload<AgentThinkingDeltaPayload>(event);
      stores.conversation.getState().appendAgentThinking(p.node_id, p.text);
    },
  ],

  [
    "agent.tool_call",
    (stores, event, ctx) => {
      const p = payload<AgentToolCallPayload>(event);
      const id = ctx.counter.next();
      stores.toolCall
        .getState()
        .addToolCall(id, p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
      stores.conversation
        .getState()
        .addToolCall(p.node_id, p.agent_name, p.tool_name, p.tool_args || {});
    },
  ],

  [
    "agent.tool_result",
    (stores, event, _ctx) => {
      const p = payload<AgentToolResultPayload>(event);
      const store = stores.toolCall.getState();
      const match = store.order
        .map((oid) => store.records[oid])
        .reverse()
        .find(
          (r) =>
            r.nodeId === p.node_id &&
            r.toolName === p.tool_name &&
            r.result === undefined
        );
      if (match) {
        stores.toolCall.getState().addToolResult(match.id, String(p.result ?? ""));
      }
      stores.conversation
        .getState()
        .addToolResult(p.node_id, p.tool_name, String(p.result ?? ""));
    },
  ],

  [
    "agent.tool_output_delta",
    (stores, event, _ctx) => {
      const p = payload<AgentToolOutputDeltaPayload>(event);
      stores.conversation
        .getState()
        .appendToolOutput(p.node_id, p.tool_name, p.line, p.stream);
    },
  ],
];
