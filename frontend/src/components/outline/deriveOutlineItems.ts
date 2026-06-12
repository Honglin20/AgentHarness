/**
 * Pure derivation: store snapshot → ordered OutlineItem[].
 *
 * This is the single source of truth for what the outline renders. The UI
 * layer is a thin map over this output — no business logic in components.
 *
 * Properties guaranteed by this function:
 *   - Stable order: items sorted by first-message timestamp ascending;
 *     idle nodes (no messages) sort last, preserving DAG declaration order
 *     (the order keys appear in the `nodes` Record, which mirrors the
 *     order the engine registered them).
 *   - Loop expansion: a nodeId with messages across N iterations produces
 *     N items, keyed `${nodeId}__iter${n}`.
 *   - Deterministic: identical inputs always yield identical output. Safe
 *     to memoize on (nodes, messages, todos) references.
 */

import type { ConversationMessage } from "@/stores/conversationStore";
import type { NodeState } from "@/stores/workflowStore";
import type { TodoStep } from "@/contexts/workflow-context/stores/todo";
import type { OutlineItem, OutlineBadge, AgentActivity, OutlineStatus } from "./types";

export function deriveOutlineItems(
  nodes: Record<string, NodeState>,
  messages: ConversationMessage[],
  todos: Record<string, TodoStep[]>,
): OutlineItem[] {
  // DAG declaration order — index of each nodeId as it appears in the
  // `nodes` Record. Used as the stable secondary sort key for idle nodes
  // (which all share firstTs = Infinity). Mirrors how the engine registers
  // nodes; JS object string keys preserve insertion order, so this is the
  // order users see in the workflow definition.
  const nodeDagOrder = new Map<string, number>();
  Object.keys(nodes).forEach((id, idx) => nodeDagOrder.set(id, idx));

  // 1. Collect (nodeId, iteration) pairs seen in messages.
  const iterSet = new Map<string, { nodeId: string; iteration: number; firstTs: number }>();
  for (const m of messages) {
    if (!m.nodeId) continue;
    // Skip synthetic followup nodeIds — ChatInput creates `followup-${agent}`
    // entries for @mention multi-turn conversations (addFollowupUserMessage /
    // addFollowupAgentMessage in conversation.ts). These never fire
    // node.started, so they're not real DAG nodes and would otherwise appear
    // as phantom outline rows detached from the original agent.
    if (m.nodeId.startsWith("followup-")) continue;
    const iter = m.iteration ?? 1;
    const key = `${m.nodeId}__iter${iter}`;
    const existing = iterSet.get(key);
    if (!existing || m.timestamp < existing.firstTs) {
      iterSet.set(key, { nodeId: m.nodeId, iteration: iter, firstTs: m.timestamp });
    }
  }

  // 2. For nodes with no messages yet, synthesize a single iter=1 entry.
  //    Uses Infinity so idle nodes sort after any node that has produced
  //    a message — DAG declaration order is the stable secondary sort.
  for (const nodeId of Object.keys(nodes)) {
    const key = `${nodeId}__iter1`;
    if (!iterSet.has(key)) {
      iterSet.set(key, { nodeId, iteration: 1, firstTs: Number.POSITIVE_INFINITY });
    }
  }

  // 3. Detect multiple iterations per nodeId for the badge.
  const iterCountByNode = new Map<string, number>();
  for (const entry of Array.from(iterSet.values())) {
    iterCountByNode.set(entry.nodeId, (iterCountByNode.get(entry.nodeId) ?? 0) + 1);
  }

  // 4. Sort by firstTs ascending; tiebreak on DAG declaration order, then
  //    iteration number. Avoids localeCompare so idle nodes follow the
  //    workflow's declared topology instead of alphabetical order.
  const sorted = Array.from(iterSet.values()).sort((a, b) => {
    if (a.firstTs !== b.firstTs) return a.firstTs - b.firstTs;
    const dagA = nodeDagOrder.get(a.nodeId) ?? Number.POSITIVE_INFINITY;
    const dagB = nodeDagOrder.get(b.nodeId) ?? Number.POSITIVE_INFINITY;
    if (dagA !== dagB) return dagA - dagB;
    return a.iteration - b.iteration;
  });

  // 5. Project each entry to OutlineItem.
  return sorted.map((entry, idx) => {
    const node = nodes[entry.nodeId];
    const name = node?.name ?? entry.nodeId;
    const iterCount = iterCountByNode.get(entry.nodeId) ?? 1;
    const isLatestIter = entry.iteration === iterCount;
    // Filter todos by iter so each row only sees its own steps. Legacy
    // steps without `iteration` field default to iter=1 (matches
    // ConversationMessage.iteration ?? 1 convention).
    const todosForNode = (todos[entry.nodeId] ?? []).filter(
      (t) => (t.iteration ?? 1) === entry.iteration,
    );
    const iterMessages = messages.filter(
      (m) => m.nodeId === entry.nodeId && (m.iteration ?? 1) === entry.iteration,
    );
    return buildItem(entry, node, name, todosForNode, iterMessages, iterCount, idx, isLatestIter);
  });
}

