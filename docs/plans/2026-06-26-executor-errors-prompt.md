# Plan: Executor Extensibility + Unified Error Flow + Layered Prompt

**Date**: 2026-06-26
**ADRs**: [`docs/refactor/executor-extensibility/ADR.md`](../refactor/executor-extensibility/ADR.md)
**Parent Task**: `docs/status/CURRENT.md` 三个未解决项 + 用户反馈

按 SDD：本计划紧接 ADR 审批后执行。**Phase 间禁并行**（依赖：P2 用 P1 的范式字段；P3 用 P2 的 ExecutorError）。**Phase 内 task 可顺序执行**（同一 Phase 内 task 间有依赖时按 ID 顺序）。

---

## 通用 Workflow（每个 task 强制走三阶段）

```
[实施] → [Review] → [Test] → [Commit] → [Status Update]
```

### 1. Review（代码审查）
- 用 `superpowers:code-reviewer` 子代理对 diff 审查（独立 context，不看我视角）
- 审查清单：
  - 是否满足本 task 的 **Acceptance Criteria**（功能）
  - 是否满足本 task 的 **Test Criteria**（测试覆盖）
  - 是否引入 CLAUDE.md 禁止行为（hack / 兼容代码 / 静默吞错）
  - 是否符合 ADR 不变量（ErrorEvent 唯一性 / Prompt 范式二选一 / Profile 注册幂等等）
- Review fail → 回 [实施] 修正，不进 Test

### 2. Test（测试）
- 跑 `make test`（Python 全量）+ `cd frontend && npm test`（前端全量）+ `make lint-runs`（runs 持久化契约）
- 跑本 task **Test Criteria** 列出的所有专项测试
- e2e 验证（task 标注 "e2e" 的）：手动启动 server / CLI 跑一遍，对照 Acceptance Criteria
- Test fail → 回 [实施] 修正，不进 Commit

### 3. Commit（提交）
- Commit message 格式：`{type}({scope}): P{n}-T{m} {desc}`
  - type: `feat` / `fix` / `refactor` / `test` / `docs`
  - scope: 简短模块名（`prompt` / `executor` / `translator` / `cli-runner` / `frontend` / ...）
  - desc: 一句话说明
- 多 task 同 PR 时，每 task 一个独立 commit（便于回滚）
- **不**用 `--no-verify` / `--amend`（按 CLAUDE.md 全局规则）

### 4. Status Update（状态更新）
- task 完成后立即更新 CURRENT.md（移到 "已完成" 段或移除）
- Phase 全部 task 完成后：写 release note + CHANGELOG 加索引 + CURRENT.md 清空对应未解决项

---

# Phase 1 — Prompt 分层（pydantic-ai 范式 / minimal 范式）

**目标**：claude-code 路径不再被 pydantic-ai 工具契约污染；ask_user_demo 跑通。

**Phase 完成定义**：跑 `ask_user_demo` workflow，greeter 节点真实调用 `mcp__harness__ask_user` 工具（前端能看到 tool_call + 弹问题卡片 + 用户答 → resolve），且 prompt 字符串内**不**含 `final_result` / `TodoTool` 等 pydantic-ai 专属契约。

---

### Task P1-T1: 拆 base.md → base_pydantic.md + base_minimal.md

**Scope**:
- 新建 `harness/prompts/base_pydantic.md`
- 新建 `harness/prompts/base_minimal.md`
- 删除 `harness/prompts/base.md`

**Acceptance Criteria**:
- [ ] `base_pydantic.md` 内容 == 原 `base.md`（byte-level 一致，含 `TodoTool MUST` / `final_result` 段落）
- [ ] `base_minimal.md` 保留以下段落（跨 executor 通用工作范式）：
  - "Plan before you act"（保留"plan intent"段，去掉 TodoTool MUST 措辞）
  - "Narrate before you call"
  - "Coordinate your tools"
  - "Handle failure loudly"
  - "Finish cleanly"（保留"finish cleanly"语义，去掉 `final_result` tool 强制）
- [ ] `base_minimal.md` 不含以下字符串：`TodoTool` / `final_result` / `MUST be.*create` / `complete_remaining`
- [ ] 原 `base.md` 已删除

**Test Criteria**:
- [ ] 手动 grep 验证：`grep -E "TodoTool|final_result" harness/prompts/base_minimal.md` 返回空
- [ ] byte-level diff：`base_pydantic.md` == 改前的 `base.md`（用 `git show HEAD:harness/prompts/base.md` 对比）

