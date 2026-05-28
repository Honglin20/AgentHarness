# Analysis 可观测性增强方案

> 前提：纯功能增强，不改架构；不加配置/注册/API；只用 Python 库；数据不出本机。

---

## 现状诊断

### Plugin 启用状态

所有 6 个 Hook Plugin **默认启用**（`harness/extensions/plugins/__init__.py` 的 `_DEFAULT_HOOKS`），无需 workflow.json 配置：

| Plugin | 功能 | 分析图表 |
|--------|------|----------|
| PerfMetricsPlugin | 累计 token/cost | Token Usage + Cost 柱状图 |
| EvalChartPlugin | Eval 分数 | 分数折线图 |
| AgentTracePlugin | 节点 trace | trace.step 事件 |
| ReasoningVizPlugin | 推理可视化 | reasoning 事件 |
| StepCounterPlugin | 调用计数 | step.summary 事件 |
| CircularDetectorPlugin | 循环检测 | circular.warning 事件 |

### 当前 Analysis 图表来源

1. **前端 `computeRunSummary`**（刚加的）：workflow 完成时生成 Tokens/Duration/Overview 图表
2. **后端 Plugin `ctx.emit`**：PerfMetricsPlugin 每次 node 完成时通过 `_side_effects` → `bus.emit` → WebSocket → 前端 chartStore

### 问题

- PerfMetricsPlugin 理论上应该生成图表，但实际前端只看到 3 幅（来自 computeRunSummary）
- 需要在实现前先定位 plugin chart 是否到达前端（通过已有 debug 日志确认）
- `span.start/end` 有 span_id 但缺 `parent_span_id`，无法还原嵌套关系
- 缺少 timeline 可视化（agent/工具的执行时间线）
- circular.warning 存在 observabilityStore 但无 analysis 图表

---

## 改动方案

### 改动 1：增强 PerfMetricsPlugin — 新增 Duration/TTFT/Steps 图表

**文件：** `harness/extensions/plugins/perf_metrics.py`

**当前行为：** 每次 `on_node_end` 累计数据，emit token usage 分组柱状图 + cost 柱状图。

**增强：** 在 `on_node_end` 继续累计 duration、ttft、step count，同样 emit 为 `category: "analysis"` 图表。

新增图表：

| 图表 | chart_type | 数据 |
|------|-----------|------|
| Duration (ms) by Agent | bar | `{agent, duration_ms}` |
| Time to First Token (ms) by Agent | bar | `{agent, ttft_ms}`（有数据时） |
| Steps by Agent | bar (grouped) | `{agent, kind: tool/llm, count}`（有数据时） |
| Run Overview | table | `{agent, status, duration_ms, ttft_ms, input, output, total, cost_usd, steps}` |

**数据来源：**
- `ctx.metadata[agent_name]` 已有 `duration_ms`, `token_usage`, `cost_usd`
- `ttft_ms` 需要从 node metadata 获取（macro_graph.py 已在 772 行写入 `node_meta`）
- `tool_calls` 已在 747-748 行写入 metadata

**关键问题：** `ttft_ms` 当前写入的是 LangGraph state 的 `node_meta`，不是 `ext_ctx.metadata`。需要在 macro_graph.py 中补一行：
```python
if ttft_ms is not None:
    ext_ctx.metadata.setdefault(agent_def.name, {})["ttft_ms"] = ttft_ms
```

### 改动 2：新增 TimelinePlugin — 甘特图（含工具执行时间）

**文件：** 新建 `harness/extensions/plugins/timeline.py`

**职责：** 收集每个 agent 的 start_time 和 end_time，以及每个工具调用的 start/end，在 workflow 完成时生成甘特图数据。

**图表：** 新增 `timeline` chart_type

```
reviewer  ████████                          1.2s
writer         ████████████████              2.1s
  └─ bash   ██████                           0.4s
  └─ python      ████████                    0.6s
editor                  ██████               0.8s
|--------|--------|--------|--------|
0ms     500ms    1s      1.5s     2s
```

**数据结构：**
```json
{
  "chart_type": "timeline",
  "category": "analysis",
  "data": [
    {"agent": "writer", "start_ms": 200, "end_ms": 2300, "kind": "agent"},
    {"agent": "writer", "start_ms": 400, "end_ms": 800, "kind": "tool", "tool": "bash"},
    {"agent": "writer", "start_ms": 900, "end_ms": 1500, "kind": "tool", "tool": "python"}
  ]
}
```

**实现方式：**
- `on_node_start`: 记录 agent start_time
- `on_tool_call`: 记录 tool start_time
- `on_node_end`: 记录 agent end_time + tool end_time
- 在 `on_workflow_end`: emit timeline chart

**注册：** 加入 `_DEFAULT_HOOKS` 列表

