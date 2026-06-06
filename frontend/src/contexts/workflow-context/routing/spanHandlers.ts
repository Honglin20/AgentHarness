/**
 * Span tracing and circular warning event handlers.
 */

import type { EventHandler } from "./types";
import type { SpanStartPayload, SpanEndPayload, CircularWarningPayload } from "@/types/events";
import { payload } from "./utils";
import { useObservabilityStore } from "@/stores/observabilityStore";

export const spanHandlers: [string, EventHandler][] = [
  [
    "span.start",
    (stores, event, _ctx) => {
      const p = payload<SpanStartPayload>(event);
      stores.span.getState().startSpan(p);
    },
  ],

  [
    "span.end",
    (stores, event, _ctx) => {
      const p = payload<SpanEndPayload>(event);
      stores.span.getState().endSpan(p.span_id, p.ts);
    },
  ],

  [
    "circular.warning",
    (_stores, event, _ctx) => {
      const p = payload<CircularWarningPayload>(event);
      useObservabilityStore.getState().addCircularWarning({
        nodeId: p.node_id,
        agentName: p.agent_name,
        message: p.message,
        lastTool: p.last_tool,
        ts: Date.now(),
      });
    },
  ],
];
