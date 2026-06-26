# Current Task

**当前任务**: Executor Extensibility Refactor — **全部完成（Phase 1 + 2 + 3）**

- ADR: [`docs/refactor/executor-extensibility/ADR.md`](../refactor/executor-extensibility/ADR.md) (Status: Accepted)
- Plan: [`docs/plans/2026-06-26-executor-errors-prompt.md`](../plans/2026-06-26-executor-errors-prompt.md)

## ✅ Phase 1 已完成（2026-06-26）

Prompt 范式分层 — 4 task 全过。详见 [Phase 1 release note](../releases/2026-06-26-prompt-paradigm-split.md)。

## ✅ Phase 2 已完成（2026-06-26）

ErrorEvent 契约 + 统一错误流 — 10 task 全过。详见 [Phase 2 release note](../releases/2026-06-26-error-event-contract.md)。

## ✅ Phase 3 已完成（2026-06-26）

CliProfile 抽象 + 用户可注册 — 11 task 全过：

1. **P3-T1** `harness/engine/cli_profile.py` — CliProfile dataclass + registry
2. **P3-T2** `harness/engine/_cli_subprocess.py` — generic `run_cli`
3. **P3-T3** `harness/cli_profiles/__init__.py` + `claude.py` — builtin + project-level discovery
4. **P3-T4** ClaudeCodeExecutor 接 profile 参数（profile-driven cli_path / extractor / name）
5. **P3-T5** `VALID_EXECUTORS` 改为函数（动态合并 BUILTIN_EXECUTORS + profile registry）
6. **P3-T6** `executor_factory.py` 通过 `get_profile(backend)` 分派
7. **P3-T7** env overlay 改 profile-aware（HARNESS_<NAME>_ENV_<KEY> per-profile override）
8. **P3-T8** server/app.py + harness/cli.py 启动加载 builtin + project profiles
9. **P3-T9** broken profile 自动 disable + 详细 reason；不阻塞启动
10. **P3-T10** README + CLAUDE.md 文档（执行器与 CLI Profile）
11. **P3-T11** e2e mock 测试（自定义 opencode profile 端到端验证）

367 backend 测试 + 291 frontend 测试全绿。详见 [Phase 3 release note](../releases/2026-06-26-cli-profile-abstraction.md)。

## ❌ 跨 Phase 遗留未解决（用户明确要求跟踪）

### 1. ask_user 端到端实测未做

P1 + P2 + P3 改造完成（prompt 范式 / ErrorEvent 流 / profile-driven executor）。**完整端到端实测仍未做**：
- events 出现 `agent.tool_call: tool_name=mcp__harness__ask_user`
- 前端弹出问题卡片（AgentQuestionCard）
- 用户答 → ask_user handler resolve → workflow 继续

**当前可手动验证**：启动 server + 前端，跑 ask_user_demo，观察是否调 ask_user 工具。Phase 1 smoke 已验证模型识别 ask_user 需求；MCP server 起来后理论上能完成调用。

### 2. ✅ Phase G 翻译器覆盖度 — Phase 2 闭环

### 3. ✅ 前端 retry UI gap — Phase 2 闭环

## 必读文件

- `docs/refactor/executor-extensibility/ADR.md` — 三大决策（Status: Accepted）
- `docs/plans/2026-06-26-executor-errors-prompt.md` — 25 task 拆分
- `docs/releases/2026-06-26-prompt-paradigm-split.md` — Phase 1 完整改动
- `docs/releases/2026-06-26-error-event-contract.md` — Phase 2 完整改动
- `docs/releases/2026-06-26-cli-profile-abstraction.md` — Phase 3 完整改动
- `harness/engine/cli_profile.py` — CliProfile + registry
- `harness/cli_profiles/__init__.py` + `claude.py` — builtin profile discovery
- `harness/engine/_cli_subprocess.py` — generic run_cli
- `harness/engine/claude_code_executor.py` — profile-driven executor
- `harness/engine/executor_factory.py` — registry-based dispatch
- `harness/core/agent.py` — VALID_EXECUTORS dynamic function
- `harness/engine/error_event.py` — ErrorEvent + ExecutorError + build_workflow_error_payload
- `server/app.py` + `harness/cli.py` — startup profile loading


