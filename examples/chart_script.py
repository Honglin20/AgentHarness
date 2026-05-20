"""Demo script: generate data → render_chart() → pushes to frontend.

Called by an agent via the bash tool. render_chart() inside a server
subprocess uses HTTP fallback (HARNESS_SERVER_URL set by server lifespan)
to POST to /api/charts → EventBus → WebSocket → frontend.

Usage (via agent bash tool):
    python examples/chart_script.py
"""

from harness.tools.chart import render_chart

data = [
    {"iter": 1, "score": 0.3, "loss": 0.9, "method": "A"},
    {"iter": 2, "score": 0.5, "loss": 0.7, "method": "A"},
    {"iter": 3, "score": 0.7, "loss": 0.4, "method": "B"},
    {"iter": 4, "score": 0.65, "loss": 0.5, "method": "B"},
    {"iter": 5, "score": 0.85, "loss": 0.2, "method": "A"},
]

results = []

results.append(render_chart(data,
    chart_type="line", x="iter", y="score",
    label="Metrics", title="Score over iterations"))

results.append(render_chart(data,
    chart_type="table",
    label="Metrics", title="Raw Data"))

results.append(render_chart(data,
    chart_type="bar", x="iter", y="loss",
    label="Metrics", title="Loss per iteration"))

print("\n".join(results))
print(f"\nDone — {len(results)} charts rendered.")
