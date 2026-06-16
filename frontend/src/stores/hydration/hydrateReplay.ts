/**
 * Replay hydration — extracted from viewStore.showReplay so each step is
 * independently testable.
 *
 * The hydration pipeline has three stages:
 *
 *   1. decideStrategy  — pick "persisted" | "events" | "legacy" based on
 *                        which fields are populated on the run record +
 *                        sidecars.
 *   2. loadSidecars    — lazily fetch charts / events / conversation if
 *                        the run record's `_has_*` flags say they live in
 *                        separate endpoints. Conversation was split out
 *                        of /runs/{id} to keep switching snappy on long
 *                        workflows (see server/_helpers.py). Since stage 3
 *                        the conversation sidecar is a cursor-paginated
 *                        slice ({messages, has_more}); `applyHydration`
 *                        surfaces has_more to the conversation store.
 *   3. applyHydration  — write to scoped stores via the chosen strategy.
 *
 * Race-safety: the caller is responsible for `_replaySeq`-style guards.
 * Each function here is pure (or async with no shared state), so callers
 * can sequence them under whatever concurrency policy they need.
 */

import type { RunRecord, OutlineSummaryItem } from "@/stores/runHistoryStore";
import type { ConversationMessageDTO } from "@/lib/conversion/dtoToMessage";
import type { WSEvent } from "@/types/events";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import {
  loadLegacyRunData,
  loadRunFromPersistedData,
  replayEventsToStores,
} from "@/contexts/workflow-context/replayEvents";
import { getWorkflowManager } from "@/contexts/workflow-context/WorkflowManager";
import { outlineSummaryToItems } from "@/components/outline/outlineSummaryToItems";

export type HydrationStrategy = "persisted" | "events" | "legacy";

export interface ConversationWindow {
  messages: ConversationMessageDTO[];
  has_more: boolean;
  total: number;
}

export interface SidecarData {
  charts: RunRecord["chart_groups"];
  events: RunRecord["events"];
  /**
   * Conversation window. After stage 3 this is a cursor-paginated slice —
   * `messages` is the loaded tail (or prepended window), `has_more` tells
   * the UI whether older messages exist on the backend.
   */
  conversation: ConversationWindow | null;
  outline: OutlineSummaryItem[] | null;
}

/**
 * Pick a hydration strategy based on what data is actually present.
 *
 * - persisted: conversation + dag + trace all populated → the
 *   fast path; direct store hydration that survives event buffer overflow.
 *   agent_io is optional — some runs don't have IO records.
 * - events: persisted data incomplete, but ws events available → replay
 *   event-by-event.
 * - legacy: neither — bare-bones load (very old runs).
 */
export function decideStrategy(run: RunRecord, sidecars: SidecarData): HydrationStrategy {
  const conv = sidecars.conversation?.messages ?? run.conversation ?? [];
  // agent_io is optional — some runs don't have IO records. The persisted
  // path handles missing agent_io gracefully (agentIO store stays empty).
  const hasPersistedData = Boolean(conv && conv.length > 0 && run.dag && run.result?.trace);
  if (hasPersistedData) return "persisted";

  const wsEvents = sidecars.events as WSEvent[] | undefined;
  if (wsEvents && wsEvents.length > 0) return "events";

  return "legacy";
}

/**
 * Resolve sidecar data — fetch charts/events/conversation lazily when the
 * run record's `_has_*` flags say they live in separate endpoints. When
 * the data is already inline, returns it without a network call.
 *
 * On fetch failure, the individual sidecar comes back as `null` / `undefined`
 * — the caller's strategy decision and applyHydration tolerate that.
 */