**Workflow**: Review → Test → Commit (`refactor(prompt): P1-T1 split base.md into paradigm-specific files`)

---

### Task P1-T2: assembler.py 加 executor 参数 + minimal output format 模板

**Scope**: `harness/prompts/assembler.py`

**Acceptance Criteria**:
- [ ] `assemble_static_prompt` 签名：`(agent_md_body, result_type, *, executor="pydantic-ai") -> str`
- [ ] `_load_base_layer()` 改为 `_load_base_layer(executor: str) -> str`，按 executor 返回 `base_pydantic.md` 或 `base_minimal.md`
- [ ] 新增 `_OUTPUT_FORMAT_MINIMAL_TEMPLATE`：措辞为 "respond with a JSON object matching this schema"，不引用 `final_result` tool
- [ ] 原 `_OUTPUT_FORMAT_TEMPLATE` 重命名为 `_OUTPUT_FORMAT_PYDANTIC_TEMPLATE`
- [ ] `_output_format_section(result_type, executor)` 按 executor 选模板
- [ ] executor 值未知（不在 `{"pydantic-ai", "minimal-paradigm-set"}`）→ fail-loud 抛 `ValueError`

**Test Criteria**:
- [ ] 新增 `tests/test_prompt_assembler.py::test_pydantic_paradigm_byte_level_unchanged`：传 `executor="pydantic-ai"`，输出 byte-level 等于改前 fixture
- [ ] 新增 `test_minimal_paradigm_no_final_result_tool`：传 `executor="claude-code"`，输出**不**含 `final_result` / `TodoTool` 字符串
- [ ] 新增 `test_unknown_executor_raises`：传 `executor="xxx"` 抛 `ValueError`
- [ ] `tests/test_prompt_baseline.py` 全绿（pydantic-ai 路径 baseline 不变）

**Workflow**: Review → Test → Commit (`feat(prompt): P1-T2 add executor-aware assembler + minimal output format`)

---

### Task P1-T3: node_factory.py 调用 assembler 时传 executor

**Scope**: `harness/engine/node_factory.py:117`

**Acceptance Criteria**:
- [ ] `assemble_static_prompt` 调用改为传 `executor=agent_def.executor`
- [ ] deps 构造的 `agent_md_content=augmented_prompt` 不变（ClaudeCodeExecutor 透明消费）
- [ ] 不改任何其他调用点（pydantic-ai 路径透明保持）

**Test Criteria**:
- [ ] `make test` 全绿（所有 node_factory 单测）
- [ ] e2e: 跑 pydantic-ai workflow（如 `demo_pipeline`），输出 prompt byte-level 等于改前
- [ ] e2e: 跑 claude-code workflow（如 `ask_user_demo`），prompt 不含 `final_result` 字符串

**Workflow**: Review → Test → Commit (`feat(prompt): P1-T3 wire executor param at node_factory call site`)

---

### Task P1-T4: 重生成 prompt baseline + ask_user_demo 端到端验证

**Scope**:
- `tests/capture_prompt_baseline.py`（如需调整）
- `tests/test_prompt_baseline.py`
- `tests/fixtures/prompt_baseline/`（新增 minimal 范式 fixture）

**Acceptance Criteria**:
- [ ] pydantic-ai 路径 fixture 重生成，byte-level 与改前一致
- [ ] 新增 minimal 范式 fixture（claude-code executor 的 prompt 样本）
- [ ] **关键验收**：跑 `ask_user_demo` workflow，前端能看到：
  - `agent.tool_call` 事件，`tool_name=mcp__harness__ask_user`
  - 弹出问题卡片
  - 用户答 → `agent.tool_result` 事件 → workflow 继续
- [ ] prompt 字符串扫描：`ask_user_demo` 跑出来的 `system_prompt` 字段（`agent_io.system_prompt`）不含 `final_result` / `TodoTool` 字符串

**Test Criteria**:
- [ ] `tests/test_prompt_baseline.py` 全绿
- [ ] 手动 e2e（按上面 Acceptance Criteria 走一遍）
- [ ] 在 `/tmp/claude-exit-debug-*.log`（spawn 失败 debug log）验证 prompt 已切到 minimal 范式

**Workflow**: Review → Test → Commit (`test(prompt): P1-T4 regenerate baseline + verify ask_user_demo e2e`)

---

### Phase 1 收尾

- [ ] 写 release note: `docs/releases/2026-06-26-prompt-paradigm-split.md`
- [ ] CHANGELOG 顶部加索引
- [ ] CURRENT.md "未解决 #1" 移到 CHANGELOG
- [ ] **Phase gate**: 跑 `make test` + 前端 `npm test` + ask_user_demo e2e 全过 → 进 Phase 2

