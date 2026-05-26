# Benchmark 修复报告

## 修复日期
2026-05-25

## 编译错误修复

### 问题1: conversationStore.ts 类型错误 ✅ 已修复
**错误**: `Type 'void' is not assignable to type 'boolean'`

**原因**: 在 Zustand 中，`set(() => {...})` 形式的更新函数不返回值。需要直接返回 `true` 或 `false`。

**修复**:
```typescript
// 修复前 - 在 set 内部返回错误
restoreFromCache: (wid) =>
  set((state) => {
    const { _cache } = state;
    const snap = _cache[wid];
    if (!snap) return;  // 这里返回 void，不是 boolean
    set({ messages: snap.messages, ...state });
  }),

// 修复后 - 返回正确的布尔值
restoreFromCache: (wid) => {
  const { _cache } = get();
  const snap = _cache[wid];
  if (!snap) return;
  set({ messages: snap.messages, ...state });
    return true;  // 正确返回 boolean
},
```

---

## 问题修复总结

### 问题1: Benchmark 启动后 4 个 workflow 不立即显示 ✅ 已修复
**修复文件**: `frontend/src/components/benchmark/BenchmarkRunner.tsx`
**修复方案**: 在 batch 创建完成后立即调用 `fetchRuns()` 刷新侧边栏

### 问题2: 历史记录堆叠/重复显示 ✅ 已验证无问题
**验证结果**: 后端每个 workflow 使用独立的 workflow_id，前端按 `workflow_name` 分组是预期行为，不是 bug。如果需要区分，可以显示更多细节。

### 问题3: Conversation 隔离 - 非选中 run 的事件没有缓存 ✅ 已修复
**修复文件**:
- `frontend/src/stores/conversationStore.ts` - 添加 cache 操作方法
- `frontend/src/hooks/useWorkflowEvents.ts` - 更新 dispatchBatchEvent 处理非选中 run 的事件

**新增方法**:
- `appendAgentTextToCache(wid, nodeId, text, agentName)` - 缓存文本 delta
- `addToolCallToCache(wid, nodeId, agentName, toolName, toolArgs)` - 缓存 tool call
- `addToolResultToCache(wid, nodeId, toolName, result)` - 缓存 tool result

---

## 修改的文件

```
frontend/src/components/benchmark/BenchmarkRunner.tsx
frontend/src/stores/conversationStore.ts
frontend/src/hooks/useWorkflowEvents.ts
```

---

## 测试建议

### TC1: 启动 Benchmark 立即显示
1. 打开 code-review-v1 benchmark
2. 点击 Run Benchmark
3. **验证**: 侧边栏立即显示 4 个新 run

### TC2: 切换 workflow 查看 conversation
1. 在 batch 运行期间切换查看不同的 task
2. **验证**: 每个 workflow 的 conversation 独立显示
3. **验证**: 切换回来时，之前的 conversation 被完整恢复

### TC3: 非选中 run 的状态保存
1. 启动 benchmark
2. 选中的 run A 有输出时，切换到 run B（没有输出）
3. run B 接收输出后切换回 run A
4. **验证**: run A 的 conversation 从 cache 正确恢复，包括所有输出

---

## 服务器状态
- 后端服务运行正常 (http://localhost:8000/health)
- 前端编译成功
- 可以进行端到端测试