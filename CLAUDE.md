# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **框架使用说明（安装、API、工具列表、目录结构、扩展用法等）请见 [README.md](README.md)。**
> 本文件只包含**规则性引导** —— 开发规范、协作准则、必须遵守的契约。

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

## 问题分类与质量标准（必须遵守）

当遇到用户反馈或缺陷报告时，**先判定是 bug 还是架构问题**，再决定动手方式：

- **Bug**：局部逻辑错误、状态丢失、渲染错位、边界条件未处理。修复方式 = 最小化 surgical fix，不动结构。
- **架构问题**：跨模块的耦合、抽象层次错位、违反单一职责、缺少扩展点、数据流或事件流不合理、违反 SOLID 原则。修复方式 = 先提出设计方案（说明动机、权衡、迁移路径），与用户对齐后再改，不允许直接打补丁绕过。

### 判定信号（出现任一即倾向"架构问题"）
- 同一现象在多个模块复现
- 修复需要改动 ≥3 个不相关文件
- 现象背后是"职责越界"（例如工具直接污染对话结构、UI 状态散落在多处）
- 现象背后是"事件/数据流断裂"（例如持久化层与内存状态不同步）
- 用 hack/兼容代码才能让现有抽象跑通

### 代码质量底线（任何改动必须满足）
1. **整洁**：命名表达意图，函数职责单一，无注释解释 *what*，只在 *why* 非显然时注释。
2. **可扩展**：新能力通过新增（策略/插件/注册项）而非修改核心路径实现（OCP）。
3. **鲁棒**：边界条件、空值、失败路径显式处理；失败 **fail loud**，不静默吞错。
4. **性能**：默认无 N+1、无全量重渲、无重复请求；大数据流式或分页。
5. **易定位**：关键路径有结构化日志/事件；错误能追溯到一个明确的层（工具 / 引擎 / 事件 / UI）。

### 报错处理与可观测性
- 重试**必须显式**告知用户（UI 上能看到"重试中 / 第 N 次 / 失败原因"），不允许静默重试或静默失败。
- LLM / 网络 / 工具失败要分层捕获：transport 层重试（网络抖动）→ 协议层重试（4xx 中可重试项）→ 业务层中断（不可恢复）。层与层之间不能互相吞错。
- 限流（rate limit / request_limit）应走"退避重试 + 用户可见"，而不是直接中断 agent。

> 违反上述任何一条时，优先写设计方案而不是打补丁。

---

## 事件 Priority 契约（添加新事件类型时必须遵守）

Bus 的 WS replay buffer 有大小上限（默认 `buffer_size=2000`），normal 事件按 FIFO 淘汰；**critical 事件永不淘汰**（独立的 `_critical_buffer`）。

**判定规则**：「如果下游消费者错过了这个事件，UI 会永久错误吗？」→ critical；「能被后续事件或刷新重建吗？」→ normal。

白名单定义在 `harness/extensions/bus.py` 的 `CRITICAL_EVENT_TYPES`（frozenset）。

**添加新事件类型时的强制流程**：
1. 判定语义属于 critical 还是 normal
2. 如果是 critical，**必须**同时加入 `CRITICAL_EVENT_TYPES`
3. `bus.emit(...)` 和 `safe_emit(...)` 的 `priority` 参数默认 `None`（按 event_type 自动查表），显式传 `priority="critical"` 或 `"normal"` 会覆盖白名单（保留逃生通道）

历史教训：曾因 `node.completed` 走 normal priority，5641 个事件被 FIFO 淘汰了 3641 个 → 前端实时 token 显示只有单节点值（334.8k）而非真实总和（1.71M）。

---

## 扩展系统职责分界（开发约束）

| 类型 | 能做什么 | 不能做什么 |
|------|---------|-----------|
| **Hook** | 读取数据流，产生副产物（chart.render, trace.step） | 修改任何数据 |
| **Middleware** | 修改数据流，可抛 RejectAction/RetryAction | 改写 DAG 结构 |
| **GraphMutator** | 改写 DAG（插入节点、修改依赖） | 修改运行时数据 |

违反职责分界 = 架构问题（见上文「问题分类」），不允许打补丁绕过。