---

# Phase 2 — ErrorEvent 契约 + 统一错误流

**目标**：claude -p 报错前端实时看到（含 stderr / phase / retry）；CLI 与 server 错误流对齐。

**Phase 完成定义**：故意配错 `ANTHROPIC_BASE_URL` → 前端 toast 实时显示 stderr_tail + phase + retry_attempt；CLI 路径打印同样字段到 stderr/Rich TUI。

---

### Task P2-T1: 新建 error_event.py + ExecutorError 异常基类

**Scope**: 新建 `harness/engine/error_event.py`

**Acceptance Criteria**:
- [ ] `ErrorEvent` dataclass，字段见 ADR Decision 2（workflow_id / node_id / agent_name / executor / phase / error_type / error_message / stderr_tail / exit_code / timed_out / retry_attempt / ts）
- [ ] `ExecutorError(RuntimeError)`：`__init__(message, error_event)`，存 `self.error_event`
- [ ] 模块级 docstring 说明 emit 唯一性约束（每个错误只在一个位置 emit）

**Test Criteria**:
- [ ] 新增 `tests/test_executor_error_event.py::test_error_event_fields`
- [ ] 新增 `test_executor_error_carries_event`
- [ ] 类型检查（mypy / pyright）通过

**Workflow**: Review → Test → Commit (`feat(executor): P2-T1 add ErrorEvent + ExecutorError base`)

---

### Task P2-T2: bus.py CRITICAL_EVENT_TYPES 加 agent.executor_error

**Scope**: `harness/extensions/bus.py`

**Acceptance Criteria**:
- [ ] `CRITICAL_EVENT_TYPES` frozenset 新增 `"agent.executor_error"`
- [ ] 注释说明：executor_error 是 critical 因为下游错过会导致 UI 永远显示 "running"（与 workflow.error 同级理由）

**Test Criteria**:
- [ ] 新增 `tests/test_bus_critical_types.py::test_executor_error_is_critical`
- [ ] 现有 bus 测试全绿

**Workflow**: Review → Test → Commit (`feat(bus): P2-T2 mark agent.executor_error as critical`)

---

### Task P2-T3: 改 ClaudeCodeExecutor 内部封装 + emit + raise ExecutorError

**Scope**: `harness/engine/claude_code_executor.py`

**Acceptance Criteria**:
- [ ] 新增 `_emit_executor_error(event: ErrorEvent)` async 方法：emit `agent.executor_error` 到 bus
- [ ] spawn 错（exit_code != 0）：构造 ErrorEvent（phase="spawn"）→ emit → raise `ExecutorError`
- [ ] stream 错（result.is_error=true，从 `_extract_pre_translate` 标记）：phase="stream"，同上
- [ ] result_text 为空（claude exit 0 但无 result）：phase="result_parse"，同上
- [ ] schema_validate 错（已有 `SchemaValidationError`）：在 `_extract_and_validate_result` 包装一层，phase="schema_validate"
- [ ] timeout（claude_result.timed_out=True）：phase="spawn"，timed_out=True
- [ ] **删除** 当前 line 209-214 / 217-221 的 `raise RuntimeError(...)`，全部替换为 ExecutorError 路径

**Test Criteria**:
- [ ] `tests/test_claude_code_executor_error_paths.py`：mock 各 phase 错误，断言 emit + raise
- [ ] `test_no_runtime_error_raised_directly`：grep `claude_code_executor.py` 不含 `raise RuntimeError`
- [ ] 现有 ClaudeCodeExecutor 测试（如有 mock exit_code=0 路径）保持绿

**Workflow**: Review → Test → Commit (`refactor(executor): P2-T3 wrap ClaudeCodeExecutor errors as ExecutorError`)

---

### Task P2-T4: 翻译器 stream_json.py 调整（result.is_error + api_retry + status）

**Scope**: `harness/translator/stream_json.py`

**Acceptance Criteria**:
- [ ] `_translate_result`：`is_error=true` 分支**删除**（不再 emit `node.failed`）— executor 统一发
- [ ] 新增 `_translate_system_subtype_api_retry`：emit `agent.api_retry`，payload `{retry_count, max_retries, wait_seconds}`
- [ ] 新增 `_translate_system_subtype_status`：emit `agent.status_update`，payload `{status: "thinking"|"requesting"|...}`
- [ ] `_translate_system` 改为按 subtype 分派到具体子函数
- [ ] 未知 subtype 仍走 defensive parsing（不抛）

