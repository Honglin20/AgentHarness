/**
 * Shared grouping utilities for conversation rendering.
 *
 * Two consumers: ScopedConversationTab (full details view) and any future
 * tab that needs NodeBlock grouping. Previously both ScopedConversationTab
 * and ScopedOutlineTab copy-pasted the same algorithm — this module is the
 * single source of truth.
 *
 * Data shape contract:
 *   - A NodeBlock corresponds to one agent node's lifetime (node.started →
 *     node.completed). Its messages arrive in temporal order from the
 *     store; we never re-sort them here.
 *   - NodeChild introduces the "interleaved turn" layer that the flat
 *     items[] representation lost: agent_msg → tool_group → agent_msg →
 *     tool_group → question. This is what makes "对话→工具→对话→工具"
 *     visible at the UI level.
 *   - stepId on each child is the bridge to TODO-tool progress: messages
 *     emitted while a step was in_progress carry that step's id, so a
 *     child's details can be rendered under the right StepRow.
 */

import type { ConversationMessage } from "@/stores/conversationStore";

export type NodeChild =
  | { kind: "agent_msg"; message: ConversationMessage; stepId?: string }
  | { kind: "tool_group"; tools: ConversationMessage[]; stepId?: string }
  | { kind: "question"; message: ConversationMessage; stepId?: string };

export interface NodeBlock {
  kind: "node";
  nodeId: string;
  children: NodeChild[];
  mainMessage: ConversationMessage;
  /**
   * L1 summary slot (reserved). Populated by an agent calling
   * todo(op="summarize", ...) in a future PR. Undefined in PR-E → the
   * outer card skips L1 and renders L2 directly.
   */
  purposeSummary?: string;
}

export interface OtherBlock {
  kind: "other";
  message: ConversationMessage;
}

export type Block = NodeBlock | OtherBlock;

/**
 * Does this message belong to an agent node's stream?
 *
 * Discriminated-union fix: "question" is included so that ask_user cards
 * are grouped under their parent agent's NodeBlock (collapsing the agent
 * also hides the question). Previously question fell through to OtherBlock
 * and stayed visible when its agent was collapsed.
 */
export function isNodeMsg(m: ConversationMessage): boolean {
  return (
    (m.type === "agent" || m.type === "tool_call" || m.type === "question") &&
    !!m.nodeId
  );
}

/**
 * Pick the message that represents this node's "final output".
 * Last non-empty agent message wins; falls back to the first message if
 * the node has no agent text (e.g. tool-only node, or only a question).
 */
export function extractMainMessage(buf: ConversationMessage[]): ConversationMessage {
  for (let i = buf.length - 1; i >= 0; i--) {
    const m = buf[i];
    if (m.type === "agent" && m.content.trim()) return m;
  }
  return buf[0];
}

/**
 * Split a same-nodeId message buffer into NodeChild[].
 *
 * Adjacent tool_calls with the same stepId (or both absent) merge into one
 * tool_group. tool_calls that span a step boundary become separate groups
 * so the StepRow rendering shows the right summary line per step.
 *
 * agent / question messages each become their own child carrying their
 * own stepId.
 */
export function buildChildren(buf: ConversationMessage[]): NodeChild[] {
  const children: NodeChild[] = [];
  for (const m of buf) {
    const stepId = m.stepId;
    if (m.type === "tool_call") {
      const last = children[children.length - 1];
      if (last && last.kind === "tool_group" && last.stepId === stepId) {
        last.tools.push(m);
      } else {
        children.push({ kind: "tool_group", tools: [m], stepId });
      }
    } else if (m.type === "agent") {
      children.push({ kind: "agent_msg", message: m, stepId });
    } else if (m.type === "question") {
      children.push({ kind: "question", message: m, stepId });
    }
  }
  return children;
}
