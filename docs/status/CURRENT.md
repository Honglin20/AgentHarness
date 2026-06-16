# Current Task

**当前任务**: 工具与 Token 问题分阶段修复 —— 阶段 1 已完成，准备阶段 2
**状态**: 阶段 1 P0 已落地（ask_user 三缺陷修复）；阶段 2-4 待启动
**日期**: 2026-06-16
**分支**: `main`

## 阶段 1 完成情况

- [x] ask_user emit `chat.answer` / `chat.timeout`（critical priority，进 replay buffer）
- [x] 前端 chatHandlers 处理 chat.answer / chat.timeout（idempotent + 支持 legacy 形态）
- [x] `HARNESS_ASK_USER_TIMEOUT` env 替代硬编码 60s（默认 -1=无限）
- [x] stdin fallback（bus 为 None 时走 stdin，CLI / `python run_workflow(ui=False)` 可用）
- [x] 测试：后端 28 个 + 前端 8 个全过
- [x] 前端 build 成功
- [x] release note + CHANGELOG 已更新

详见 [`docs/releases/2026-06-16-ask-user-refresh-timeout-cli.md`](../releases/2026-06-16-ask-user-refresh-timeout-cli.md)

## 必读文件（阶段 2 启动前）

- `docs/plans/2026-06-16-tooling-token-phase-plan.md` — 全四阶段计划
- `~/.claude/projects/-Users-mozzie-Desktop-Projects-AgentHarness/memory/token-stats-vs-context-window.md` — Token 语义错位根因
- `harness/engine/token_aggregator.py` + `harness/engine/llm_executor.py:170-183` — record/累加逻辑
- `frontend/src/components/diagnostics/BudgetBar.tsx` — UI 展示
- `frontend/src/types/events.ts` — TokenUsage 接口

## 阶段 2 待启动：Token 统计语义分离

目标：把「累计消耗」和「当前上下文窗口」分离展示，避免 BudgetBar 上的 500k+ 让用户误以为上下文炸了。

要点：
- `TokenAggregator` 区分 `cumulative_input_tokens`（累加）和 `last_context_tokens`（最近一次快照）
- `agent.usage_update` 事件增加 `last_context_tokens` 字段
- `BudgetBar` 改成两个进度条：消耗 / 预算 + 当前窗口 / 模型上限
- record 时减去 `cache_hit_tokens`（避免重复计费被误读）

预计 1 天。

## 后续阶段

- 阶段 3：工具结果截断（bash/codegraph_explore 等）— 1 天
- 阶段 4：自动 compaction — 评估中

## 旁路

- NAS workflow ONNX 已完成，等下次跑 NAS 实测验收
- Pre-existing 测试失败（test_chart × 3, test_sub_agent × 1, 前端 workflowHandlers import 问题）与本次改动无关，单独跟踪
