# 阶段 2：Token 统计语义分离

**日期**: 2026-06-16
**分支**: `main`
**前置**: 阶段 1 ask_user 修复已完成（commits `af923ad` + `01b5c6d`）
**目标**: 区分「累计消耗」（cost 视角）和「当前上下文窗口」（window 视角），让 BudgetBar 不再误显示 500k+

---

## 问题根因（再确认）

1. **Pydantic AI 的 `ctx.state.usage` 在 `iter()` 内累加** —— 每次 model request 把当次 tokens 加进去
2. `agent.usage_update` 事件 payload 携带的是这个累加值（`llm_executor.py:283-284`）
3. `node_factory.py:497-501` 用 `agent_run.usage.input_tokens`（iter 结束后的累加）写入 `token_usage`
4. 前端 `workflowStore.setNodeUsage` 用事件值**覆盖** `node.tokenUsage`
5. `BudgetBar` 把它当"上下文进度条"展示

**结果**：单 agent 跑 5 次 model request（每次 input 20k→35k→50k→65k→80k），累加值 = 250k，但**单次最大上下文只有 80k**。用户看到 500k 以为上下文炸了。

## 不动的部分

- 不改 Pydantic AI 的 usage 累加语义（框架行为，retry 依赖它）
- 不改现有 `input_tokens` / `output_tokens` / `total_tokens` 字段语义（保留为 cumulative，向后兼容所有下游）
- 不持久化新字段到 run_store 主记录（事件 + node.completed payload 足够；replay 时旧事件 fallback 到 input/output）

---

## 接口契约

### 后端：`agent.usage_update` 事件 payload 扩展

**既有字段**（保留语义 = cumulative）：
```python
"input_tokens": int      # 累加值（既有，不动）
"output_tokens": int     # 累加值
"total_tokens": int
"requests": int
```

**新增字段**（附加在旁边，不影响旧消费者）：
```python
"cumulative_input": int   # = input_tokens（语义化别名）
"cumulative_output": int
"last_input": int         # 最近一次 model request 的单次 input
"last_output": int
"cache_hit": int          # prompt cache 命中（cumulative）
```

### 后端：`token_usage` dict 扩展（node_factory 写入 metadata + node.completed）

```python
{
    # 既有
    "input": int, "output": int, "total": int,
    # 新增
    "cumulative_input": int,
    "cumulative_output": int,
    "last_input": int,
    "last_output": int,
    "cache_hit": int,
}
```

### 后端：`LLMExecutor` 状态扩展

```python
class LLMExecutor:
    def __init__(self, ...):
        ...
        # Baseline snapshots for per-request delta computation.
        # Reset at iter() entry (run() method) — NOT at model_request entry,
        # because a single iter() can have multiple model_request nodes
        # (tool call → continue → next model request) and we want last_*
        # to reflect the most recent single request, not the iter total.
        self._baseline_input: int = 0
        self._baseline_output: int = 0
        self._last_input: int = 0
        self._last_output: int = 0
```

**关键算法**（在 `_handle_model_request` 内）：

```python
async def _handle_model_request(self, node, ctx):
    # Snapshot baseline at ENTRY (before this request's usage lands)
    self._baseline_input = ctx.state.usage.input_tokens
    self._baseline_output = ctx.state.usage.output_tokens
    
    ...stream loop...
    
    # After stream completes, ctx.state.usage has been incremented by Pydantic AI.
    # Delta = this request's single-shot usage.
    self._last_input = ctx.state.usage.input_tokens - self._baseline_input
    self._last_output = ctx.state.usage.output_tokens - self._baseline_output
    
    # Fail loud on negative (means baseline was captured after incr — bug)
    if self._last_input < 0 or self._last_output < 0:
        logger.error(
            "usage delta negative: baseline=(%d,%d) current=(%d,%d) — "
            "baseline capture point is wrong",
            self._baseline_input, self._baseline_output,
            ctx.state.usage.input_tokens, ctx.state.usage.output_tokens,
        )
        # Don't crash the workflow — clamp to 0 and emit ext.error
        self._last_input = max(0, self._last_input)
        self._last_output = max(0, self._last_output)
    
    safe_emit(self._bus, "agent.usage_update", {
        ...,
        "input_tokens": ctx.state.usage.input_tokens,  # cumulative (unchanged)
        "output_tokens": ctx.state.usage.output_tokens,
        "total_tokens": ctx.state.usage.input_tokens + ctx.state.usage.output_tokens,
        # NEW
        "cumulative_input": ctx.state.usage.input_tokens,
        "cumulative_output": ctx.state.usage.output_tokens,
        "last_input": self._last_input,
        "last_output": self._last_output,
        "cache_hit": getattr(ctx.state.usage, "cache_read_tokens", 0) or 0,
    })
```

