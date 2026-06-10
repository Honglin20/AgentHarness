/**
 * Chat and followup event handlers.
 */

import type { EventHandler } from "./types";
import type { ChatQuestionPayload } from "@/types/events";
import { payload } from "./utils";

export const chatHandlers: [string, EventHandler][] = [
  [
    "chat.question",
    (stores, event, _ctx) => {
      const p = payload<ChatQuestionPayload>(event);
      // Idempotent: skip if this question was already processed (WS replay guard)
      const alreadyExists = stores.conversation.getState().messages.some(
        (m) => m.type === "question" && m.questionId === p.question_id
      );
      if (alreadyExists) return;
      const conv = stores.conversation.getState();
      const lastStreaming = [...conv.messages]
        .reverse()
        .find((m) => m.type === "agent" && m.status === "streaming");
      const fallbackAgent = lastStreaming?.agentName ?? "agent";
      conv.addUserQuestion({
        question_id: p.question_id,
        question: p.question,
        agent_name: p.agent_name ?? fallbackAgent,
        node_id: p.node_id,
        header: p.header ?? null,
        options: p.options ?? null,
        multi_select: p.multi_select ?? false,
        allow_custom_input: p.allow_custom_input ?? true,
        input_type: p.input_type ?? "text",
        input_placeholder: p.input_placeholder ?? null,
      });
    },
  ],

  [
    "followup.started",
    (stores, event, _ctx) => {
      const p = payload<{ workflow_id: string; agent_name: string; turn: number }>(event);
      const conv = stores.conversation.getState();
      conv.addFollowupAgentMessage(p.agent_name);
    },
  ],

  [
    "followup.completed",
    (stores, event, _ctx) => {
      const p = payload<{ workflow_id: string; agent_name: string; turn: number }>(event);
      const nodeId = `followup-${p.agent_name}`;
      stores.conversation.getState().completeAgentMessage(nodeId, p.agent_name);
    },
  ],

  [
    "followup.failed",
    (stores, event, _ctx) => {
      const p = payload<{ workflow_id: string; agent_name: string; error: string }>(event);
      const nodeId = `followup-${p.agent_name}`;
      stores.conversation.getState().failAgentMessage(nodeId, p.agent_name, p.error);
    },
  ],
];
