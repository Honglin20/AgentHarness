"""Built-in Hook plugins — observational artifacts produced via ctx.emit().

Hook plugins are auto-registered when a Bus is present (no .use() needed).
Middleware and GraphMutator still require explicit .use().

To manually opt out, call bus.unregister("plugin-name") before compile.
"""
from harness.extensions.plugins.eval_chart import EvalChartPlugin
from harness.extensions.plugins.agent_trace import AgentTracePlugin
from harness.extensions.plugins.reasoning_viz import ReasoningVizPlugin
from harness.extensions.plugins.perf_metrics import PerfMetricsPlugin

__all__ = [
    "EvalChartPlugin",
    "AgentTracePlugin",
    "ReasoningVizPlugin",
    "PerfMetricsPlugin",
    "register_default_hooks",
]

# All built-in hooks, instantiated once. Add new hooks here to auto-enable them.
_DEFAULT_HOOKS = [
    EvalChartPlugin,
    AgentTracePlugin,
    ReasoningVizPlugin,
    PerfMetricsPlugin,
]


def register_default_hooks(bus) -> None:
    """Register all built-in Hook plugins on *bus* if not already present.

    Idempotent — safe to call multiple times.
    """
    for hook_cls in _DEFAULT_HOOKS:
        instance = hook_cls()
        if instance.name not in bus._hooks:
            bus.register(instance)