export async function loadSidecars(run: RunRecord): Promise<SidecarData> {
  const needsCharts = Boolean(
    (run._has_charts || run._has_events) && !run.chart_groups && !run.events,
  );
  const needsConv = Boolean(
    run._has_conversation && (!run.conversation || run.conversation.length === 0),
  );
  const needsOutline = Boolean(run._has_outline);

  if (!needsCharts && !needsConv && !needsOutline) {
    return {
      charts: run.chart_groups ?? null,
      events: run.events,
      conversation: run.conversation && run.conversation.length > 0
        ? { messages: run.conversation, has_more: false, total: run.conversation.length }
        : null,
      outline: null,
    };
  }

  const store = useRunHistoryStore.getState();
  // Promise.all settles every branch — if one sidecar fetch rejects we'd
  // reject the whole batch. We want partial success, so we wrap each fetch
  // to swallow its own rejection.
  const safeFetch = <T>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

  const [charts, events, convResp, outline] = await Promise.all([
    needsCharts && run._has_charts
      ? safeFetch(store.fetchRunCharts(run.run_id))
      : Promise.resolve(run.chart_groups ?? null),
    needsCharts && run._has_events
      ? safeFetch(store.fetchRunEvents(run.run_id))
      : Promise.resolve(run.events ?? null),
    needsConv
      ? safeFetch(store.fetchRunConversation(run.run_id))
      : Promise.resolve(null),
    needsOutline
      ? safeFetch(store.fetchRunOutline(run.run_id))
      : Promise.resolve(null),
  ]);

  // Cursor fetch returns {messages, has_more, total}; fall back to inline
  // conversation (legacy main-record data) when the fetch was skipped.
  let conversation: ConversationWindow | null = null;
  if (convResp && typeof convResp === "object" && Array.isArray((convResp as any).messages)) {
    conversation = {
      messages: (convResp as any).messages as ConversationMessageDTO[],
      has_more: Boolean((convResp as any).has_more),
      total: Number((convResp as any).total ?? 0),
    };
  } else if (run.conversation && run.conversation.length > 0) {
    conversation = { messages: run.conversation, has_more: false, total: run.conversation.length };
  }

  return {
    charts: charts ?? run.chart_groups ?? null,
    events: events ?? run.events,
    conversation,
    outline: outline ?? null,
  };
}

/**
 * Apply the chosen hydration strategy — write to scoped stores.
 *
 * Returns the merged run record (original + sidecars) so the caller can
 * stash it on activeView for later inspection.
 */
export function applyHydration(
  workflowId: string,
  run: RunRecord,
  sidecars: SidecarData,
  strategy: HydrationStrategy,
): RunRecord {
  const convWindow = sidecars.conversation;
  const conv = convWindow?.messages ?? run.conversation ?? [];
  const merged: RunRecord = {
    ...run,
    chart_groups: sidecars.charts,
    conversation: conv,
    events: sidecars.events ?? undefined,
  };
  const wsEvents = sidecars.events as WSEvent[] | undefined;

  switch (strategy) {
    case "persisted":
      loadRunFromPersistedData(workflowId, merged, wsEvents);
      break;
    case "events":
      // Guarded by decideStrategy — wsEvents is non-empty when this fires.
      if (wsEvents && wsEvents.length > 0) {
        replayEventsToStores(workflowId, wsEvents);
      } else {
        // Defensive: if strategy was chosen but events turned out empty
        // (race), fall back to legacy so we don't silently no-op.
        loadLegacyRunData(
          workflowId,
          conv,
          sidecars.charts,
          run.dag,
          run.workflow_name,
          run.result,
        );
      }
      break;
    case "legacy":
      loadLegacyRunData(
        workflowId,
        conv,
        sidecars.charts,
        run.dag,
        run.workflow_name,
        run.result,
      );
      break;
  }

  // Hydrate the outline sidecar store AFTER the strategy dispatch — every
  // strategy calls resetAllStores() internally, which would wipe an earlier
  // write. When sidecar is absent (legacy run / fetch failed / computation
  // failed at save), items stays null and `useAgentOutline` falls back to
  // deriving from the full conversation.
  if (sidecars.outline && sidecars.outline.length > 0) {
    const items = outlineSummaryToItems(sidecars.outline);
    getWorkflowManager().getOrCreate(workflowId).stores.outline.getState().setItems(items);
  }

  // Windowed conversation flag — also written after the dispatch for the
  // same resetAllStores reason. has_more tells the UI whether older
  // messages are still on the backend (drives the "Load earlier" button);
  // total lets the cursor math compute the next `before` (total - loaded).
  getWorkflowManager().getOrCreate(workflowId).stores.conversation.getState().setWindowedState(
    convWindow?.has_more ?? false,
    convWindow?.total ?? 0,
  );

  return merged;
}

