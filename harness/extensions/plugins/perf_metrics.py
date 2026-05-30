"""PerfMetricsPlugin — deprecated.

The Token Usage and Cost charts that this plugin used to emit are now produced
by the frontend Run Summary view (see frontend/src/lib/summary/runSummary.ts),
which reads token_usage, cost_usd, duration_ms etc. directly from per-node
state populated by macro_graph.

Kept as a no-op so existing imports and registrations stay valid; safe to
remove once no external code references it.
"""

from __future__ import annotations

from harness.extensions.base import BaseHook, NodeCtx


class PerfMetricsPlugin(BaseHook):
    name = "perf-metrics"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        return None
