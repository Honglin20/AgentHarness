/**
 * Node lifecycle event handlers.
 */

import type { EventHandler } from "./types";
import type {
  NodeStartedPayload,
  NodeCompletedPayload,
  NodeFailedPayload,
} from "@/types/events";
import { payload, formatOutputAsMd } from "./utils";

export const nodeHandlers: [string, EventHandler][] = [
  [
    "node.started",
    (stores, event, _ctx) => {
      const p = payload<NodeStartedPayload>(event);
      // Idempotent: skip if node is already tracked and running
      const existingNode = stores.workflow.getState().nodes[p.node_id];
      if (existingNode && existingNode.status === "running") return;

      // Read iteration from the event payload (backend is the source of
      // truth since Plan F). Frontend `currentIterationByNode` is now a
      // cache, not a counter. Falls back to 1 for legacy events emitted
      // before Plan F backend deploy.
      const conv = stores.conversation.getState();
      const iter = (p.iteration as number | undefined) ?? 1;
      conv.setCurrentIteration(p.node_id, iter);

      stores.workflow.getState().handleNodeStarted(p);
      stores.output.getState().setActiveNode(p.node_id);
      stores.conversation.getState().addAgentMessage(p.node_id, p.agent_name);
    },
  ],

  [
    "node.completed",
    (stores, event, _ctx) => {
      const p = payload<NodeCompletedPayload>(event);
      stores.workflow.getState().handleNodeCompleted(p);
      const conversationState = stores.conversation.getState();

      if (p.output_result) {
        const formattedOutput = formatOutputAsMd(p.output_result);
        const idx = conversationState.messages.findLastIndex(
          (m) =>
            m.nodeId === p.node_id &&
            m.type === "agent" &&
            (m.status === "streaming" ||
              m.status === "done" ||
              m.status === "interrupted")
        );
        if (idx !== -1) {
          stores.conversation.setState((state) => {
            const messages = [...state.messages];
            const existing = messages[idx].content.trim();
            messages[idx] = {
              ...messages[idx],
              content: existing
                ? `${existing}\n\n---\n\n${formattedOutput}`
                : formattedOutput,
            };
            return { messages };
          });
        } else {
          conversationState.addAgentMessage(p.node_id, p.agent_name);
          const newState = stores.conversation.getState();
          const newIdx = newState.messages.findLastIndex(
            (m) =>
              m.nodeId === p.node_id &&
              m.type === "agent" &&
              m.status === "streaming"
          );
          if (newIdx !== -1) {
            stores.conversation.setState((state) => {
              const messages = [...state.messages];
              messages[newIdx] = { ...messages[newIdx], content: formattedOutput };
              return { messages };
            });
          }
        }
      }

      conversationState.completeAgentMessage(
        p.node_id,
        p.agent_name,
        p.duration_ms
      );

      if (p.input_prompt || p.output_result || p.system_prompt) {
        stores.agentIO
          .getState()
          .setAgentIO(
            p.node_id,
            p.input_prompt ?? "",
            p.output_result,
            p.system_prompt
          );
      }
    },
  ],

  [
    "node.failed",
    (stores, event, _ctx) => {
      const p = payload<NodeFailedPayload>(event);
      stores.workflow.getState().handleNodeFailed(p);
      stores.conversation
        .getState()
        .failAgentMessage(p.node_id, p.agent_name, p.error, p.duration_ms);
    },
  ],
];