function buildItem(
  entry: { nodeId: string; iteration: number; firstTs: number },
  node: NodeState | undefined,
  name: string,
  todos: TodoStep[],
  iterMessages: ConversationMessage[],
  iterCount: number,
  order: number,
  isLatestIter: boolean,
): OutlineItem {
  const pendingQuestions = iterMessages.filter(
    (m) => m.type === "question" && m.status === "pending",
  );
  const status = computeStatus(node, pendingQuestions.length, iterMessages, isLatestIter);
  const activity = computeActivity(node, todos, pendingQuestions, isLatestIter);
  const badges = computeBadges(node, entry.iteration, iterCount, isLatestIter);

  return {
    key: `${entry.nodeId}__iter${entry.iteration}`,
    nodeId: entry.nodeId,
    name,
    iteration: entry.iteration,
    hasMultipleIterations: iterCount > 1,
    isLatestIter,
    status,
    activity,
    badges,
    order,
  };
}

function computeStatus(
  node: NodeState | undefined,
  pendingQuestionCount: number,
  iterMessages: ConversationMessage[],
  isLatestIter: boolean,
): OutlineStatus {
  if (pendingQuestionCount > 0) return "waiting-for-user";
  if (!node) return "idle";

  // Latest iter — use node-level real-time status.
  if (isLatestIter) {
    // NodeState.status values: idle | running | success | failed | retrying
    switch (node.status) {
      case "running": return "running";
      case "success": return "completed";
      case "failed": return "failed";
      case "retrying": return "retrying";
      default: return "idle";
    }
  }

  // Historical iter — node.status reflects the current iter, not this one.
  // Infer from messages: error → failed, done → completed, else → idle.
  if (iterMessages.some((m) => m.status === "error")) return "failed";
  if (iterMessages.some((m) => m.status === "done")) return "completed";
  return "idle";
}

function computeActivity(
  node: NodeState | undefined,
  todos: TodoStep[],
  pendingQuestions: ConversationMessage[],
  isLatestIter: boolean,
): AgentActivity {
  if (pendingQuestions.length > 0) {
    return {
      kind: "waiting-for-user",
      questionId: pendingQuestions[0].questionId ?? "",
      questionCount: pendingQuestions.length,
    };
  }
  if (!node) return { kind: "idle" };

  // Retry activity is only meaningful on the latest iter — historical
  // iters' retryAttempts are merged into the node-level array and can't
  // be attributed to a specific past iter.
  if (isLatestIter && node.status === "retrying" && node.retryAttempts?.length) {
    const last = node.retryAttempts[node.retryAttempts.length - 1];
    // RetryAttempt.attempt is 1-indexed for the attempt that JUST FAILED.
    // UI displays the upcoming attempt number (attempt + 1) to match the
    // toast at agentHandlers.ts and the inline retry card at AgentMessage.tsx.
    // All three surfaces must agree; do not "fix" one without the others.
    return { kind: "retrying", attempt: last.attempt + 1, maxAttempts: last.maxAttempts };
  }

  // Historical iters have terminated (they're in the past). Without
  // per-iter metadata we treat them as completed; durationMs is omitted
  // because node.durationMs is the latest iter's value, not this one's.
  if (!isLatestIter) {
    return { kind: "completed" };
  }

  if (node.status === "failed") {
    return { kind: "failed", errorSummary: node.classifiedFailure?.category ?? node.error ?? "Failed" };
  }
  if (node.status === "running") {
    const activeStep = todos.find((t) => t.status === "in_progress");
    return {
      kind: "running",
      currentStepContent: activeStep?.activeForm || activeStep?.content,
    };
  }
  if (node.status === "success") {
    return { kind: "completed", durationMs: node.durationMs };
  }
  return { kind: "idle" };
}

function computeBadges(
  node: NodeState | undefined,
  iteration: number,
  iterCount: number,
  isLatestIter: boolean,
): OutlineBadge[] {
  const badges: OutlineBadge[] = [];
  if (iterCount > 1) {
    badges.push({ kind: "iteration", text: `#${iteration}`, title: `Iteration ${iteration} of ${iterCount}` });
  }
  // Token / retry badges only on the latest iter. NodeState.tokenUsage and
  // retryAttempts are node-level (not iter-partitioned), so showing them on
  // historical rows would be misleading — three rows showing the same
  // number under different "Iteration N/M" titles. Iteration badge above
  // is genuinely iter-level and shows on every row.
  if (isLatestIter) {
    if (node?.retryAttempts?.length) {
      const last = node.retryAttempts[node.retryAttempts.length - 1];
      // Display upcoming attempt (attempt + 1) — matches toast at
      // agentHandlers.ts:148 and inline card at AgentMessage.tsx:388.
      // See computeActivity comment: all three surfaces must agree.
      badges.push({
        kind: "retry",
        text: `${last.attempt + 1}/${last.maxAttempts}`,
        title: `Retry attempt ${last.attempt + 1} of ${last.maxAttempts}`,
      });
    }
    if (node?.tokenUsage && node.tokenUsage.total > 0) {
      badges.push({
        kind: "tokens",
        text: formatTokens(node.tokenUsage.total),
        title: `${node.tokenUsage.input} in / ${node.tokenUsage.output} out`,
      });
    }
  }
  return badges;
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
