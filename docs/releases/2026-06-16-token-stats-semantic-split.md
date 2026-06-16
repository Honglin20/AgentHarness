# 阶段 2：Token 统计语义分离

**日期**: 2026-06-16
**Plan**: [`docs/plans/2026-06-16-token-stats-semantic-split.md`](../plans/2026-06-16-token-stats-semantic-split.md)
**分支**: `main`

## 背景

用户报告跑 NAS workflow 看到 BudgetBar 显示 500k+ token，但 output 仅 7k，怀疑上下文炸了。实际是**统计语义错位**：

- Pydantic AI 的 `ctx.state.usage` 在 `iter()` 内**累加**每次 model request 的 input_tokens
- `agent.usage_update` 事件 payload 携带累加值（`llm_executor.py:283-284`）
- 前端 `workflowStore.setNodeUsage` 用累加值覆盖 `node.tokenUsage`
- BudgetBar 把累加值当"上下文进度条"展示

**举例**：单 agent 跑 5 次 model request，每次 input 20k→35k→50k→65k→80k，累加值 = 250k，但**单次最大上下文只有 80k**。用户看到的"500k 上下文"其实是累计消耗。

## 改动

### 后端

**`harness/engine/llm_executor.py`**：
- `LLMExecutor.__init__`：加 `_baseline_input` / `_baseline_output` / `_baseline_cache_hit` / `_last_input` / `_last_output` / `_last_cache_hit` 六个字段
- `LLMExecutor.run()`：在 iter 入口显式重置所有 baseline / last 字段，覆盖 retry 边界
- `_handle_model_request`：
  - 进入时捕获 baseline（`ctx.state.usage` 当前的 input/output/cache_read）
  - 退出时算 delta = current - baseline，得单次 usage
  - delta 为负（baseline 捕获点错）→ log error + emit `ext.error` + clamp 到 0（不阻塞 workflow）
  - emit `agent.usage_update` 时附加 `cumulative_input` / `cumulative_output` / `last_input` / `last_output` / `cache_hit` 五个新字段
  - 保留 `input_tokens` / `output_tokens` / `total_tokens` 语义不变（cumulative，向后兼容）
- 新方法 `get_last_request_usage()` 返回最近一次单次快照，供 node_factory 在 iter 结束后读取

**`harness/engine/node_factory.py:494-518`**：
- `token_usage` dict 扩展：加 `cumulative_input` / `cumulative_output` / `last_input` / `last_output` / `cache_hit`
- 从 `executor.get_last_request_usage()` 读 last 字段，写进 node.completed payload 和 metadata

### 前端

**`frontend/src/types/events.ts`**：`AgentUsageUpdatePayload` 加 5 个可选字段（cumulative_input / cumulative_output / last_input / last_output / cache_hit）

**`frontend/src/stores/workflowStore.ts`**：
- `NodeState.tokenUsage` 扩展可选字段（cumulativeInput / cumulativeOutput / lastInput / lastOutput / cacheHit）
- `setNodeUsage` 签名加 3 个可选参数（lastInput / lastOutput / cacheHit）

**`frontend/src/stores/settingsStore.ts`**：新增 `modelContextLimit`（默认 200_000，localStorage 持久化）

**`frontend/src/contexts/workflow-context/routing/agentHandlers.ts`**：`agent.usage_update` handler 透传 last_input / last_output / cache_hit 到 `setNodeUsage`

**`frontend/src/components/diagnostics/BudgetBar.tsx`**：
- 原 "Tokens" 行重命名为 "Cost"（明确语义：累计消耗 / envelope 预算）
- 新增 "Window" 行：`max(node.tokenUsage.lastInput + lastOutput)` / `settings.modelContextLimit`
  - 用 max 而非 sum（单 agent 上下文压力 = 最大那次请求，不是总和）
  - 缺 last 字段时 fallback 到 cumulative（旧行为兼容）

## 验证

**后端测试**（`tests/engine/test_llm_executor.py`，新增 5 个）：
- `test_last_input_single_request` — 单次请求 last == cumulative
- `test_last_input_multi_request_is_delta` — 三次请求，last 反映最近一次 delta，cumulative 持续增长
- `test_usage_resets_on_run_reentry` — run() 重入 baseline 重置（retry 边界）
- `test_cache_read_tokens_missing_defaults_to_zero` — 旧 Pydantic AI 版本兼容
- `test_get_last_request_usage_returns_zero_before_any_run` — 新 executor 初始状态

**前端测试**（`agentHandlers.test.ts`，新增 2 个）：
- `routes stage-2 fields to setNodeUsage` — last_input/output/cache_hit 透传
- `falls back gracefully when stage-2 fields absent` — 旧后端事件兼容

**结果**：
- 后端 78 个测试全过（test_llm_executor + test_ask_user + test_ws_handler + test_run_store）
- 前端 8 个 routing 测试全过
- TypeScript 类型检查干净
- Frontend build 成功

## 风险与对策

| 风险 | 状态 |
|---|---|
| Baseline 捕获点错 → 负值 | ✅ fail loud (log + ext.error) + clamp 0 |
| Retry 后 baseline 没重置 → 跨 iter 错乱 | ✅ run() 入口显式重置 |
| 旧 record replay 缺新字段 | ✅ 前端 `last_input ?? cumulative_input` fallback |
| `cache_read_tokens` Pydantic AI 版本差异 | ✅ `getattr(..., 0) or 0` 防御 |
| 多 model request 并发 baseline race | 不守卫（iter 顺序驱动，无并发） |

## 不做的事

- 不改 Pydantic AI usage 累加语义（框架行为）
- 不持久化 last 字段到 run_store（事件 + node.completed 已覆盖）
- 不做 per-model context limit 字典（先用单一 settings）
- 不改 `calculate_cost`（用 cumulative input + output，正确）

## 下一步

阶段 3：工具结果截断（bash/codegraph_explore 等长输出超阈值截断，治本降 token）— 1 天
