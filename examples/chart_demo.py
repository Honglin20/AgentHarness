"""Chart rendering demo — shows render_chart() dual-channel delivery.

render_chart() is NOT an agent tool. It's a plain function that agent code calls
directly to push visualizations to the frontend.

Usage:
    python examples/chart_demo.py
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from harness.tools.chart import render_chart


def main():
    data = [
        {"iter": 1, "score": 0.3, "loss": 0.9, "method": "A"},
        {"iter": 2, "score": 0.5, "loss": 0.7, "method": "A"},
        {"iter": 3, "score": 0.7, "loss": 0.4, "method": "B"},
        {"iter": 4, "score": 0.65, "loss": 0.5, "method": "B"},
        {"iter": 5, "score": 0.85, "loss": 0.2, "method": "A"},
    ]

    # Line chart
    r1 = render_chart(data=data, chart_type="line", x="iter", y="score",
                      label="Training", title="Score Progress")
    print(f"1. {r1}")

    # Scatter with hue
    r2 = render_chart(data=data, chart_type="scatter", x="iter", y="score",
                      label="Training", title="Score by Method", hue="method")
    print(f"2. {r2}")

    # Pareto front
    r3 = render_chart(data=data, chart_type="pareto", x="iter", y="score",
                      label="Optimization", title="Pareto Front",
                      pareto_direction="max")
    print(f"3. {r3}")

    # Optimal line
    r4 = render_chart(data=data, chart_type="optimal_line", x="iter", y="score",
                      label="Training", title="Best Score Over Time",
                      optimal_line="max")
    print(f"4. {r4}")

    # Table
    r5 = render_chart(data=data, chart_type="table", label="Results",
                      title="Training Data")
    print(f"5. {r5}")

    # When running inside a workflow node (same process), charts emit via EventBus.
    # When running outside (no EventBus, no HARNESS_API_URL), returns info message.
    print("\nAll chart payloads generated successfully.")


if __name__ == "__main__":
    main()
