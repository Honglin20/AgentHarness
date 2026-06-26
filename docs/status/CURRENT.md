# Current Task

**当前任务**: Executor Extensibility Refactor — Phase 3 进行中（CliProfile 抽象 + 用户可注册）

- ADR: [`docs/refactor/executor-extensibility/ADR.md`](../refactor/executor-extensibility/ADR.md)
- Plan: [`docs/plans/2026-06-26-executor-errors-prompt.md`](../plans/2026-06-26-executor-errors-prompt.md)

## ✅ Phase 1 已完成（2026-06-26）

Prompt 范式分层 — 4 task 全过。详见 [Phase 1 release note](../releases/2026-06-26-prompt-paradigm-split.md)。

## ✅ Phase 2 已完成（2026-06-26）

ErrorEvent 契约 + 统一错误流 — 10 task 全过：

1. **P2-T1** ErrorEvent dataclass + ExecutorError 异常 + emit-uniqueness 契约
2. **P2-T2** `agent.executor_error` 加入 bus.CRITICAL_EVENT_TYPES（永不淘汰）
3. **P2-T3** ClaudeCodeExecutor 5 phase 错误封装（timeout/spawn/stream/result_parse/schema_validate）
4. **P2-T4** 翻译器调整：result.is_error 不再 emit node.failed + 新增 api_retry/status 翻译
5. **P2-T5** node_factory except 处理 ExecutorError（不重 emit + 富字段填充）
6. **P2-T6** server/runner.py workflow.error payload 扩 7 字段（error_type / executor / phase / stderr_tail / exit_code / executor_extra / failed_node）
7. **P2-T7** cli_runner.py 与 server 共用 `build_workflow_error_payload` helper（CLI/server payload parity）
8. **P2-T8** 前端 events.ts + workflowStore 加 ExecutorErrorPayload / ApiRetryPayload / StatusUpdatePayload + 4 个新 actions
9. **P2-T9** 前端 toast（即时反馈）+ inline banner（持久渲染）+ live badges（retry / status）
10. **P2-T10** e2e mock 测试（spawn 失败 / stream is_error / payload round-trip）

321 测试全绿（282 backend + 25 frontend helper + 14 frontend store）。详见 [Phase 2 release note](../releases/2026-06-26-error-event-contract.md)。

## 🚧 Phase 3 进行中：CliProfile 抽象 + 用户可注册

11 tasks（详见 Plan）。核心交付：
- `harness/engine/cli_profile.py` 新建（CliProfile dataclass + CliExecutorBase）
- `harness/cli_profiles/` 新建（builtin + 项目级 profile 目录，cwd > install fallback）
- ClaudeCodeExecutor 重构为 `CliExecutorBase + ClaudeCliProfile`
- `VALID_EXECUTORS` 改为动态函数（builtin frozenset + runtime registry）
- `executor_factory.py` 改用 profile registry 分派
- env overlay 改 profile-aware（HARNESS_<NAME>_CLI / HARNESS_<NAME>_ENV_*）
- 启动时 load_builtin_profiles + load_project_profiles
- 容错降级：broken profile 不阻塞 server 启动 + HARNESS_DISABLE_PROJECT_PROFILES 开关

## ❌ 跨 Phase 遗留未解决（用户明确要求跟踪）

### 1. ask_user 端到端实测未做

Phase 1 + Phase 2 改造完成（prompt 范式 + ErrorEvent 流）。**完整端到端实测仍未做**：
- events 出现 `agent.tool_call: tool_name=mcp__harness__ask_user`
- 前端弹出问题卡片（AgentQuestionCard）
- 用户答 → ask_user handler resolve → workflow 继续

**当前可手动验证**：启动 server + 前端，跑 ask_user_demo，观察是否调 ask_user 工具。Phase 3 mock opencode profile 任务（P3-T11）会顺带跑通端到端流程。

### 2. ✅ Phase G 翻译器覆盖度 — Phase 2 已闭环

| stream-json 事件 | 状态 |
|---|---|
| `system/init` / `assistant` text/thinking / `result` success | ✅ 已翻译 |
| `result` is_error=true | ✅ Phase 2 闭环（翻译器不再 emit node.failed，executor 统一） |
| `system/api_retry` | ✅ Phase 2 闭环（→ agent.api_retry） |
| `system/status` (requesting/thinking) | ✅ Phase 2 闭环（→ agent.status_update） |

### 3. ✅ 前端 retry UI gap — Phase 2 已闭环

后端 emit 富 payload `workflow.error`；前端 toast（即时反馈）+ inline `ExecutorErrorBanner` + `ApiRetryBadge` + `StatusBadge`（持久 + 实时 retry 计数 + 阶段显示）。Phase 2 task P2-T8/T9/T10 全部完成。

## 必读文件

- `docs/refactor/executor-extensibility/ADR.md` — 三大决策（Prompt 范式 / ErrorEvent / CliProfile）
- `docs/plans/2026-06-26-executor-errors-prompt.md` — 25 task 拆分
- `docs/releases/2026-06-26-prompt-paradigm-split.md` — Phase 1 完整改动
- `docs/releases/2026-06-26-error-event-contract.md` — Phase 2 完整改动
- `harness/engine/error_event.py` — ErrorEvent + ExecutorError + build_workflow_error_payload
- `harness/engine/claude_code_executor.py` — 5-phase 错误封装
- `harness/engine/node_factory.py` — ExecutorError 处理 + assembler 接线
- `harness/translator/stream_json.py` — api_retry/status 翻译
- `harness/extensions/bus.py` — CRITICAL_EVENT_TYPES
- `server/runner.py` + `harness/cli_runner.py` — workflow.error 共用 helper
- `frontend/src/types/events.ts` + `eventSchemas.ts` — 新 payload types
- `frontend/src/stores/workflowStore.ts` — 4 个新 actions
- `frontend/src/components/conversation/` — ExecutorErrorBanner + LiveStatusBadges