**retry 边界**：`execute_with_retry` 重放整个 iter()，每次 `run_fn()` 构造新的 `agent.iter()`，Pydantic AI 会重置 `ctx.state.usage` 为 0。但 `LLMExecutor` 实例是同一个（在 node_factory 创建一次）。所以：

- 在 `LLMExecutor.run()` 入口（每次 iter 开始）重置 `self._baseline_input = 0`、`self._baseline_output = 0`、`self._last_input = 0`、`self._last_output = 0`
- 这保证 retry 时 baseline 是 0，第一次 `_handle_model_request` 的 baseline 也是 0，差值正确

### 前端：`AgentUsageUpdatePayload` 扩展（`frontend/src/types/events.ts`）

```ts
export interface AgentUsageUpdatePayload {
  workflow_id: string;
  node_id: string;
  agent_name: string;
  requests: number;
  // 既有（保留语义 = cumulative）
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  // 新增（可选 — 旧后端事件不带，handler fallback）
  cumulative_input?: number;
  cumulative_output?: number;
  last_input?: number;
  last_output?: number;
  cache_hit?: number;
}
```

### 前端：`NodeState.tokenUsage` 扩展（`workflowStore.ts`）

```ts
tokenUsage?: {
  // 既有
  input: number;
  output: number;
  total: number;
  // 新增（可选 — 旧事件/replay 时缺失）
  cumulativeInput?: number;
  cumulativeOutput?: number;
  lastInput?: number;
  lastOutput?: number;
  cacheHit?: number;
};
```

`setNodeUsage` 签名扩展（向后兼容：旧调用只传 4 个位置参数）：
```ts
setNodeUsage(
  nodeId: string,
  requests: number,
  inputTokens: number,        // cumulative
  outputTokens: number,       // cumulative
  lastInput?: number,
  lastOutput?: number,
  cacheHit?: number,
): void;
```

### 前端：`agent.usage_update` handler 路由

`agentHandlers.ts:155-183` 现有 delta 计算保持不变（用 cumulative input/output）。新字段透传到 store。

### 前端：`settingsStore` 新增 `modelContextLimit`

```ts
modelContextLimit: number;  // 默认 200_000；用户可改
```

env 透传：后端从 `HARNESS_MODEL_CONTEXT_LIMIT` 读，通过 `/api/settings` 或内联到 index.html 暴露。

简化版（本次实施）：直接前端硬编码默认 200_000，settings UI 暴露输入框（不持久化也行）。后端 env 透传作为 P2 跟进。

### 前端：`BudgetBar` 双进度条

```
Cost     ▓▓▓▓▓▓▓░░░  250k / 500k envelope       (cumulative)
Window   ▓▓░░░░░░░░  80k / 200k ctx limit       (last)
```

- Cost 行：`sum(node.tokenUsage.input + output)` / `envelope.max_tokens`（既有逻辑）
- Window 行：`max(node.tokenUsage.lastInput + lastOutput)` / `settings.modelContextLimit`
  - 用 max 而非 sum，因为窗口是"最大单次"语义
  - 缺 last 字段时 fallback 到 cumulative（旧行为）

### 前端：`DiagnosticsPanel` / `TraceTab`

