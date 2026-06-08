# 重构建议 — 相关大型文件

> 这些文件在 NAS 系列工具开发过程中被修改。随着工具数量增加，需要拆分以保持可维护性。

---

## 1. `frontend/src/contexts/workflow-context/workflowStores.ts` (1510 行)

### 问题
- 所有 store 定义、接口、创建函数都堆在一个文件里
- 每加一个工具（todo → task → parallel_tasks）都要往里塞
- 代码导航困难，改一个 store 要在 1500 行里找

### 建议

拆分为独立 store 文件 + 聚合索引：

```
frontend/src/stores/
├── todoStore.ts          ← 从 workflowStores.ts 提取
├── taskStore.ts          ← 新增
├── conversationStore.ts  ← 已存在，移入
├── workflowStore.ts      ← 已存在，移入
├── chartStore.ts         ← 已存在，移入
└── ...

frontend/src/contexts/workflow-context/
├── workflowStores.ts     ← 只做聚合：import + createWorkflowStores()
```

`workflowStores.ts` 变成纯聚合文件（~50 行），每个 store 独立开发和测试。

### 迁移步骤
1. 将 `TodoState`、`TodoStep`、`createTodoStore`、`handleTodoCreated`、`handleTodoUpdated` 移到 `stores/todoStore.ts`
2. `workflowStores.ts` 改为 import + 转导出
3. 后续 task store 直接在 `stores/taskStore.ts` 新建

---

## 2. `frontend/src/contexts/workflow-context/routeEvent.ts` (464 行)

### 问题
- 所有事件路由逻辑在一个 switch 里
- 每加一个事件类型就要改这个文件
- 路由逻辑和 handler 逻辑混在一起

### 建议

改为事件 handler 注册制：

```typescript
// 每个 store 导出自己的路由
// stores/todoStore.ts
export function registerTodoRoutes(router: EventRouter) {
  router.on("todo.created", (stores, event) => { ... });
  router.on("todo.updated", (stores, event) => { ... });
}

// routeEvent.ts
const handlers: EventHandlers[] = [
  workflowRoutes,
  conversationRoutes,
  todoRoutes,
  // ... 每个 store 注册自己的
];
```

### 迁移步骤
1. 先为 todo 创建独立的 route 处理函数
2. 在 routeEvent.ts 中调用（不动其他路由）
3. 后续逐步迁移其他事件

---

## 3. `frontend/src/contexts/workflow-context/types.ts` (129 行)

### 问题
- `WorkflowStores` 接口在两个地方定义（types.ts + workflowStores.ts）
- `EVENT_TO_STORES` 映射需要手动维护
- 加新 store 要改两处，容易遗漏

### 建议
统一到一个源文件，另一个用 `export type { ... }` 转导。

---

## 4. `harness/engine/macro_graph.py` (1119 行)

### 问题
- `_make_node_func` 巨大（~600 行），包含所有节点逻辑
- 每加一个需要注入到 tool-calling 循环的功能都要改这里
- `_reminder_tracker_holder` 模式是 closure 限制的 workaround

### 建议

引入 NodePlugin 接口：

```python
class NodePlugin:
    """Per-node lifecycle hook that runs inside the tool-calling loop."""

    def on_tool_call(self, tool_name: str) -> None: ...
    def on_tool_result(self, tool_name: str, content: str) -> str | None: ...

# macro_graph.py
plugins: list[NodePlugin] = []
if todo_available:
    plugins.append(TodoReminderPlugin(deps))

executor = LLMExecutor(..., plugins=plugins)
```

这样 macro_graph 不需要知道每个 plugin 的细节，只负责创建和传递。新功能（task tracking、progress reporting）只需加新 plugin。

---

## 5. `harness/engine/llm_executor.py` (385 行)

### 问题
- `reminder_tracker` 是 todo 专属概念，直接硬编码在 executor 里
- 后续 task tracker、progress tracker 也会需要类似的注入点
- `_handle_call_tools` 职责膨胀

### 建议

改为通用 plugin 回调：

```python
class ToolCallPlugin:
    def on_tool_call(self, tool_name: str) -> None: ...
    def on_tool_result(self, part) -> None: ...

class LLMExecutor:
    def __init__(self, ..., plugins: list[ToolCallPlugin] | None = None):
        self._plugins = plugins or []

    async def _handle_call_tools(self, node, ctx):
        # ... 在 tool call/result 时遍历 plugins
        for p in self._plugins:
            p.on_tool_call(event.part.tool_name)
```

macro_graph 传入 plugins 列表，executor 不知道也不关心具体 plugin 类型。
