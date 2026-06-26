# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **框架使用说明（安装、API、工具列表、目录结构、扩展用法等）请见 [README.md](README.md)。**
> 本文件只包含**规则性引导** —— 必须遵守的协作准则与契约。

---

## 12-Rule 协作原则

1. **Think Before Coding** — 明确假设，不确定则问
2. **Simplicity First** — 最少代码解决
3. **Surgical Changes** — 只改必须的
4. **Goal-Driven Execution** — 定义成功标准
5. **Use the model only for judgment calls** — deterministic 逻辑用代码
6. **Token budgets are not advisory** — 接近 budget 及时总结
7. **Surface conflicts, don't average them** — 选一个，说明 why
8. **Read before you write**
9. **Tests verify intent, not just behavior**
10. **Checkpoint after every significant step**
11. **Match the codebase's conventions**
12. **Fail loud**

---

## SDD 开发流程

```
接口讨论（确认）→ ADR（如需）→ 计划 → 执行 → 更新状态
```

**禁止**：未确认接口就实现、未写计划就写代码。

---

## CHANGELOG 与状态文档规则

- `docs/status/CURRENT.md` —— 当前任务快照（≤50 行：任务、状态、必读文件、待办）
- `docs/status/CHANGELOG.md` —— 索引，每条 1-2 句话 + 链接到 release note
- `docs/releases/<date>-<name>.md` —— 详细 release note（实际做了什么、偏离 plan 处、commit SHAs、验证结果）
- `docs/plans/<date>-<name>.md` —— 事前实施计划

**任务完成时的强制流程**：写 release note → CHANGELOG 顶部加索引 → 清空 CURRENT.md。**不积累，不延后。**

**断点续传**：新终端必读 `CLAUDE.md` + `docs/status/CURRENT.md` + CURRENT.md 中"必读文件"。未读 CURRENT.md 不要开工。

---

## 问题分类（必须遵守）

遇到反馈先判定 **bug** 还是 **架构问题**：

- **Bug**：局部错误、状态丢失、边界未处理 → 最小化 surgical fix
- **架构问题**：跨模块耦合、抽象错位、职责越界、数据/事件流断裂、需要 hack 才能跑通 → 先写设计方案对齐再改，**不允许直接打补丁**

判定信号：现象在多模块复现 / 修复涉及 ≥3 个不相关文件 / 需要 hack 兼容代码 → 架构问题。

---

## 代码质量底线

1. **整洁**：命名达意，函数单一，只在 *why* 非显然时注释
2. **可扩展**：新能力靠新增策略/插件，不改核心路径（OCP）
3. **鲁棒**：边界、空值、失败路径显式处理，**fail loud**，不静默吞错
4. **性能**：无 N+1、无全量重渲、无重复请求；大数据流式或分页
5. **易定位**：关键路径有结构化日志/事件

**报错处理**：重试必须用户可见（"重试中 / 第 N 次 / 失败原因"），不允许静默；transport / 协议 / 业务三层重试不能互相吞错；限流走退避重试而非直接中断。

---

## 事件 Priority 契约

Bus 的 replay buffer 满了会 FIFO 淘汰 normal 事件，**critical 事件永不淘汰**。

判定：「下游错过这个事件，UI 会永久错误吗？」→ critical；「能被后续事件或刷新重建吗？」→ normal。

添加新事件类型：判定后**必须**同步更新 `harness/extensions/bus.py` 的 `CRITICAL_EVENT_TYPES` 白名单。

---

## 执行器与 CLI Profile 契约

详见 [`docs/refactor/executor-extensibility/ADR.md`](docs/refactor/executor-extensibility/ADR.md)。关键不变量：

- **Prompt 范式二选一**：每个 executor 属于 `pydantic-ai` 或 `minimal` 范式之一（不能混）。`harness/prompts/assembler.py:executor_to_paradigm` 是范式分派入口；`register_executor_paradigm` 是 override hook。
- **ErrorEvent emit-uniqueness**：每个 executor 错误**只在一个位置 emit**。Executor 内部封装 → emit `agent.executor_error` (critical) → raise `ExecutorError`。`node_factory` / `execute_with_retry` 接住 `ExecutorError` 不重 emit。翻译器不再为 `result.is_error` emit `node.failed`（让 executor 统一）。
- **CliProfile 注册幂等**：同名 profile 后注册覆盖前注册；项目级（`<cwd>/.harness/cli_profiles/`）覆盖 builtin。损坏 profile 自动 disable 但不阻塞启动；用户用到时抛 `ValueError` 含具体原因。
- **VALID_EXECUTORS 是函数**：`harness/core/agent.VALID_EXECUTORS()` 动态合并 `BUILTIN_EXECUTORS` + profile registry。新增 backend = 写一个 profile 文件，**不需要改白名单**。
- **CLI/server payload parity**：`workflow.error` 通过 `harness.engine.error_event.build_workflow_error_payload` 统一构造，CLI 和 server emit 相同 schema。

添加新 CLI backend：写 `harness/cli_profiles/<name>.py`（builtin）或 `./.harness/cli_profiles/<name>.py`（项目级），导出 `PROFILE: CliProfile`。详见 [README — 执行器与 CLI Profile](README.md#执行器与-cli-profile)。

---

## 扩展系统职责分界

| 类型 | 能做 | 不能做 |
|------|------|--------|
| **Hook** | 读数据流，产生副产物（chart/trace） | 修改任何数据 |
| **Middleware** | 修改数据流，抛 RejectAction/RetryAction | 改写 DAG |
| **GraphMutator** | 改写 DAG | 修改运行时数据 |

违反职责分界 = 架构问题，不允许打补丁绕过。

---

## Runs/ 持久化契约（single-source 重构）

详见 [`docs/refactor/single-source-index-driven/ADR.md`](docs/refactor/single-source-index-driven/ADR.md)。

**写盘契约**：
- 所有 iter sidecar 写盘**必须**走 `harness.persistence.sidecar_io.save_iter_sidecar_safe`（R3：atomic + verify + retry + log loud + 不 raise）。**禁止**直接调 `RunStore.save_iter_sidecar` 写 iter sidecar（已 deprecated，P5 移除）。
- 所有写盘**必须** atomic（tmpfile + `os.replace`）—— 复用 `sidecar_io.atomic_write_json` 或 `RunStore._atomic_write`。

**校验契约**：
- 改 schema 字段前先改 `schemas/*.v2.schema.json` —— `additionalProperties: false`，未声明字段直接被拒。
- `make lint-runs` 是 CI 门槛 —— 默认模式 warn-only（pre-P2b/P4 baseline），`--strict` 全 error（post-P4 启用）。
- 新增不变量：在 `scripts/lint_runs.py` 加 `check_iN_*` 函数 + 在 ADR `不变量` 节同步描述。