/**
 * Orchestrator: load sidecars → pick strategy → apply to scoped stores.
 *
 * Extracted from viewStore.showReplay so activateRun's running branch can
 * reuse the same hydration pipeline without going through showReplay (which
 * owns activeView switching and is replay-specific). The caller is fully
 * responsible for the race-safety seq guard — pass your own (whether
 * `_replaySeq` from viewStore or `_activateSeq` from activateRun) plus a
 * reader so the post-await staleness check uses the live value.
 *
 * Does NOT reset scoped stores — the caller must `resetAllStores(scoped.stores)`
 * synchronously BEFORE any state write that flips the UI to the new run,
 * otherwise the previous run's data bleeds into the new run's render window.
 */
export async function hydrateStores(
  run: RunRecord,
  seq: number,
  getCurrentSeq: () => number,
): Promise<RunRecord> {
  try {
    const sidecars = await loadSidecars(run);
    if (seq !== getCurrentSeq()) return run;
    const strategy = decideStrategy(run, sidecars);
    return applyHydration(run.run_id, run, sidecars, strategy);
  } catch (err) {
    if (seq !== getCurrentSeq()) return run;
    console.error("[hydrateStores] failed:", err);
    const fallback: SidecarData = {
      charts: run.chart_groups ?? null,
      events: run.events,
      conversation: run.conversation && run.conversation.length > 0
        ? { messages: run.conversation, has_more: false, total: run.conversation.length }
        : null,
      outline: null,
    };
    const fallbackStrategy = decideStrategy(run, fallback);
    return applyHydration(run.run_id, run, fallback, fallbackStrategy);
  }
}

/**
 * Phase 1 hydration — minimum viable data for instant UI feedback.
 *
 * Writes synchronously to the workflow store (dag + name) and fetches the
 * outline sidecar (small pre-computed summary, typically a few KB). Combined
 * these let the user see the DAG + agent outline within ~100ms of clicking
 * a run, instead of waiting for the full hydration pipeline (which replays
 * events and fetches conversation/charts sidecars).
 *
 * Does NOT call resetAllStores — phase 2 (`hydrateStores`) owns that. The
 * caller must have reset stores before invoking phase 1 (or accept that
 * stale data may briefly show until phase 2 lands).
 *
 * Best-effort on the outline fetch — if it fails, phase 2 will retry via
 * applyHydration's outline branch.
 */
export async function hydratePhase1(run: RunRecord): Promise<void> {
  const scoped = getWorkflowManager().getOrCreate(run.run_id).stores;
  scoped.workflow.getState().setWorkflow(
    run.run_id,
    run.workflow_name,
    run.dag ?? null,
  );
  if (run._has_outline) {
    try {
      const outline = await useRunHistoryStore.getState().fetchRunOutline(run.run_id);
      if (outline && outline.length > 0) {
        scoped.outline.getState().setItems(outlineSummaryToItems(outline));
      }
    } catch (err) {
      // Fail loud per CLAUDE.md — surface the error so it doesn't look
      // identical to "no outline sidecar". Phase 2 will still attempt
      // its own fetch via loadSidecars, but if the backend is broken
      // both phases fail silently without this log.
      console.error(`[hydratePhase1] outline fetch failed for ${run.run_id}:`, err);
    }
  }
}

// ---------------------------------------------------------------------------
// Snapshot-based hydration (Phase 1 long-run replay)
// ---------------------------------------------------------------------------
//
// Fetches /api/runs/{id}/snapshot — a self-contained payload written
// incrementally by node_factory._save_incremental after each node completion.
// Hydrates the scoped stores in a single setState pass, so the UI is correct
// immediately and WS only needs to deliver events after `seq_cursor`.
//
// Caller (activateRun) is responsible for:
//   - setting the hydration watermark via setHydratedCursor (so WS-replayed
//     events with seq ≤ cursor are deduped by routing/dedup.ts)
//   - setting useAppViewStore.wsSinceSeq = cursor (so WS connects with
//     since_seq=cursor and only delivers post-snapshot events)
//
// See docs/plans/2026-06-16-long-run-replay-architecture.md.

