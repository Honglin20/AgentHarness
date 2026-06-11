/**
 * Pure derivation: store snapshot → ordered OutlineItem[].
 *
 * This is the single source of truth for what the outline renders. The UI
 * layer is a thin map over this output — no business logic in components.
 *
 * Properties guaranteed by this function:
 *   - Stable order: items sorted by first-message timestamp ascending;
 *     idle nodes (no messages) sort last, preserving DAG declaration order.
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
  // 1. Collect (nodeId, iteration) pairs seen in messages.
  const iterSet = new Map<string, { nodeId: string; iteration: number; firstTs: number }>();
  for (const m of messages) {
    if (!m.nodeId) continue;
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

  // 4. Sort by firstTs ascending, with stable secondary sort on nodeId+iter.
  const sorted = Array.from(iterSet.values()).sort((a, b) => {
    if (a.firstTs !== b.firstTs) return a.firstTs - b.firstTs;
    if (a.nodeId !== b.nodeId) return a.nodeId.localeCompare(b.nodeId);
    return a.iteration - b.iteration;
  });

  // 5. Project each entry to OutlineItem.
  return sorted.map((entry, idx) => {
    const node = nodes[entry.nodeId];
    const name = node?.name ?? entry.nodeId;
    const todosForNode = todos[entry.nodeId] ?? [];
    const iterMessages = messages.filter(
      (m) => m.nodeId === entry.nodeId && (m.iteration ?? 1) === entry.iteration,
    );
    return buildItem(entry, node, name, todosForNode, iterMessages, iterCountByNode.get(entry.nodeId) ?? 1, idx);
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
): OutlineItem {
  const pendingQuestions = iterMessages.filter(
    (m) => m.type === "question" && m.status === "pending",
  );
  const status = computeStatus(node, pendingQuestions.length);
  const activity = computeActivity(node, todos, pendingQuestions);
  const badges = computeBadges(node, entry.iteration, iterCount);

  return {
    key: `${entry.nodeId}__iter${entry.iteration}`,
    nodeId: entry.nodeId,
    name,
    iteration: entry.iteration,
    hasMultipleIterations: iterCount > 1,
    status,
    activity,
    badges,
    order,
  };
}

function computeStatus(node: NodeState | undefined, pendingQuestionCount: number): OutlineStatus {
  if (pendingQuestionCount > 0) return "waiting-for-user";
  if (!node) return "idle";
  // NodeState.status values: idle | running | success | failed | retrying
  switch (node.status) {
    case "running": return "running";
    case "success": return "completed";
    case "failed": return "failed";
    case "retrying": return "retrying";
    default: return "idle";
  }
}

function computeActivity(
  node: NodeState | undefined,
  todos: TodoStep[],
  pendingQuestions: ConversationMessage[],
): AgentActivity {
  if (pendingQuestions.length > 0) {
    return {
      kind: "waiting-for-user",
      questionId: pendingQuestions[0].questionId ?? "",
      questionCount: pendingQuestions.length,
    };
  }
  if (!node) return { kind: "idle" };
  if (node.status === "retrying" && node.retryAttempts?.length) {
    const last = node.retryAttempts[node.retryAttempts.length - 1];
    // RetryAttempt.attempt is 1-indexed (payload.attempt counts current attempt),
    // so the displayed attempt equals the record's `attempt` value directly.
    return { kind: "retrying", attempt: last.attempt, maxAttempts: last.maxAttempts };
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
): OutlineBadge[] {
  const badges: OutlineBadge[] = [];
  if (iterCount > 1) {
    badges.push({ kind: "iteration", text: `#${iteration}`, title: `Iteration ${iteration} of ${iterCount}` });
  }
  if (node?.retryAttempts?.length) {
    const last = node.retryAttempts[node.retryAttempts.length - 1];
    // RetryAttempt.attempt is 1-indexed — display value matches the record directly.
    badges.push({
      kind: "retry",
      text: `${last.attempt}/${last.maxAttempts}`,
      title: `Retry attempt ${last.attempt} of ${last.maxAttempts}`,
    });
  }
  if (node?.tokenUsage && node.tokenUsage.total > 0) {
    badges.push({
      kind: "tokens",
      text: formatTokens(node.tokenUsage.total),
      title: `${node.tokenUsage.input} in / ${node.tokenUsage.output} out`,
    });
  }
  return badges;
}

function formatTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
