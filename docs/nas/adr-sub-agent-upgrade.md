# ADR: sub_agent 升级 — 并行执行 + 代码隔离

> 日期: 2026-06-10
> 状态: Proposed
> Spike 验证: ✅ pydantic-ai v1.98.0 默认并行执行多个 tool call（实测 3 × sleep(2) = 2s）

## 背景

当前 `SubAgentToolFactory`（`harness/tools/sub_agent.py`）实现同步阻塞子 agent。NAS 场景需要 orchestrator 同时启动多个优化策略并行执行。

## 关键发现：框架已支持并行

**Spike 实测**：当 LLM 在一次响应中返回 3 个 `slow_tool` 调用时，pydantic-ai 默认并行执行：

```
A: start +2.22s, end +4.22s, duration 2.00s
B: start +2.22s, end +4.22s, duration 2.00s
C: start +2.22s, end +4.22s, duration 2.00s
Start spread: 0.000s → PARALLEL ✅
```

这意味着：**不需要 `mode="async"`、不需要 `SubAgentTaskManager`、不需要 `task_id/action`**。子 agent 的并行由框架自动处理——LLM 只需在一次响应中发起多个 `sub_agent` 调用。

## 决策：极简升级，只加隔离

### 接口

```python
sub_agent(
    task: str,                                    # 任务描述（必填）
    isolation: "none" | "worktree" = "none",      # 代码隔离
) -> str
```

与当前接口完全兼容（只新增一个有默认值的参数）。

### 并行用法

NAS orchestrator 在一次 tool-calling turn 中返回：

```json
[
  {"tool": "sub_agent", "args": {"task": "剪枝 + 蒸馏", "isolation": "worktree"}},
  {"tool": "sub_agent", "args": {"task": "知识蒸馏", "isolation": "worktree"}},
  {"tool": "sub_agent", "args": {"task": "低秩分解", "isolation": "worktree"}}
]
```

pydantic-ai 并行执行三个子 agent，全部完成后返回结果给 orchestrator，orchestrator 汇总后决定是否迭代。

### 改动范围

| 改动 | 文件 | 复杂度 |
|------|------|--------|
| `sub_agent()` 新增 `isolation` 参数 | `harness/tools/sub_agent.py` | 小 |
| worktree 创建/清理 helper | `harness/tools/sub_agent.py`（同文件） | 小 |
| 子 agent 事件带 `sub_agent: true` 标记 | `harness/engine/llm_executor.py` | 小 |
| 前端按 sub_agent 标记分组渲染 | `ConversationMessage` + `ScopedConversationTab.tsx` | 中 |

**总计：~1.5 天**

### 不需要的东西

| 原设计 | 为什么不需要 |
|--------|-------------|
| `mode="async"` | pydantic-ai 默认并行 |
| `SubAgentTaskManager` | 框架管理 tool call 生命周期 |
| `task_id` / `action` 参数 | 框架自动收集所有 tool 结果 |
| `sub_agent.spawned/completed/failed` 事件 | 现有 `tool_call`/`tool_result` 事件已覆盖 |
| `max_turns` 参数 | 复用现有 `request_limit` |
| `model` 参数 | 始终继承父 agent 模型 |
| Resume 能力 | NAS orchestrator 不需要 |
| 前端 taskStore | 复用 conversationStore |

## 内部实现

### Worktree 隔离

当 `isolation="worktree"` 时，在 `sub_agent` 函数体内部：

```python
async def sub_agent(ctx: RunContext, task: str, isolation: str = "none") -> str:
    workdir = ctx.deps.workdir

    if isolation == "worktree":
        workdir = _create_worktree(workdir)  # git worktree add

    try:
        child_deps = AgentDeps(workdir=workdir, ...)
        result = await child.run(task, deps=child_deps)
        return result.output
    finally:
        if isolation == "worktree":
            _cleanup_worktree(workdir)  # git worktree remove
```

worktree 创建失败时降级为无隔离（warn + 继续执行）。

### 事件标记

子 agent 的 tool_call/tool_result 事件通过现有 `_emit_tool_call` 发射，payload 中新增 `is_sub_agent: true` 标记。前端可据此分组渲染。

### Token 统计

复用现有 `TokenAggregator`，与当前同步模式一致。

## Claude Code 对齐度

| Claude Code 特性 | Harness 对应 | 状态 |
|-----------------|-------------|------|
| Foreground Agent | `sub_agent(task="...")` — 同步阻塞 | ✅ 已有 |
| 并行多 Agent | pydantic-ai 默认并行执行 | ✅ 框架支持 |
| `isolation: "worktree"` | `isolation="worktree"` 参数 | 🆘 待实现 |
| `model: "inherit"` | 不暴露参数，始终继承 | ✅ 已有 |
| `tools` 限制 | `_EXCLUDE_FROM_CHILD` | ✅ 已有 |
| 上下文隔离 | 子 agent 不收到父对话历史 | ✅ 已有 |
| `background: true` | 不需要 — 框架并行已满足 | ⬜ 不实现 |
| `maxTurns` | 复用 `request_limit` | ✅ 已有 |
| Resume | 不需要 — NAS 场景不适用 | ⬜ 不实现 |

## 参考

- [Claude Code Tools Reference](https://code.claude.com/docs/en/tools-reference)
- [Claude Code Subagents SDK](https://code.claude.com/docs/en/agent-sdk/subagents)
- [NAS Workflow Architecture](./nas-workflow-architecture.md)
- [NAS Task Tool 设计](./task-tool.md) — 被本方案替代