export interface RunSnapshot {
  run_id: string;
  workflow_name: string;
  status: string;
  created_at?: string;
  seq_cursor: number;
  dag?: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null;
  agent_io?: Record<string, unknown>;
  conversation?: unknown[];
  /** Total message count in the full backend conversation (pre-tail). */
  conversation_total?: number;
  charts?: { groupOrder?: string[]; groups?: Record<string, unknown> } | null;
  todo_states?: Record<string, unknown> | null;
  nodes_latest?: Record<string, { status?: string; latest_iter?: number | null }>;
  current_iter?: number | null;
  iter_index?: Record<string, unknown> | null;
  fitness_history?: Array<{
    iter: number;
    best_fitness: number;
    best_strategy_id?: string;
    best_latency_ms?: number | null;
    best_metrics?: Record<string, unknown> | null;
    primary_metric?: string | null;
  }>;
}

/**
 * Hydrate scoped stores directly from a snapshot payload (single setState per store).
 *
 * Does NOT touch:
 *   - toolCall store (let WS replay repopulate post-cursor tool activity)
 *   - span store (same)
 *   - agentIO store (snapshot carries agent_io but the store has its own
 *     shape — defer until Phase 2 when snapshot shape stabilises)
 *
 * The caller MUST follow up with setHydratedCursor + setWsSinceSeq so WS
 * replay doesn't undo / duplicate this hydration.
 */
export function hydrateFromSnapshot(snapshot: RunSnapshot): void {
  const scoped = getWorkflowManager().getOrCreate(snapshot.run_id).stores;

  // 1. Workflow store: id + name + dag (matches hydratePhase1 contract)
  //    + fitness_history (Phase 4) — direct setState bypasses setWorkflow
  //    to keep the trend chart data on refresh.
  scoped.workflow.getState().setWorkflow(
    snapshot.run_id,
    snapshot.workflow_name,
    snapshot.dag ?? null,
  );
  if (Array.isArray(snapshot.fitness_history)) {
    scoped.workflow.setState({ fitnessHistory: snapshot.fitness_history as never });
  }

  // 2. Conversation store: replace messages (snapshot.conversation is
  // already a structured message list from build_conversation on backend).
  // Also set hasEarlier so the scroll-to-top loader knows whether to fetch.
  if (Array.isArray(snapshot.conversation)) {
    const total = typeof snapshot.conversation_total === "number"
      ? snapshot.conversation_total
      : snapshot.conversation.length;
    const hasEarlier = total > snapshot.conversation.length;
    scoped.conversation.setState({
      messages: snapshot.conversation as never[],
      hasEarlier,
      conversationTotal: total,
      loadingEarlier: false,
    });
  }

  // 3. Chart store: replace groupOrder + groups.
  if (snapshot.charts && (snapshot.charts.groupOrder || snapshot.charts.groups)) {
    scoped.chart.setState({
      groupOrder: snapshot.charts.groupOrder ?? [],
      groups: (snapshot.charts.groups ?? {}) as never,
    });
  }

  // 4. Todo store: replace per-node todo states.
  if (snapshot.todo_states && typeof snapshot.todo_states === "object") {
    scoped.todo.setState({ todos: snapshot.todo_states as never });
  }
}

/**
 * Fetch /api/runs/{id}/snapshot. Returns null on 404 / network error / parse
 * failure — caller falls back to legacy replay path.
 */
export async function fetchSnapshot(
  runId: string,
  signal?: AbortSignal,
): Promise<RunSnapshot | null> {
  try {
    const { fetchWithAuth } = await import("@/lib/api");
    const r = await fetchWithAuth(`/api/runs/${encodeURIComponent(runId)}/snapshot`, {
      signal,
    });
    if (!r.ok) return null;
    const data = (await r.json()) as RunSnapshot | null;
    if (!data || typeof data !== "object" || !data.run_id) return null;
    return data;
  } catch {
    return null;
  }
}