**Test Criteria**:
- [ ] `tests/test_translator_api_retry.py::test_api_retry_translated`
- [ ] `tests/test_translator_status.py::test_status_translated`
- [ ] `tests/test_translator_result_is_error.py::test_result_is_error_does_not_emit_node_failed`
- [ ] 现有翻译器测试全绿

**Workflow**: Review → Test → Commit (`refactor(translator): P2-T4 split result.is_error path + add api_retry/status`)

---

### Task P2-T5: node_factory.py except 处理 ExecutorError

**Scope**: `harness/engine/node_factory.py:656-714`

**Acceptance Criteria**:
- [ ] except 块开头加 `if isinstance(e, ExecutorError)` 分支：
  - 从 `e.error_event` 取 `stderr_tail` / `phase` / `executor` 塞进 `extra` 字段
  - error_type 改用 `e.error_event.error_type`（更精确）
  - **不重 emit** `agent.executor_error`（executor 已 emit）
- [ ] 现有 RuntimeError 路径（其他异常）保持不变
- [ ] tool_calls_before_failure / io_data 等字段保留填充逻辑

**Test Criteria**:
- [ ] `tests/test_node_factory_executor_error.py::test_executor_error_not_re_emitted`
- [ ] `test_executor_error_extra_fields_populated`
- [ ] `test_non_executor_error_unchanged_behavior`
- [ ] 现有 node_factory 测试全绿

**Workflow**: Review → Test → Commit (`feat(node-factory): P2-T5 propagate ExecutorError fields without re-emit`)

---

### Task P2-T6: server/runner.py workflow.error payload 扩字段

**Scope**: `server/runner.py:403-431`（`_run_workflow` except 块）

**Acceptance Criteria**:
- [ ] `workflow.error` payload 扩字段：`error_type` / `executor` / `phase` / `stderr_tail` / `failed_node`
- [ ] `executor` 从 `agents_snapshot` 推断（找最近 `node.failed` 事件的 node_id 对应 agent 的 executor）
- [ ] `phase` / `stderr_tail` 从 `getattr(e, "error_event", None)` 取（非 ExecutorError 时为 None）
- [ ] `failed_node` 从 event_bus.buffer 反向扫最近一个 `node.failed` 事件的 node_id
- [ ] 老 payload 字段（`workflow_id` / `user_id` / `error` / `batch_id`）保持兼容

**Test Criteria**:
- [ ] `tests/test_runner_workflow_error_payload.py::test_payload_includes_stderr_tail_on_executor_error`
- [ ] `test_payload_handles_non_executor_error`
- [ ] `test_failed_node_extracted_from_bus_buffer`
- [ ] 现有 server runner 测试全绿

**Workflow**: Review → Test → Commit (`feat(server): P2-T6 enrich workflow.error payload with executor context`)

---

### Task P2-T7: cli_runner.py 加 workflow.error emit（与 server 对齐）

**Scope**: `harness/cli_runner.py`

**Acceptance Criteria**:
- [ ] 现有失败路径加 `bus.emit("workflow.error", payload)`，payload schema 与 P2-T6 server 一致
- [ ] 解掉 `cli_runner.py:19-24` 旧设计约束注释（"不动 server" → "错误流是共享契约，必须对齐"）
- [ ] CLI 模式仍走 Rich TUI 渲染错误（不依赖前端）

**Test Criteria**:
- [ ] `tests/test_cli_runner_error_emit.py::test_cli_emits_workflow_error_on_failure`
- [ ] `test_cli_error_payload_matches_server_schema`（schema parity 测试）
- [ ] 手动 `harness run <wf>` 跑错配 env 验证 stderr 输出含富字段

**Workflow**: Review → Test → Commit (`feat(cli-runner): P2-T7 emit workflow.error with server-parity payload`)

---

### Task P2-T8: 前端 events.ts + workflowStore 加新事件类型

**Scope**:
- `frontend/src/types/events.ts`
- `frontend/src/types/eventSchemas.ts`
- `frontend/src/stores/workflowStore.ts`

**Acceptance Criteria**:
- [ ] `events.ts` 新增 type: `ExecutorErrorPayload` / `ApiRetryPayload` / `StatusUpdatePayload`
- [ ] `WorkflowErrorPayload` 扩字段（与后端 P2-T6 schema 对齐）
- [ ] `eventSchemas.ts` zod schema 同步
- [ ] `workflowStore.ts` 加 `handleWorkflowError(payload)`：
  - 把 error 写入 `nodes[payload.failed_node].error`
  - 把 stderr_tail / phase 写入 `nodes[payload.failed_node]` 扩字段
  - status 置 `"failed"`
  - 调用 `sweepOrphanRunning`（已有逻辑）
