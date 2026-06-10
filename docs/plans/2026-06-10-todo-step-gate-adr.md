# ADR: TODO Step Gate + Output Validator 架构

**Date**: 2026-06-10
**Status**: Accepted（spike 验证通过）
**Related**: [`2026-06-10-conversation-todo-arch-fix.md`](2026-06-10-conversation-todo-arch-fix.md)（根因报告）

## Context

根因 R1（agent 完成判定无 step 检查）+ R2（TODO 工具 op 不完整）导致：
- step 没做完就跳到下一个 agent
- 用户期望"动态更新步骤"硬性不可达
- 现有补丁 `forceTerminalSteps` (R10) 只是症状治疗

## Decision

### D1. Step Gate 通过 pydantic-ai `output_validator` 实现

- 新文件 `harness/engine/step_gate.py`，函数 `step_gate_validator`
- 检查 2 条：`has_plan == True` + 所有 step terminal（completed/skipped）
- 失败抛 `ModelRetry`，由 pydantic-ai 续 iter 重试（**不重启**，保留 message_history）
- 通过 `LLMClient.agent()` 注入，移除 `node_factory.py:462-476` 手工 `validate_output` 调用

### D2. TODO 工具扩展 op

| op | 用途 |
|----|------|
| `create` (现有) | 首次规划 |
| `update` (现有) | 单步状态/内容 |
| `complete_remaining` (**新**) | 批量收尾所有 non-terminal step |
| `replace` (**新**) | 全量重新规划 |
| `list` (现有) | 查看 |

### D3. Step 状态机扩展

新增 `skipped` 状态：
- `pending` → `in_progress` → `completed`（真做了）
- `pending` / `in_progress` → `skipped`（显式放弃）
- terminal 不可逆，重做用 `replace`

### D4. Retry 策略

- `retries={'output': 1, 'tools': N}`：output retry 1 次
- LLM 失败 → ModelRetry → pydantic-ai 自动 retry（保留 history）
- retry 用尽 → `UnexpectedModelBehavior` → 现有 except 接住 → emit `node.failed`
- error_type 区分：`NoTodoPlan` / `UnfinishedSteps` / `OutputValidation`

### D5. 事件契约

新增 critical 事件：
- `todo.bulk_completed`（complete_remaining 触发）
- `todo.replaced`（replace 触发）

加入 `CRITICAL_EVENT_TYPES`，前端 todoHandlers 增加对应 handler。

## Spike 验证

`.spike_model_retry.py` 验证三种 pydantic-ai 调用路径：

| 路径 | 结果 |
|------|------|
| `agent.run()` (non-streaming) | ✅ retry 触发，history 保留 |
| `agent.iter() + node.stream(ctx)` (**本项目路径**) | ✅ retry 触发，history 保留 |
| `agent.run_stream()` (streaming output) | ❌ pydantic-ai 不支持 retry |

**结论**：本项目 `llm_executor.py` 用 `agent.iter()` + `node.stream()` 路径，validator 完美工作。

## Consequences

### Positive
- step 跳步问题根治（hard gate）
- LLM 粗心错误自动修复（1 次 retry）
- 删除 `forceTerminalSteps` 补丁（症状治疗）
- 删除 `nodeHandler` 冗余 `addAgentMessage`（R6）
- 删除手工 `validate_output`（schema 错误也能 retry）
- conversation ↔ todo 联动清理（currentStepIdByNode）

### Negative
- **老 run 不兼容**：旧 run 没有 todo.create 事件 → step gate 直接 fail。已与用户确认"不需要适配旧 run"。
- **`agent.run_stream()` 禁用**：在 LLMExecutor 加防御性检查。
- retry 时 message_history 多 1 条 RetryPromptPart → token 计费略增（影响可忽略）。

## 实施阶段

| 阶段 | 任务 | 文件 |
|------|------|------|
| 1 | TODO op 扩展 + 事件 | `todo.py` / `bus.py` |
| 2 | step_gate validator + schema 迁移 | `step_gate.py`(新) / `llm.py` / `node_factory.py` |
| 3 | 前端联动 | `events.ts` / `eventSchemas.ts` / `todoHandlers.ts` / `todo.ts` / `nodeHandlers.ts` / `AgentQuestionCard.tsx` |
| 4 | system prompt + 集成测试 | system prompt 注入 / 端到端测试 |
