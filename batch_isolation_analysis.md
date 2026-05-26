# Batch Workflow 隔离分析报告

## 执行日期
2026-05-25

## 分析结论

**从后端到前端的流程是隔离的**。每个并行运行的 workflow 有独立的状态存储和历史记录。

---

## 后端隔离机制

### 1. Workflow ID 隔离 ✅

```python
# server/routes.py - _create_and_start_workflow()
workflow_id = str(uuid.uuid4())  # 每个 run 有唯一 ID
```

每个 workflow run 获得唯一的 UUID 作为标识符。

### 2. Event Bus 隔离 ✅

```python
# server/routes.py - _create_and_start_workflow()
# Each workflow gets its own Bus — fully isolated events + extensions
event_bus = _new_bus()  # 每个独立的 Bus 实例
```

每个 workflow 创建独立的 EventBus，事件不会交叉污染。

### 3. Thread ID 隔离 ✅

```python
# server/routes.py - _create_and_start_workflow()
repo.put(workflow_id, {
    "thread_id": workflow_id,  # 等于 workflow_id
    ...
})
```

LangGraph 使用独立的 thread_id，checkpointer 按此隔离状态。

### 4. 历史记录隔离 ✅

```python
# server/runner.py - _run_workflow()
RunStore().save(
    run_id=workflow_id,  # 每个文件以 workflow_id 命名
    workflow_name=workflow.name,
    ...
)
```

文件结构：`runs/{workflow_id}.json`，完全独立。

---

## 前端隔离机制

### 1. Batch WS 事件路由 ✅

```typescript
// frontend/src/hooks/useWorkflowEvents.ts - dispatchBatchEvent()
if (_isSelectedRun(wid)) {
    _routeToUIStores(event);  // 只更新选中 run 的 UI
} else if (wid && _isBatchMode()) {
    // 更新非选中 run 的 cache
    if (event.type === "node.started") {
        useWorkflowStore.getState().updateNodeInCache(wid, p);
    } ...
}
```

### 2. Cache 隔离 ✅

```typescript
// frontend/src/stores/workflowStore.ts
_cache: Record<string, { nodes, status, workflowId, ... }>  // 按 wid 分隔
```

每个 store (conversation, output, workflow) 都有独立的 cache。

### 3. 切换机制 ✅

```typescript
// frontend/src/hooks/useWorkflowEvents.ts - switchBatchRun()
useConversationStore.getState().saveToCache(selectedRunId);  // 保存当前
useConversationStore.getState().restoreFromCache(wid);  // 恢复目标
```

---

## 已修复的问题

### P006: Batch 模式下非选中 run 的节点状态未保存

**问题描述**: 在 batch 模式下，只有选中的 run 节点状态被更新，非选中 run 切换回来时看不到执行进度。

**修复方案**:
1. 在 `dispatchBatchEvent` 中添加非选中 run 的 cache 更新逻辑
2. 在 `_routeToUIStores` 的 `node.started/failed` 事件中添加 cache 更新

**文件**: `frontend/src/hooks/useWorkflowEvents.ts`

---

## 验证测试建议

### 测试用例 1: 并行 Run 状态隔离
1. 启动 code-review-v1 benchmark（4 个 task）
2. 观察 BenchmarkRunner 的进度表
3. 切换查看不同 task
4. 验证每个 task 的 DAG 状态独立显示

### 测试用例 2: 历史记录独立性
1. 运行 benchmark
2. 完成后查看侧边栏
3. 应该看到 4 个独立的 run 记录
4. 每个 run 有不同的 run_id 和 inputs.task

### 测试用例 3: 切换状态恢复
1. 在 benchmark 运行期间，从一个 task 切换到另一个
2. 再切换回来
3. 验证 DAG 状态从 cache 正确恢复

### 测试用例 4: Benchmark 结果隔离
1. 查看 benchmarks/code-review-v1/results/
2. 每个结果文件对应一个 benchmark run
3. result.json 中的 task_results 应该正确关联到各个 workflow

---

## 文件变更

```
frontend/src/hooks/useWorkflowEvents.ts  - 添加 batch cache 更新逻辑
```

---

## 结论

1. **后端隔离完全正确** - 每个 workflow 使用独立的 workflow_id、event_bus 和 thread_id
2. **历史记录完全独立** - 每个运行保存到独立的 JSON 文件
3. **前端隔离已修复** - 非 batch 模式下正确，batch 模式下 cache 更新已补充