- `TraceTab.tsx:58-61` 累加 `tokenUsage.total` —— 不改（这是 cost 视角，对的）
- `DiagnosticsPanel.tsx:109` —— 不改
- 新增"Window"列展示 `lastInput + lastOutput`（可选，时间允许再做）

---

## 实施步骤

| 步骤 | 文件 | 改动 | 工作量 |
|---|---|---|---|
| 1 | `harness/engine/llm_executor.py` | 加 baseline 字段 + run() 重置 + `_handle_model_request` 差值 + emit 新字段 | 1h |
| 2 | `harness/engine/node_factory.py:497-501` | `token_usage` dict 加 cumulative_* / last_* / cache_hit | 0.5h |
| 3 | `tests/engine/test_llm_executor.py`（新或扩） | 单次 model request 的 last_input 正确 / 多次累加正确 / retry 后重置 | 1.5h |
| 4 | `frontend/src/types/events.ts` | 扩展 `AgentUsageUpdatePayload` | 0.2h |
| 5 | `frontend/src/stores/workflowStore.ts` | 扩展 `NodeState.tokenUsage` + `setNodeUsage` 签名 | 0.5h |
| 6 | `frontend/src/stores/settingsStore.ts` | 加 `modelContextLimit`（默认 200_000） | 0.3h |
| 7 | `frontend/src/contexts/workflow-context/routing/agentHandlers.ts` | 透传新字段到 `setNodeUsage` | 0.3h |
| 8 | `frontend/src/components/diagnostics/BudgetBar.tsx` | 双进度条 | 1h |
| 9 | 前端单测：`agentHandlers.test.ts` + 新 `BudgetBar.test.tsx` | 验证 last 字段路由 + BudgetBar 双条 | 1.5h |
| 10 | E2E 验证 + frontend build + commit | 跑后端 + 前端套件 | 0.5h |

**总计**：~7-8h（1 个工作日）

---

## 风险与对策

| 风险 | 对策 |
|---|---|
| Baseline 捕获点错（stream 内部多次 incr）→ 负值 | fail loud + clamp 0 + emit ext.error |
| Retry 后 baseline 没重置 → last 算成跨 iter | `LLMExecutor.run()` 入口显式重置 baseline / last |
| 旧 record replay 时事件不带新字段 | 前端 `last_input ?? input_tokens` fallback；BudgetBar 缺 last 时只显示 Cost 行 |
| 多 model request 并发（Pydantic AI 不做，但理论可能）→ baseline race | 实际上 `_handle_model_request` 是 sequential 的（iter 顺序驱动），不会并发；不专门守卫 |
| `cache_read_tokens` 字段名 Pydantic AI 版本变动 | 用 `getattr(usage, "cache_read_tokens", 0) or 0`，缺失时为 0 |

## 不做的事

- 不做 per-model context limit 字典（先用单一 env / settings）
- 不做 token 用量历史曲线（chart）（已有 TraceTab 数字够用）
- 不做 run_store 持久化新字段（事件 + node.completed payload 已覆盖）
- 不改 cost 计算（`calculate_cost` 用 cumulative input + output，正确）

## 测试矩阵

**后端**：
- `test_llm_executor_records_last_usage_per_request` — 一次 iter 内多次 model request，每次 last 正确
- `test_llm_executor_cumulative_resets_on_retry` — retry 后 last 不携带上一轮
- `test_llm_executor_handles_missing_cache_read_tokens` — 旧 Pydantic AI 版本字段缺失
- `test_agent_usage_update_payload_includes_new_fields` — emit 事件包含 last_input / cache_hit

**前端**：
- `agentHandler routes last_input to store` — setNodeUsage 收到 last 参数
- `BudgetBar shows two bars when last fields present` — 双进度条
- `BudgetBar falls back to cumulative when last missing` — 旧事件兼容

## 验收

- 跑 NAS workflow（或更简单的多工具 agent），观察 BudgetBar：
  - Cost 行持续增长（累计消耗）
  - Window 行反映"当前最大单次"，远小于 Cost
- 刷新页面：双进度条仍正确（replay 旧事件时 Window fallback 到 cumulative）
- 后端 + 前端测试全过