- [ ] 加 `pushApiRetry(nodeId, attempt)` action（实时 retry 计数）

**Test Criteria**:
- [ ] `frontend/src/stores/__tests__/workflowStore.test.ts` 新增 cases:
  - `handleWorkflowError_sets_node_error_and_status_failed`
  - `handleWorkflowError_preserves_orphan_sweep_semantics`
  - `pushApiRetry_increments_count`
- [ ] 现有前端测试全绿（含 orphanSweep test）

**Workflow**: Review → Test → Commit (`feat(frontend): P2-T8 add executor_error / api_retry / workflow_error handlers`)

---

### Task P2-T9: 前端 toast / banner UI 显示富错误信息

**Scope**:
- `frontend/src/contexts/workflow-context/eventRouter.ts`
- `frontend/src/contexts/workflow-context/routing/workflowHandlers.ts`
- `frontend/src/components/...`（具体 toast / banner 组件）

**Acceptance Criteria**:
- [ ] `eventRouter.ts` 路由 `agent.executor_error` → 调 `workflowStore.pushApiRetry` 或新 action
- [ ] `eventRouter.ts` 路由 `workflow.error` → 调 `handleWorkflowError`
- [ ] toast / banner UI 显示：`phase` + `error_type` + `stderr_tail`（前 200 字）+ retry_attempt 计数
- [ ] retry_attempt 实时显示（每次 `agent.api_retry` 事件更新计数）
- [ ] 不引入新依赖（用现有 toast 组件 / Radix UI）

**Test Criteria**:
- [ ] 前端组件测试：渲染 mock payload，断言显示字段
- [ ] e2e（手动）：故意配错 env → 前端看到 toast + NodeState.error + retry 实时计数

**Workflow**: Review → Test → Commit (`feat(frontend): P2-T9 surface executor errors via toast + retry counter`)

---

### Task P2-T10: e2e 验证 — 故意配错 env，前端 + CLI 都看到富错误

**Scope**: 无代码改动（验证 task）

**Acceptance Criteria**:
- [ ] 配置错误 `ANTHROPIC_BASE_URL=http://nonexistent.invalid` 在 `.env`
- [ ] 前端启动 `ask_user_demo` workflow → toast 显示 `phase="spawn"` + stderr_tail + retry_attempt
- [ ] CLI 路径 `harness run ask_user_demo` → stderr / TUI panel 显示同样字段
- [ ] schema parity：前端 sink 与 CLI sink 看到的 `ErrorEvent` 字段一致
- [ ] replay 模式：刷新前端，failed run 历史里能看到完整错误信息（agent.executor_error 是 critical，不被淘汰）

**Test Criteria**:
- [ ] 手动跑两路径并截图 / 录屏
- [ ] `tests/test_e2e_error_flow.py`（可选）：TestClient 跑完整路径，断言事件序列

**Workflow**: Review（验证报告） → Test（手动） → Commit (`docs(release): P2-T10 verify e2e error flow parity`)

---

### Phase 2 收尾

- [ ] 写 release note: `docs/releases/2026-06-26-error-event-contract.md`
- [ ] CHANGELOG 顶部加索引
- [ ] CURRENT.md "未解决 #2/#3" 移到 CHANGELOG
- [ ] **Phase gate**: 故意错配 e2e 通过 + 全测试绿 → 进 Phase 3

---

# Phase 3 — CliProfile 抽象 + 用户可注册

**目标**：用户写一个 `./.harness/cli_profiles/opencode.py` 即可加新 executor；env cli 可配置；持久化 + 项目级覆盖。

**Phase 完成定义**：写一个 mock opencode profile → 重启 server → workflow 用 `executor: "opencode"` 跑通端到端；项目级 profile 覆盖 builtin；broken profile 不阻塞 server 启动。

---

### Task P3-T1: 新建 cli_profile.py（CliProfile dataclass + CliExecutorBase 框架）

**Scope**: 新建 `harness/engine/cli_profile.py`

