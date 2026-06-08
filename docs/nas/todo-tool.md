# TODO 工具 — Agent 自驱式步骤追踪

> 状态：已实现
> 对比参考：Claude Code TaskCreate/TaskUpdate/TaskList

## 设计目标

让 agent 在执行过程中自己规划步骤、更新进度，前端实时渲染。框架不解析 MD、不预设步骤格式——agent 读 MD 后自己决定要做什么。

## 工具接口

```python
todo(
    op: Literal["create", "update", "list"],

    # create
    items: list[TodoItem] | None = None,

    # update
    task_id: str | None = None,
    status: Literal["in_progress", "completed"] | None = None,
    detail: str | None = None,
) -> str
```

### 操作行为

| op | 输入 | 行为 |
|----|------|------|
| `create` | `items` | 创建步骤列表，第 1 步自动标为 `in_progress`，可多次调用追加 |
| `update` | `task_id, status?, detail?` | 更新步骤。`completed` 时自动推进下一个 `pending` 为 `in_progress` |
| `list` | — | 返回当前步骤列表及状态 |

### TodoItem

```python
class TodoItem(BaseModel):
    content: str       # "分析项目结构"
    activeForm: str    # "正在分析项目结构..."
```

## 架构

### 核心设计决策：TodoState 通过 AgentDeps 隔离

```
defaults.py    → 注册无状态 TodoToolFactory（全局一次性）
macro_graph.py → 创建 TodoReminderTracker(deps) 传给 executor
todo.py        → ensure_todo_state(deps) 懒创建，通过 AgentDeps 隔离
todo_reminder.py → 独立计数器 + 从 deps 读 TodoState
llm_executor.py → 可选 reminder_tracker，None-safe
```

**为什么不用 ToolRegistry 传递 state：**
ToolRegistry 是全局单例。如果在上面覆盖注册，多 agent 时最后一个覆盖前面所有的，导致状态污染。改用 AgentDeps（`extra="allow"`）后每个 agent 有独立 state。

### State 生命周期

```
_make_node_func() 编译阶段：
  └── 创建闭包 node_func，闭包捕获 _reminder_tracker_holder = [None]

node_func() 运行时（每次调用）：
  ├── deps = AgentDeps(...)           ← 全新实例
  ├── tracker = TodoReminderTracker(deps)
  ├── _reminder_tracker_holder[0] = tracker
  ├── executor = LLMExecutor(..., reminder_tracker=tracker)
  └── executor.run(context)
       ├── tool call: tracker.on_tool_call(name)   ← 追踪计数
       ├── tool result: tracker.get_reminder()      ← 生成提醒
       └── todo tool: ensure_todo_state(deps)       ← 懒创建 state
```

每个 agent 调用每次 node_func 都创建全新 deps + tracker，无跨调用共享。

## `<system-reminder>` 兜底机制

### 两层提醒

| 场景 | 阈值 | 提醒内容 |
|------|------|---------|
| Agent 没创建计划 | 3 轮非 todo 调用 | "请先调用 todo(op='create')" |
| Agent 有计划但不更新 | 5 轮非 todo 调用 | "当前步骤「X」是否完成？请更新" |

### 为什么计数器独立于 TodoState

CREATE reminder 的意义是 **在 agent 还没调 todo 时**提醒它先规划。如果把计数器放在 TodoState 里，state 不存在时计数器也不工作，CREATE reminder 永远触发不了。所以计数器必须在 Tracker 内部独立维护。

### 注入方式

Reminder 追加到 tool result 的 `event.part.content` 末尾。LLM 在下一轮看到这个 reminder。前端不收 reminder（不 re-emit `agent.tool_result`）。

## 事件协议

两个事件，前端无关：

### `todo.created`

```json
{
  "type": "todo.created",
  "payload": {
    "node_id": "nas_orchestrator",
    "agent_name": "nas_orchestrator",
    "items": [
      {"task_id": "t_1", "content": "分析项目", "activeForm": "正在分析...", "status": "in_progress"},
      {"task_id": "t_2", "content": "制定策略", "activeForm": "正在制定...", "status": "pending"}
    ]
  }
}
```

### `todo.updated`

```json
{
  "type": "todo.updated",
  "payload": {
    "node_id": "nas_orchestrator",
    "task_id": "t_1",
    "status": "completed",
    "detail": null,
    "auto_advance": {"next_task_id": "t_2", "status": "in_progress"}
  }
}
```

`auto_advance` 仅在 completed 触发自动推进时出现。

## 并发安全性分析

| 场景 | 隔离机制 |
|------|---------|
| 串行 agents | 每个 node_func 创建独立 deps |
| 并行 fan-out | 每个闭包有独立 holder，无共享可变状态 |
| 多 workflow | 独立 MacroGraphBuilder + ToolRegistry + 闭包 |
| Loop 回到自身 | 每次调用创建全新 deps + tracker |
| Workflow 重运行 | 同理 |
| todo 不在工具列表 | `todo_available=False`，不创建 tracker |
| Agent 忘了调 todo | `_non_todo_calls` 独立计数，3 轮后 CREATE reminder 触发 |

## 文件清单

| 文件 | 角色 |
|------|------|
| `harness/tools/todo.py` | TodoState + TodoToolFactory + ensure/get helpers |
| `harness/tools/todo_reminder.py` | TodoReminderTracker（独立计数器 + reminder 生成） |
| `harness/tools/defaults.py` | 注册 todo 工具 |
| `harness/engine/llm_executor.py` | reminder_tracker 注入 tool result |
| `harness/engine/macro_graph.py` | 创建 tracker + 传给 executor |
| `frontend/src/types/events.ts` | todo.created / todo.updated 事件类型 |
| `frontend/src/contexts/workflow-context/workflowStores.ts` | todoStore + handlers |
| `frontend/src/contexts/workflow-context/routeEvent.ts` | 事件路由 |
| `frontend/src/contexts/workflow-context/types.ts` | WorkflowStores.todo + EVENT_TO_STORES |
| `frontend/src/components/todo/TodoStepList.tsx` | 步骤列表组件 |
| `frontend/src/components/conversation/ScopedConversationTab.tsx` | 嵌入 TodoStepList |
| `frontend/src/app/globals.css` | todo-pulse 动画 |
