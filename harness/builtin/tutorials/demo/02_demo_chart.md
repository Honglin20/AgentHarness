---
workflow: demo_chart
title: 图表渲染演示
---

# 图表渲染演示（demo_chart）

一个 agent + `render_chart` 工具，演示如何把一份样本数据用多种图表类型可视化。适合快速验证 portal 的图表渲染链路、调试新图表类型。

## 数据分析师 @analyst

`analyst` 拿到用户给的主题（例如「某电商 Q1 销售」），独立完成三件事：

1. **构造样本数据**：根据主题编一份合理的数据集（list of dicts）
2. **简短叙述**：写一段对数据的解读
3. **多图渲染**：调用 `render_chart` 至少 2 种不同图表类型

`render_chart` 的关键字段：

| 字段 | 说明 |
|------|------|
| `data` | list of dicts，每行一条记录 |
| `chart_type` | `bar` / `line` / `scatter` / `pareto` / `optimal_line` / `heatmap` / `box` / `bubble` / `area` / `radar` / `waterfall` / `table` / `dist_overlay` |
| `x` / `y` | x/y 轴字段名 |
| `label` | 分组标签（图例） |
| `title` | 图表标题 |

`dist_overlay`（双轴叠加）需要额外 `series` 配置，可用于「预测值 vs 真实值 + 残差」这类多分布对比。

---

## 演示 task

直接把下面这段贴到运行框的 task 输入里：

```
分析某电商平台 2025 年 Q1 三个月份（1/2/3 月）的 GMV 走势，并用柱状图和折线图分别展示月度 GMV 和环比增长率。
```

也可换成任何你感兴趣的主题，analyst 会按相同套路构造数据 + 出图。

## 调试要点

- 图表没渲染：检查 portal 右侧的 event 流，搜 `render_chart` 的 tool_call 是否成功返回
- 想看支持的全部 chart_type：直接读 `harness/extensions/chart.py`
