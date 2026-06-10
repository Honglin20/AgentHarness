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
 *                        workflows (see server/_helpers.py).
 *   3. applyHydration  — write to scoped stores via the chosen strategy.
 *
 * Race-safety: the caller is responsible for `_replaySeq`-style guards.
 * Each function here is pure (or async with no shared state), so callers
 * can sequence them under whatever concurrency policy they need.
 */

import type { RunRecord } from "@/stores/runHistoryStore";
import type { WSEvent } from "@/types/events";
import { useRunHistoryStore } from "@/stores/runHistoryStore";
import {
  loadLegacyRunData,
  loadRunFromPersistedData,
  replayEventsToStores,
} from "@/contexts/workflow-context/replayEvents";

export type HydrationStrategy = "persisted" | "events" | "legacy";

export interface SidecarData {
  charts: RunRecord["chart_groups"];
  events: RunRecord["events"];
  conversation: RunRecord["conversation"] | null;
}

/**
 * Pick a hydration strategy based on what data is actually present.
 *
 * - persisted: agent_io + conversation + dag + trace all populated → the
 *   fast path; direct store hydration that survives event buffer overflow.
 * - events: persisted data incomplete, but ws events available → replay
 *   event-by-event.
 * - legacy: neither — bare-bones load (very old runs).
 */
export function decideStrategy(run: RunRecord, sidecars: SidecarData): HydrationStrategy {
  const conv = sidecars.conversation ?? run.conversation ?? [];
  const hasPersistedData = Boolean(run.agent_io && conv && run.dag && run.result?.trace);
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

  if (!needsCharts && !needsConv) {
    return {
      charts: run.chart_groups ?? null,
      events: run.events,
      conversation: run.conversation ?? null,
    };
  }

  const store = useRunHistoryStore.getState();
  // Promise.all settles every branch — if one sidecar fetch rejects we'd
  // reject the whole batch. We want partial success, so we wrap each fetch
  // to swallow its own rejection.
  const safeFetch = <T>(p: Promise<T>): Promise<T | null> => p.catch(() => null);

  const [charts, events, conv] = await Promise.all([
    needsCharts && run._has_charts
      ? safeFetch(store.fetchRunCharts(run.run_id))
      : Promise.resolve(run.chart_groups ?? null),
    needsCharts && run._has_events
      ? safeFetch(store.fetchRunEvents(run.run_id))
      : Promise.resolve(run.events ?? null),
    needsConv
      ? safeFetch(store.fetchRunConversation(run.run_id))
      : Promise.resolve(run.conversation ?? null),
  ]);

  return {
    charts: charts ?? run.chart_groups ?? null,
    events: events ?? run.events,
    conversation: conv ?? run.conversation ?? null,
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
  const conv = sidecars.conversation ?? run.conversation ?? [];
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

  return merged;
}
