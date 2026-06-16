# Current Task

**当前任务**: 工具与 Token 问题分阶段修复 —— 阶段 1 完成（含 review 修补），准备阶段 2
**状态**: 阶段 1 P0 + P1 review follow-ups 全部落地；阶段 2 待启动
**日期**: 2026-06-16
**分支**: `main`

## 阶段 1 完成情况

**Commits**:
- `af923ad` — 阶段 1 P0：emit chat.answer/timeout + 超时 env + stdin fallback
- `01b5c6d` — P1 review follow-ups：float timeout / EOF raise / stdin lock + 测试缺口

**Review 判定**: ship with follow-ups（无阻塞性问题，3 个 P1 已修，3 个 P2 推后跟踪）

### P0 改动（commit af923ad）
- [x] ask_user emit `chat.answer` / `chat.timeout`（critical priority，进 replay buffer）
- [x] 前端 chatHandlers 处理 chat.answer / chat.timeout（idempotent + legacy 形态）
- [x] `HARNESS_ASK_USER_TIMEOUT` env 替代硬编码 60s（默认 -1=无限）
- [x] stdin fallback（bus 为 None 时走 stdin）

### P1 Review Follow-ups（commit 01b5c6d）
- [x] `_resolve_timeout` 接受 float seconds（`"1.5"` 不再误报 "not an integer"）
- [x] stdin EOFError → raise RuntimeError（不再 silent return ""）
- [x] stdin 并发守卫：进程级 `asyncio.Lock` 防止两个 prompt 物理交错
- [x] 测试缺口补：float timeout / EOFError raises / stdin lock 序列化 / interrupted skip / orphan answer

详见 [`docs/releases/2026-06-16-ask-user-refresh-timeout-cli.md`](../releases/2026-06-16-ask-user-refresh-timeout-cli.md)

### P2 推后项（review 标记，不阻塞阶段 2）

| 项 | 位置 | 优先级 | 说明 |
|---|---|---|---|
| chat.answer silent-drop dev warning | `chatHandlers.ts:82-87` | P2 | 当前静默丢弃未知 question_id 的 answer；加 `console.warn` 便于调试 |
| rawToAnswer legacy 双模式丢失 | `chatHandlers.ts:25-27` | P3 | legacy `{answer}` 形态无法表达 selected+custom_input 同时存在；实际无 legacy 生产者，de-prioritize |
| ask_user 集成测试（端到端 WS replay） | 新文件 | P2 | 当前 chatHandlers 是单元测试；应补一个 mock WS 流的真集成测试 |

## 必读文件（阶段 2 启动前）

- `docs/plans/2026-06-16-tooling-token-phase-plan.md` — 全四阶段计划
- `~/.claude/projects/-Users-mozzie-Desktop-Projects-AgentHarness/memory/token-stats-vs-context-window.md` — Token 语义错位根因
- `harness/engine/token_aggregator.py` + `harness/engine/llm_executor.py:170-183` — record/累加逻辑
- `frontend/src/components/diagnostics/BudgetBar.tsx` — UI 展示
- `frontend/src/types/events.ts` — TokenUsage 接口

## 阶段 2 待启动：Token 统计语义分离

**目标**：把「累计消耗」和「当前上下文窗口」分离展示，避免 BudgetBar 上的 500k+ 让用户误以为上下文炸了。

**要点**：
- `TokenAggregator` 区分 `cumulative_input_tokens`（累加）和 `last_context_tokens`（最近一次快照）
- `agent.usage_update` 事件增加 `last_context_tokens` 字段
- `BudgetBar` 改成两个进度条：消耗 / 预算 + 当前窗口 / 模型上限
- record 时减去 `cache_hit_tokens`（避免重复计费被误读为窗口炸了）

**预计工作量**：1 天

## 后续阶段

- 阶段 3：工具结果截断（bash/codegraph_explore 等）— 1 天
- 阶段 4：自动 compaction — 评估中

## 旁路

- NAS workflow ONNX 已完成（上轮任务），等下次跑 NAS 实测验收
- Pre-existing 测试失败（test_chart × 3, test_sub_agent × 1, 前端 workflowHandlers `@/lib/summary/runSummary` import 问题）与本次改动无关，单独跟踪
