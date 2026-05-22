"""Built-in Hook plugins — observational artifacts produced via ctx.emit().

Each plugin is a BaseHook subclass. Enable via workflow.use():

    wf = Workflow("name", agents=[...]).use(EvalChartPlugin())
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
]