**Acceptance Criteria**:
- [ ] `CliProfile` dataclass，字段见 ADR Decision 3（name / prompt_paradigm / cli_path_env / default_cli_path / flags / prompt_channel / mcp_flag_template / env_overlay_prefixes / translator / result_extractor / spawn_factory）
- [ ] `CliExecutorBase(BaseExecutor)`：
  - `__init__(self, profile, agent_def, deps, *, event_bus, workflow_id, node_id, agent_name, ...)`
  - 实现 `run/record_usage/get_last_request_usage/tool_calls`（按 profile 分派）
  - 通用 `_setup_mcp` / `_teardown_mcp` 按 `profile.mcp_flag_template` 分支
- [ ] `CliRunResult`（迁移自 `ClaudeRunResult`，重命名 + 通用化）
- [ ] 模块级 docstring 说明 Profile 注册契约

**Test Criteria**:
- [ ] `tests/test_cli_profile_dataclass.py`：字段默认值 / 必填项
- [ ] `tests/test_cli_executor_base.py`：mock profile 跑通 base 框架（spawn mock）

**Workflow**: Review → Test → Commit (`feat(executor): P3-T1 add CliProfile dataclass + CliExecutorBase framework`)

---

### Task P3-T2: 通用 run_cli() 替代 run_claude()

**Scope**: 新建 `harness/engine/_cli_subprocess.py`（迁移自 `_claude_subprocess.py`）

**Acceptance Criteria**:
- [ ] `run_cli(cfg: CliSpawnConfig, profile: CliProfile, on_line, timeout) -> CliRunResult`
- [ ] `_build_cmd(cfg, profile)`：按 `profile.flags` + `profile.prompt_channel` 构造命令行
- [ ] `_build_env(env_overlay)`：从 `profile.env_overlay_prefixes` + `os.environ` 合并
- [ ] 通用 stdin / argv 双通道（按 profile.prompt_channel）
- [ ] 删除 `_claude_subprocess.py`（功能完全迁移）

**Test Criteria**:
- [ ] `tests/test_run_cli.py`：mock 各 profile 配置，断言 cmd 构造正确
- [ ] `test_stdin_channel` / `test_argv_channel`
- [ ] `test_env_overlay_merges_prefixes`

**Workflow**: Review → Test → Commit (`refactor(executor): P3-T2 generalize run_claude into run_cli with profile dispatch`)

---

### Task P3-T3: 新建 harness/cli_profiles/ 包 + claude.py profile

**Scope**:
- 新建 `harness/cli_profiles/__init__.py`（registry）
- 新建 `harness/cli_profiles/claude.py`（迁移 DEFAULT_FLAGS）

**Acceptance Criteria**:
- [ ] `__init__.py` 导出：
  - `register_cli_profile(profile)` / `get_profile(name)` / `load_builtin_profiles()` / `load_project_profiles(cwd)`
  - `_REGISTRY: dict[str, CliProfile]`（process-global）
- [ ] `claude.py` 导出 `PROFILE = CliProfile(name="claude-code", prompt_paradigm="minimal", ...)`
  - `flags` = 当前 `DEFAULT_FLAGS` 迁移
  - `translator` = `harness.translator.stream_json.translate`
  - `result_extractor` = 当前 `_extract_and_validate_result` 迁移
  - `cli_path_env = "HARNESS_CLAUDE_CLI"`
  - `default_cli_path = "claude"`
  - `prompt_channel = "stdin"`
  - `mcp_flag_template = "--mcp-config {path}"`
  - `env_overlay_prefixes = ("ANTHROPIC_", "CLAUDE_")`
- [ ] `load_builtin_profiles()` 启动时自动调（在 `harness/cli.py` 入口）

**Test Criteria**:
- [ ] `tests/test_cli_profile_registry.py::test_register_and_get`
- [ ] `test_load_builtin_loads_claude`
- [ ] `test_unknown_profile_raises_key_error`
- [ ] `test_claude_profile_flags_match_legacy_default_flags`（迁移不变量）

**Workflow**: Review → Test → Commit (`feat(profiles): P3-T3 add cli_profiles package + claude builtin profile`)

---

### Task P3-T4: 重构 ClaudeCodeExecutor 为 CliExecutorBase 子类

**Scope**: `harness/engine/claude_code_executor.py`

**Acceptance Criteria**:
- [ ] `ClaudeCodeExecutor(CliExecutorBase)`：
  - `__init__(**kwargs)`: `super().__init__(profile=get_profile("claude-code"), **kwargs)`
  - 删除所有 claude-specific 私有方法（`_build_spawn_config` / `_load_env_overlay` / `_resolve_allowed_tools` 等）→ 移到 CliExecutorBase + profile
