"""#4 — All 8 chart types via render_chart(). No LLM needed.

Usage:
    python examples/04_chart_demo.py
"""

from harness.tools.chart import render_chart

data = [{"iter": 1, "score": 0.3, "loss": 0.9, "method": "A"},
        {"iter": 2, "score": 0.5, "loss": 0.7, "method": "A"},
        {"iter": 3, "score": 0.7, "loss": 0.4, "method": "B"},
        {"iter": 4, "score": 0.65, "loss": 0.5, "method": "B"},
        {"iter": 5, "score": 0.85, "loss": 0.2, "method": "A"}]

print(render_chart(data, chart_type="line", x="iter", y="score", label="Training", title="Score"))
print(render_chart(data, chart_type="bar", x="iter", y="score", label="Training"))
print(render_chart(data, chart_type="scatter", x="iter", y="score", hue="method", label="Methods"))
print(render_chart(data, chart_type="pareto", x="iter", y="score", pareto_direction="max", label="Optimization"))
print(render_chart(data, chart_type="optimal_line", x="iter", y="score", optimal_line="max", label="Training"))
print(render_chart(data, chart_type="heatmap", x="iter", y="score", label="Analysis"))
print(render_chart(data, chart_type="box", x="iter", y="score", label="Stats"))
print(render_chart(data, chart_type="table", label="Results", title="All Data"))
