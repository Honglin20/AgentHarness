"""Demo script: generate data → render_chart() → pushes to frontend.

展示全部 11 种图表类型：
  line, bar, scatter, bubble, area, pareto, optimal_line, heatmap, box, radar, table

Called by an agent via the bash tool. render_chart() inside a server
subprocess uses HTTP fallback (HARNESS_SERVER_URL set by server lifespan)
to POST to /api/charts → EventBus → WebSocket → frontend.

Usage (via agent bash tool):
    python examples/chart_script.py
"""

from harness.tools.chart import render_chart

# ── 通用数据集 ──────────────────────────────────────────────

time_series = [
    {"iter": 1, "score": 0.30, "loss": 0.90, "method": "A"},
    {"iter": 2, "score": 0.50, "loss": 0.70, "method": "A"},
    {"iter": 3, "score": 0.70, "loss": 0.40, "method": "B"},
    {"iter": 4, "score": 0.65, "loss": 0.50, "method": "B"},
    {"iter": 5, "score": 0.85, "loss": 0.20, "method": "A"},
    {"iter": 6, "score": 0.90, "loss": 0.15, "method": "B"},
    {"iter": 7, "score": 0.88, "loss": 0.18, "method": "A"},
    {"iter": 8, "score": 0.95, "loss": 0.10, "method": "B"},
]

bubble_data = [
    {"x": 10, "y": 30, "size": 5,  "group": "Alpha"},
    {"x": 20, "y": 50, "size": 12, "group": "Alpha"},
    {"x": 35, "y": 25, "size": 8,  "group": "Beta"},
    {"x": 40, "y": 60, "size": 20, "group": "Beta"},
    {"x": 55, "y": 45, "size": 15, "group": "Alpha"},
    {"x": 65, "y": 70, "size": 10, "group": "Gamma"},
    {"x": 70, "y": 35, "size": 18, "group": "Gamma"},
    {"x": 80, "y": 55, "size": 7,  "group": "Beta"},
]

radar_data = [
    {"metric": "Accuracy",  "model_A": 0.85, "model_B": 0.78},
    {"metric": "Speed",     "model_A": 0.70, "model_B": 0.92},
    {"metric": "Memory",    "model_A": 0.60, "model_B": 0.80},
    {"metric": "Reliability", "model_A": 0.90, "model_B": 0.75},
    {"metric": "Scalability", "model_A": 0.75, "model_B": 0.88},
    {"metric": "Cost",      "model_A": 0.82, "model_B": 0.65},
]

results = []

# 1. 折线图 — 多线对比
results.append(render_chart(time_series,
    chart_type="line", x="iter", y="score", hue="method",
    label="Overview", title="Score over iterations (by method)"))

# 2. 柱状图 — 分组柱
results.append(render_chart(time_series,
    chart_type="bar", x="iter", y="loss", hue="method",
    label="Overview", title="Loss per iteration (grouped)"))

# 3. 散点图 — 按 method 分色
results.append(render_chart(time_series,
    chart_type="scatter", x="iter", y="score", hue="method",
    label="Overview", title="Score scatter by method"))

# 4. 气泡图 — 第三维度 size 控制气泡大小
results.append(render_chart(bubble_data,
    chart_type="bubble", x="x", y="y", size="size", hue="group",
    label="Advanced", title="Bubble chart (size = weight)"))

# 5. 面积图 — 趋势填充
results.append(render_chart(time_series,
    chart_type="area", x="iter", y="score", hue="method",
    label="Overview", title="Score area (stacked by method)"))

# 6. 帕累托图 — 多目标最优前沿
results.append(render_chart([
    {"cost": 10, "quality": 0.5},
    {"cost": 20, "quality": 0.8},
    {"cost": 15, "quality": 0.6},
    {"cost": 30, "quality": 0.9},
    {"cost": 25, "quality": 0.85},
    {"cost": 40, "quality": 0.95},
    {"cost": 35, "quality": 0.7},
], chart_type="pareto", x="cost", y="quality", pareto_direction="max",
    label="Advanced", title="Quality vs Cost (Pareto front)"))

# 7. 最优线图 — 追踪历史最优
results.append(render_chart(time_series,
    chart_type="optimal_line", x="iter", y="score", optimal_line="max",
    label="Overview", title="Best score so far"))

# 8. 热力图 — 矩阵可视化
results.append(render_chart([
    {"x": "Mon", "y": "Week1", "value": 3},
    {"x": "Tue", "y": "Week1", "value": 7},
    {"x": "Wed", "y": "Week1", "value": 5},
    {"x": "Thu", "y": "Week1", "value": 9},
    {"x": "Fri", "y": "Week1", "value": 2},
    {"x": "Mon", "y": "Week2", "value": 6},
    {"x": "Tue", "y": "Week2", "value": 4},
    {"x": "Wed", "y": "Week2", "value": 8},
    {"x": "Thu", "y": "Week2", "value": 1},
    {"x": "Fri", "y": "Week2", "value": 7},
], chart_type="heatmap", x="x", y="y",
    label="Advanced", title="Activity heatmap"))

# 9. 箱线图 — 分布对比
results.append(render_chart([
    {"group": "A", "value": 12}, {"group": "A", "value": 15},
    {"group": "A", "value": 18}, {"group": "A", "value": 22},
    {"group": "A", "value": 25}, {"group": "A", "value": 28},
    {"group": "B", "value": 8},  {"group": "B", "value": 14},
    {"group": "B", "value": 16}, {"group": "B", "value": 20},
    {"group": "B", "value": 35}, {"group": "B", "value": 40},
    {"group": "C", "value": 10}, {"group": "C", "value": 11},
    {"group": "C", "value": 12}, {"group": "C", "value": 13},
    {"group": "C", "value": 14}, {"group": "C", "value": 15},
], chart_type="box", x="group", y="value",
    label="Advanced", title="Distribution by group"))

# 10. 雷达图 — 多维对比
results.append(render_chart([
    {"metric": "Accuracy",    "model": "A", "score": 0.85},
    {"metric": "Speed",       "model": "A", "score": 0.70},
    {"metric": "Reliability", "model": "A", "score": 0.90},
    {"metric": "Scalability", "model": "A", "score": 0.75},
    {"metric": "Accuracy",    "model": "B", "score": 0.78},
    {"metric": "Speed",       "model": "B", "score": 0.92},
    {"metric": "Reliability", "model": "B", "score": 0.75},
    {"metric": "Scalability", "model": "B", "score": 0.88},
], chart_type="radar", x="metric", y="score", hue="model",
    label="Advanced", title="Model comparison (radar)"))

# 11. 数据表格
results.append(render_chart(time_series,
    chart_type="table",
    label="Data", title="Raw Data"))

print("\n".join(results))
print(f"\nDone — {len(results)} charts rendered (11 types).")
