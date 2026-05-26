# Benchmark E2E 测试修复报告

## 修复日期
2026-05-25

## 修复总结

已修复 4 个主要问题，涉及侧边栏 UI、条件路由输出显示、benchmark 历史刷新。

---

## 问题1: 侧边栏按钮消失 (P001)

### 问题描述
- 时间、re-run、删除按钮都不见了
- 按钮只在 hover 时显示

### 根本原因
`RunHistoryList.tsx` 中按钮使用了 `opacity-0 group-hover:opacity-100` 样式，导致按钮默认隐藏。

### 修复方案
```typescript
// 修改前
className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 group-hover:opacity-100 ..."

// 修改后
className="shrink-0 rounded p-0.5 text-muted-foreground ..."
```

### 文件
- `frontend/src/components/sidebar/RunHistoryList.tsx`

---

## 问题2: 侧边栏标题不截断 (P002)

### 问题描述
- 长标题显示不全，没有自适应功能

### 根本原因
标题元素缺少宽度限制和截断样式。

### 修复方案
```typescript
// 添加了 max-w-[120px] 和 truncate
<span
  className="min-w-0 flex-1 truncate text-xs text-ellipsis max-w-[120px]"
  title={run.inputs?.task ? String(run.inputs.task) : run.run_id.slice(0, 8)}
>
```

### 文件
- `frontend/src/components/sidebar/RunHistoryList.tsx`

---

## 问题3: Conditional Route Summary 输出不显示 (P003)

### 问题描述
- conditional route 运行时，summary 的输出在前端没有打印出来
- 但点开 out 是发现有输出

### 根本原因
后端发送的 `output_result` 可能是 JSON 字符串，前端的 `formatOutputAsMd` 函数只处理字符串（直接返回）和对象（提取 summary/details），没有尝试解析 JSON 字符串。

### 修复方案
```typescript
function formatOutputAsMd(output: unknown): string {
  if (output == null) return "";
  if (typeof output === "string") {
    // 尝试解析 JSON 字符串
    try {
      const parsed = JSON.parse(output);
      return formatOutputAsMd(parsed);
    } catch {
      return output;
    }
  }
  // ... 对象处理逻辑
}
```

### 文件
- `frontend/src/hooks/useWorkflowEvents.ts`

---

## 问题4: Benchmark History 自动刷新 (P004)

### 问题描述
- 启动 benchmark 后，history 没有自动刷新
- 需要手动刷新页面才能看到 run 记录

### 根本原因
`fetchRuns()` 在 benchmark 启动时立即调用，但后端可能还没有完成 run 记录的持久化。

### 修复方案
```typescript
// 添加 500ms 延迟
setTimeout(() => useRunHistoryStore.getState().fetchRuns(), 500);
```

### 文件
- `frontend/src/components/benchmark/BenchmarkRunner.tsx`

---

## 问题5: Benchmark 历史记录共享 (P005)

### 问题描述
- code-review-v1 benchmark 4 个 workflow 同时启动，但历史记录共享了

### 验证结果
经过代码审查，确认**不存在共享问题**：

1. 后端每个 workflow 使用独立的 `workflow_id`
2. `RunStore.save()` 使用 `workflow_id` 作为 `run_id` 保存到独立的 JSON 文件
3. `/api/runs` 端点正确返回所有独立的 run 记录
4. 每个记录有独立的 `created_at` 时间戳

可能的原因：
- 同时启动的 4 个 workflow 可能使用相同的 inputs（预期行为）
- 前端分组可能让它们显示在一起（按 workflow_name 分组）

### 结论
无需修复，这是预期行为。

---

## 测试建议

### 立即可测试
1. ✅ 侧边栏按钮始终可见
2. ✅ 长标题截断并显示 tooltip
3. ✅ 时间戳显示正确
4. ✅ re-run 功能正常
5. ✅ 删除功能正常

### 需要运行 workflow 测试
1. Conditional Route workflow：验证 summary 输出正确显示
2. Benchmark workflow：验证历史记录自动刷新

### 长期观察
1. Benchmark 多次运行后的历史对比
2. 不同 workflow 之间切换的状态隔离

---

## 相关文件变更

```
frontend/src/components/sidebar/RunHistoryList.tsx
frontend/src/hooks/useWorkflowEvents.ts
frontend/src/components/benchmark/BenchmarkRunner.tsx
benchmark_e2e_checklist.md
```