**前端配合：** 新建 `TimelineChartWidget.tsx`，用 Recharts 的 `<BarChart>` 水平布局渲染。

### 改动 3：增强 CircularDetectorPlugin — emit 可视化图表

**文件：** `harness/extensions/plugins/circular_detector.py`

**当前行为：** 检测到循环时 emit `circular.warning` WebSocket 事件。

**增强：** 同时 emit 一个 `category: "analysis"` 的表格或图表，记录循环历史：

```json
{
  "chart_type": "table",
  "category": "analysis",
  "label": "Circular Warnings",
  "title": "Circular Detection Log",
  "data": [
    {"agent": "writer", "tool": "bash", "repeated": 3, "message": "..."}
  ]
}
```

### 改动 4：span 事件补全 parent_span_id

**文件：** `harness/engine/macro_graph.py`

**当前：** `span.start` payload 有 `span_id` 但无 `parent_span_id`。

**增强：** 在构造 span 事件时传入父 span ID：
- agent 节点内的 LLM call → parent = node span
- agent 节点内的 tool call → parent = LLM call span

```python
"parent_span_id": current_llm_span_id or current_node_span_id
```

**数据不外传**，仅存储在 run JSON 的 metadata 中。未来如需对接 OTEL，数据已兼容。

### 改动 5：chart types 扩展

**文件：** `harness/tools/chart.py`, `frontend/src/types/events.ts`, `frontend/src/components/output/ChartWidget.tsx`

新增 `timeline` chart_type 支持。

### 改动 6：移除前端 computeRunSummary

**文件：** 删除 `frontend/src/lib/summary/runSummary.ts`，清理 eventRouter/useWorkflowEvents 中的调用。

**原因：** 后端 Plugin 已负责生成所有 analysis 图表，前端侧生成是冗余的。后端在每次 node 完成时实时 emit，比前端在 workflow 完成时一次性生成更及时。

---

## 改动文件清单

| 文件 | 改动类型 | 风险 |
|------|---------|------|
| `harness/extensions/plugins/perf_metrics.py` | 增强 | 低 |
| `harness/extensions/plugins/timeline.py` | **新建** | 无 |
| `harness/extensions/plugins/circular_detector.py` | 增强 | 低 |
| `harness/extensions/plugins/__init__.py` | 加 1 行注册 | 低 |
| `harness/engine/macro_graph.py` | 补 ttft_ms 到 metadata + parent_span_id | **中** |
| `frontend/src/types/events.ts` | 加 timeline chart_type | 低 |
| `frontend/src/components/output/charts/TimelineChartWidget.tsx` | **新建** | 无 |
| `frontend/src/components/output/ChartWidget.tsx` | 加 1 case | 低 |
| `frontend/src/lib/summary/runSummary.ts` | **删除** | 低 |
| `frontend/src/contexts/workflow-context/eventRouter.ts` | 清理调用 | 低 |
| `frontend/src/hooks/useWorkflowEvents.ts` | 清理调用 | 低 |

---

## 风险评估

### 低风险

- **新建文件**（TimelinePlugin, TimelineChartWidget）：不影响任何现有代码
- **Plugin 增强**（PerfMetrics, CircularDetector）：只增加 emit 调用，不改现有逻辑
- **chart type 扩展**：纯加法，不改现有类型
- **删除 computeRunSummary**：前端改后端，数据流不变

### 中风险

- **macro_graph.py 补 ttft_ms 到 metadata**（~1 行）
  - 风险点：metadata 写入时机（当前在 739-748 行已有同类写入，加一行同类操作）
  - 缓解：紧跟现有模式，不改其他逻辑

- **macro_graph.py 补 parent_span_id**
  - 风险点：需要追踪当前 span 上下文（哪个 LLM call 正在执行）
  - 缓解：仅在 span.start payload 中加一个字段，不影响执行逻辑

### 需先确认的问题

1. **PerfMetricsPlugin 当前是否正常生成图表？** 需要通过 debug 日志确认 `chart.render` 事件是否到达前端。如果 plugin 正常工作，PerfMetrics 已经在生成 token/cost 图表，那增强只需加 duration/ttft/steps。
2. **Timeline chart 的工具执行时间**：`on_tool_call` hook 目前只有 result，没有 start/end 时间。需要确认 hook 是否能拿到工具执行的时间戳，或者是否需要在 macro_graph.py 中补充。

---

## 执行顺序

1. **先确认** PerfMetricsPlugin chart 是否到达前端（已有 debug 日志）
2. **Phase 1**：增强 PerfMetricsPlugin + 补 ttft_ms metadata（低风险，立即见效）
3. **Phase 2**：新建 TimelinePlugin + TimelineChartWidget（新功能，无风险）
4. **Phase 3**：增强 CircularDetectorPlugin + parent_span_id（低风险增强）
5. **Phase 4**：移除前端 computeRunSummary（清理，低风险）