- [ ] P2-T3 的 ErrorEvent 逻辑迁到 `CliExecutorBase._run_phase`（通用包装器）
- [ ] `executor_factory.py` 仍能 import 并实例化（向后兼容入口）

**Test Criteria**:
- [ ] 现有 `tests/test_claude_code_executor_*.py` 全绿（duck-type 契约不变）
- [ ] `test_claude_code_executor_is_cli_executor_subclass`
- [ ] `test_claude_code_executor_uses_claude_profile`

**Workflow**: Review → Test → Commit (`refactor(executor): P3-T4 collapse ClaudeCodeExecutor into CliExecutorBase + claude profile`)

---

### Task P3-T5: agent.py VALID_EXECUTORS 改为函数（dynamic）

**Scope**: `harness/core/agent.py`

**Acceptance Criteria**:
- [ ] `BUILTIN_EXECUTORS = frozenset({"pydantic-ai", "claude-code"})`（静态）
- [ ] `def VALID_EXECUTORS() -> frozenset[str]: return BUILTIN_EXECUTORS | _runtime_registry_keys()`
- [ ] `Agent.__init__` 白名单校验：`if executor not in VALID_EXECUTORS()`
- [ ] 所有外部调用 `VALID_EXECUTORS` 改为 `VALID_EXECUTORS()`（加括号）

**Test Criteria**:
- [ ] `tests/test_agent_executor_field.py` 改为调函数
- [ ] `test_valid_executors_includes_registered_profiles`（注册 mock profile 后 VALID_EXECUTORS 含它）
- [ ] grep 验证：`grep "VALID_EXECUTORS[^)]" harness/ server/` 返回空（所有调用都加了括号）

**Workflow**: Review → Test → Commit (`refactor(agent): P3-T5 make VALID_EXECUTORS dynamic with profile registry`)

---

### Task P3-T6: executor_factory.py 改用 profile registry

**Scope**: `harness/engine/executor_factory.py`

**Acceptance Criteria**:
- [ ] `make_executor` 分派逻辑：
  ```python
  if backend == "pydantic-ai":
      return LLMExecutor(...)
  try:
      profile = get_profile(backend)
  except KeyError:
      raise ValueError(...)
  return CliExecutorBase(profile=profile, ...)
  ```
- [ ] 删除现有 `if backend == "claude-code"` 硬编码分支
- [ ] 错误消息指引用户看 `harness/cli_profiles/` README

**Test Criteria**:
- [ ] `tests/test_executor_factory.py::test_unknown_backend_error_mentions_profiles_dir`
- [ ] `test_pydantic_ai_dispatch_unchanged`
- [ ] `test_cli_backend_dispatches_via_registry`

**Workflow**: Review → Test → Commit (`refactor(executor): P3-T6 dispatch via profile registry in executor_factory`)

---

### Task P3-T7: env overlay 改 profile-aware

**Scope**: `harness/engine/cli_profile.py`（CliExecutorBase._load_env_overlay）

**Acceptance Criteria**:
- [ ] `_load_env_overlay(profile)`:
  - 读 `.env`，提取 `profile.env_overlay_prefixes` 列出的 key（如 `ANTHROPIC_*` / `OPENCODE_*`）
  - 读 env `HARNESS_<NAME>_ENV_<KEY>=val` 形式覆盖
  - 读 `HARNESS_<NAME>_CLI` 覆盖 `cli_path`
- [ ] 替换当前 `claude_code_executor.py::_load_env_overlay`（删除）
- [ ] 名字大写规则：`profile.name.upper().replace("-", "_")` → 如 `claude-code` → `CLAUDE_CODE` → `HARNESS_CLAUDE_CODE_CLI`

**Test Criteria**:
- [ ] `tests/test_env_overlay.py::test_prefix_extraction`
- [ ] `test_env_var_override_format`
- [ ] `test_cli_path_override`

**Workflow**: Review → Test → Commit (`feat(executor): P3-T7 profile-aware env overlay + cli path override`)

---

### Task P3-T8: 启动加载 builtin + project profiles

**Scope**:
- `harness/cli.py`（CLI 入口）
- `server/main.py` 或 `server/app.py`（server 入口）

**Acceptance Criteria**:
- [ ] 启动时按顺序调用：
  1. `load_builtin_profiles()`（扫描 `harness/cli_profiles/*.py`）
  2. `load_project_profiles(Path.cwd())`（扫描 `<cwd>/.harness/cli_profiles/*.py`）
