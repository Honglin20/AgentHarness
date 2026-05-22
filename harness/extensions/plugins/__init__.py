"""Built-in Hook plugins — observational artifacts produced via ctx.emit().

Each plugin is a BaseHook subclass. Enable via workflow.use():

    wf = Workflow("name", agents=[...]).use(EvalChartPlugin())
"""
from harness.extensions.plugins.eval_chart import EvalChartPlugin

__all__ = ["EvalChartPlugin"]