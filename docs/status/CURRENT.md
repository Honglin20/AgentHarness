# Current Task

**当前任务**: Executor Extensibility Refactor — Phase 2 进行中（ErrorEvent 契约 + 统一错误流）

- ADR: [`docs/refactor/executor-extensibility/ADR.md`](../refactor/executor-extensibility/ADR.md)
- Plan: [`docs/plans/2026-06-26-executor-errors-prompt.md`](../plans/2026-06-26-executor-errors-prompt.md)

## ✅ Phase 1 已完成（2026-06-26）

Prompt 范式分层重构 — 4 task 全过：

1. **P1-T1** Split `base.md` → `base_pydantic.md` + `base_minimal.md`（byte-identical / 无 TodoTool 契约）
2. **P1-T2** assembler 加 `executor` 参数 + `_OUTPUT_FORMAT_MINIMAL_TEMPLATE` + `executor_to_paradigm` + `register_executor_paradigm` override hook + fail-loud on unknown paradigm
3. **P1-T3** `node_factory.py` 调 assembler 时传 `executor=agent_def.executor`，移除 `if result_type is not None` 守卫（修 free-text agent base 注入 bug），`except ValueError: raise` 保留 fail-loud
4. **P1-T4** minimal baseline fixtures（6 golden .txt + manifest）+ 16 个新测试，含 ask_user_demo/greeter 的 forbidden-token / base-prepended / body-survives 验收

70 prompt-related tests green；真实 claude -p smoke 验证模型不再被 pydantic-ai 契约干扰（输出正确识别 ask_user 工具需求，不再 hallucinate final_result）。

→ [完整 release note](../releases/2026-06-26-prompt-paradigm-split.md)

## 🚧 Phase 2 进行中：ErrorEvent 契约 + 统一错误流

10 tasks（详见 Plan）。核心交付：
- `harness/engine/error_event.py` 新建（ErrorEvent dataclass + ExecutorError 基类）
- bus.CRITICAL_EVENT_TYPES 加 `agent.executor_error`
- ClaudeCodeExecutor 内部封装：spawn / stream / result_parse / schema_validate / timeout 各 phase 错误统一 emit + raise ExecutorError
- 翻译器：result.is_error 不再 emit node.failed（让 executor 统一）；新增 `system/api_retry` / `system/status` 翻译
- node_factory except 处理 ExecutorError（不重 emit）
- server/runner.py + cli_runner.py workflow.error payload 扩字段 + schema 对齐
- 前端 workflowStore + eventRouter 加 executor_error / api_retry / workflow_error handler
- 前端 toast / banner UI 显示 stderr_tail + phase + retry_attempt

## ❌ Phase 2 完成后剩余（Phase 3）

CliProfile 抽象 + 用户可注册（11 tasks）。

## 必读文件

- `docs/refactor/executor-extensibility/ADR.md` — 三大决策（Prompt 范式 / ErrorEvent / CliProfile）
- `docs/plans/2026-06-26-executor-errors-prompt.md` — 25 task 拆分（每 task 三阶段 review/test/commit）
- `docs/releases/2026-06-26-prompt-paradigm-split.md` — Phase 1 完整改动 + 验收
- `harness/prompts/assembler.py` — 范式分派入口（`executor_to_paradigm` / `register_executor_paradigm`）
- `harness/engine/node_factory.py:109-127` — assembler 调用点（unconditional + fail-loud ValueError）
- `harness/engine/claude_code_executor.py` — Phase 2 改造目标
- `harness/translator/stream_json.py` — Phase 2 翻译器补全目标
- `server/runner.py:403-431` — workflow.error payload 扩字段目标
- `harness/cli_runner.py` — 与 server 对齐 emit workflow.error 目标