- [ ] 加载顺序：项目级覆盖 builtin（同名）
- [ ] env 覆盖：`HARNESS_CLI_PROFILES_DIR=<path>` 替换项目级目录
- [ ] Profile module 必须导出 `PROFILE: CliProfile`（规范）；否则 fail-loud warning + skip

**Test Criteria**:
- [ ] `tests/test_profile_loading_order.py::test_project_overrides_builtin`
- [ ] `test_env_dir_override`
- [ ] `test_missing_profile_variable_warns_and_skips`

**Workflow**: Review → Test → Commit (`feat(executor): P3-T8 load builtin + project profiles at startup`)

---

### Task P3-T9: HARNESS_DISABLE_PROJECT_PROFILES + broken profile 不阻塞

**Scope**: `harness/cli_profiles/__init__.py`

**Acceptance Criteria**:
- [ ] env `HARNESS_DISABLE_PROJECT_PROFILES=1` 跳过项目级加载（CI / 共享目录场景）
- [ ] Profile module 语法错 / import 错 → log warning + 标 disabled + **不阻塞启动**
- [ ] 用户用到 disabled profile 时 fail-loud（`ValueError: profile X failed to load: ...`）
- [ ] 启动日志显示已加载 / disabled profile 列表

**Test Criteria**:
- [ ] `tests/test_profile_disabled.py::test_disable_project_profiles_env`
- [ ] `test_broken_profile_does_not_block_startup`
- [ ] `test_using_disabled_profile_raises`

**Workflow**: Review → Test → Commit (`feat(executor): P3-T9 graceful degradation for broken/disabled profiles`)

---

### Task P3-T10: 文档（README + CLAUDE.md）

**Scope**:
- `README.md`：加 "Custom CLI Profile" 章节
- `CLAUDE.md`：加 "Executor & Profile Contract" 段落
- `docs/refactor/executor-extensibility/ADR.md`：标注 Status: Accepted（实现完成后）

**Acceptance Criteria**:
- [ ] README 章节包含：
  - 写 `./.harness/cli_profiles/<name>.py` 的完整示例（含 PROFILE 导出）
  - env 配置（`HARNESS_<NAME>_CLI` / `HARNESS_<NAME>_ENV_*`）
  - 范式归属（`prompt_paradigm: "minimal"`）
- [ ] CLAUDE.md 段落简短：指向 ADR + 列关键不变量
- [ ] ADR 状态从 Proposed → Accepted

**Test Criteria**:
- [ ] 文档 lint（如有）通过
- [ ] 手动 follow README 章节能跑通一个新 profile

**Workflow**: Review → Test → Commit (`docs(executor): P3-T10 document custom CLI profile authoring`)

---

### Task P3-T11: e2e 验证 — mock opencode profile 端到端跑通

**Scope**: 无代码改动（验证 task）

**Acceptance Criteria**:
- [ ] 写 `./.harness/cli_profiles/opencode.py`（mock profile，复用 claude translator 但换 cli_path）
- [ ] workflow JSON 用 `executor: "opencode"` → 启动 server 能识别
- [ ] 跑 workflow → CliExecutorBase 用 opencode profile 分派 → 跑通端到端
- [ ] 重启 server → 自动加载项目级 opencode profile（无需重声明）
- [ ] `HARNESS_OPENCODE_CLI=/custom/path` 覆盖 cli path 生效

**Test Criteria**:
- [ ] 手动 e2e + 截图 / 录屏
- [ ] `tests/test_e2e_custom_profile.py`（可选）：自动跑 mock profile 端到端

**Workflow**: Review（验证报告） → Test（手动） → Commit (`docs(release): P3-T11 verify custom profile e2e`)

---

### Phase 3 收尾

- [ ] 写 release note: `docs/releases/2026-06-26-cli-profile-abstraction.md`
- [ ] CHANGELOG 顶部加索引
- [ ] CURRENT.md 全部未解决项清空，准备开新任务
- [ ] ADR 状态：Accepted

---

# 跨 Phase 约束

- **禁止并行 Phase**：P2 依赖 P1 的范式字段，P3 依赖 P2 的 ExecutorError
- **测试基线**：每个 task 完成时 `make test` + 前端 `npm test` + `make lint-runs` 全绿
- **回滚预案**：每 task 独立 commit；每 Phase 独立 PR；单 task / 单 Phase 回滚不影响其他
- **文档同步**：task 涉及接口变化时，本 task 内同步更新 SPEC.md / README.md / CLAUDE.md 相关段落
- **状态机**：每 task 完成立即更新 CURRENT.md（"in-progress: P{n}-T{m}" → "done: P{n}-T{m}"），不积累
