# Conversation 隔离修复报告

## 修复日期
2026-05-25

## 问题描述

在 batch 模式下运行 benchmark 时，多个 workflow 并行执行，但它们的 conversation（对话记录）没有正确隔离：

1. 非选中 run 的 `agent.text_delta` 事件被完全忽略
2. 非选中 run 的 `tool_call` / `tool_result` 事件被完全忽略
3. 当切换到非选中 run 时，conversation 是空的

## 根本原因

`dispatchBatchEvent` 只处理了选中的 run，对非选中 run：
- 更新了 workflowStore 的节点状态（通过 cache）
- **但是忽略了所有 conversation 相关事件**

这导致：
```typescript
// 之前的代码
if (_isSelectedRun(wid)) {
  _routeToUIStores(event);  // 只有选中 run 的 conversation 更新
}
// 非选中 run 的 conversation 完全丢失
```

## 修复方案

### 1. conversationStore 添加 Cache 操作方法

新增三个方法用于直接操作 cache：

```typescript
appendAgentTextToCache: (wid, nodeId, text) => void
addToolCallToCache: (wid, nodeId, agentName, toolName, toolArgs) => void
addToolResultToCache: (wid, nodeId, toolName, result) => void
```

### 2. dispatchBatchEvent 处理非选中 run 的 conversation 事件

```typescript
else if (wid && _isBatchMode()) {
  // 节点事件缓存到 workflowStore
  if (event.type === "node.started") { ... }
  else if (event.type === "node.completed") { ... }

  // Conversation 事件直接缓存
  else if (event.type === "agent.text_delta") {
    useConversationStore.getState().appendAgentTextToCache(wid, p.node_id, p.text);
  } else if (event.type === "agent.tool_call") {
    useConversationStore.getState().addToolCallToCache(wid, ...);
  } else if (event.type === "agent.tool_result") {
    useConversationStore.getState().addToolResultToCache(wid, ...);
  }
}
```

## 修改的文件

1. `frontend/src/stores/conversationStore.ts`
   - 添加 `appendAgentTextToCache`
   - 添加 `addToolCallToCache`
   - 添加 `addToolResultToCache`

2. `frontend/src/hooks/useWorkflowEvents.ts`
   - 更新 `dispatchBatchEvent` 处理非选中 run 的 conversation 事件

## 验证测试

### TC1: Batch Conversation 隔离
1. 启动 benchmark（4 个并行 task）
2. 初始选中的是 task 1
3. 等待 task 1 和 task 2 都有输出
4. 切换到 task 2
5. **验证**: task 2 的 conversation 显示了它的完整输出（不是空的）
6. 切换回 task 1
7. **验证**: task 1 的 conversation 仍然显示

### TC2: Tool Call 隔离
1. 运行包含工具调用的 benchmark
2. 验证切换 run 时 tool call 记录正确显示

## 结论

现在每个 run 的 conversation 完全独立：
- 选中的 run：直接更新 UI stores
- 非选中的 run：事件保存到各自的 cache
- 切换时：从 cache 正确恢复完整的 conversation 状态