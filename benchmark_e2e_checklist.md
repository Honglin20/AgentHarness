# Benchmark E2E 测试检查清单

## 测试环境
- API: 真实API
- 前端: Web UI
- 后端: FastAPI + LangGraph

---

## 已知问题列表

### 1. 左边侧边栏问题 (RunHistoryList)
- [x] 时间、re-run、删除按钮不见了
- [x] 没有自适应功能，title 长了显示不全
- [ ] 预期: 悬停显示完整标题
- [ ] 预期: 可以显示时间戳
- [ ] 预期: 可以点击 re-run 重新运行
- [ ] 预期: 可以点击删除按钮删除记录

### 2. Conditional Route 问题
- [x] analyzer/classifier 正常运行
- [x] summary 的输出在前端没有打印出来，但 out 里有输出
- [ ] 预期: 所有 agent 输出都应显示在 conversation 面板

### 3. Benchmark 问题
#### 3.1 History 刷新
- [x] 启动 benchmark 后，history 没有自动刷新
- [ ] 预期: benchmark 启动后 sidebar 自动更新

#### 3.2 Benchmark History 记录
- [x] benchmark 跑完后没有 benchmark 历史记录
- [ ] 预期: 在 Benchmark Compare 页面的 history tab 可以看到历史运行对比

#### 3.3 Tag/任务无法测试
- [ ] 预期: benchmark runner 中可以逐个点击任务查看详情
- [ ] 预期: benchmark runner 中任务状态实时更新

#### 3.4 历史记录共享问题
- [x] code-review-v1 benchmark 4 个 workflow 同时启动，但历史记录共享了
- [ ] 预期: 每个 workflow run 有独立的历史记录

---

## 功能测试清单

### A. Workflow 基础功能
- [ ] A1. 创建并运行单个 workflow
- [ ] A2. 查看实时状态（running → completed/failed）
- [ ] A3. 查看 agent 输出（conversation 面板）
- [ ] A4. 查看 DAG 节点状态
- [ ] A5. 查看 output 输出
- [ ] A6. 暂停/恢复 workflow
- [ ] A7. Re-run 历史记录
- [ ] A8. 删除历史记录

### B. Conditional Edge 功能
- [ ] B1. 测试 on_pass 路由（审查通过）
- [ ] B2. 测试 on_fail 路由（审查失败，回环）
- [ ] B3. 回环时注入 previous judgment 上下文
- [ ] B4. 前端显示虚线条件边
- [ ] B5. 前端显示 pass/fail 标签

### C. Benchmark 功能
#### C1. Benchmark 定义
- [ ] 查看 benchmark 列表
- [ ] 查看 benchmark 详情
- [ ] 创建/编辑 benchmark（如果有 UI）

#### C2. Benchmark 运行
- [ ] 选择 workflow 运行 benchmark
- [ ] 查看批量运行进度
- [ ] 切换查看不同 task 的运行状态
- [ ] 实时更新任务状态（running → completed/failed）

#### C3. Benchmark 结果
- [ ] Scores tab 显示平均分数
- [ ] Scores tab 显示柱状图
- [ ] Scores tab 显示任务详情表格
- [ ] Charts tab 显示生成的图表
- [ ] Workflows tab 支持对比多次运行
- [ ] History tab 显示历史趋势

#### C4. Benchmark History
- [ ] benchmark 完成后在 sidebar 显示记录
- [ ] benchmark 记录与普通 workflow 记录区分
- [ ] 可以 re-run benchmark
- [ ] 可以删除 benchmark 记录

### D. 前端 UI 响应性
- [ ] D1. 侧边栏历史记录项自适应宽度
- [ ] D2. 长标题 hover 显示完整内容
- [ ] D3. 按钮悬停时高亮
- [ ] D4. 实时状态更新（动画/图标）

### E. WebSocket 连接
- [ ] E1. 单 workflow WS 连接稳定
- [ ] E2. Batch WS 连接稳定
- [ ] E3. WS 断开自动重连
- [ ] E4. 事件正确路由到对应 store

### F. 数据持久化
- [ ] F1. 完成的 workflow 保存到 runs/
- [ ] F2. Benchmark 结果保存到 benchmarks/<name>/results/
- [ ] F3. Conversation 正确保存和恢复
- [ ] F4. Charts 正确保存和恢复

---

## 测试用例

### TC1: 单 Workflow 运行
1. 在 Web UI 选择一个 workflow（如 chart_demo）
2. 点击运行
3. 验证: workflow 状态更新为 running
4. 验证: DAG 节点实时更新状态
5. 验证: conversation 面板显示 agent 输出
6. 验证: output 面板显示文本输出
7. 等待完成后验证: 状态变为 completed
8. 验证: 侧边栏 history 自动刷新并显示该记录

### TC2: Re-run Workflow
1. 从侧边栏选择一个已完成的 run
2. 点击 re-run 按钮
3. 验证: 创建新的 workflow run
4. 验证: 侧边栏显示新 run 在顶部
5. 验证: DAG 显示新 run 的执行过程

### TC3: Conditional Edge Workflow
1. 运行带条件边的 workflow（如 conditional route）
2. 观察执行路径
3. 验证: 所有 agent 输出显示在 conversation 面板
4. 验证: DAG 显示条件边（虚线 + pass/fail 标签）

### TC4: Benchmark 运行
1. 打开 Benchmark 页面
2. 选择 code-review-v1 benchmark
3. 选择 workflow
4. 点击 Run Benchmark
5. 验证: 4 个任务同时启动
6. 验证: 每个任务状态实时更新
7. 验证: 侧边栏 history 自动刷新显示 4 个 run
8. 等待完成后验证: status 显示 All done
9. 验证: 可以切换查看不同 task 的详情

### TC5: Benchmark 对比
1. 完成 benchmark 运行
2. 切换到 Compare 视图
3. 验证: Scores tab 显示平均分和柱状图
4. 验证: Charts tab 显示图表（如果有）
5. 验证: History tab 显示历史记录

### TC6: 侧边栏响应性
1. 打开一个长标题的 run
2. 验证: hover 时显示完整标题
3. 验证: re-run 按钮可见且可点击
4. 验证: 删除按钮可见且可点击
5. 验证: 时间戳显示正确

---

## 问题追踪

| 问题ID | 描述 | 状态 | 修复时间 |
|--------|------|------|----------|
| P001 | 侧边栏按钮消失 | ✅ 已修复 | 2026-05-25 |
| P002 | 侧边栏标题不截断 | ✅ 已修复 | 2026-05-25 |
| P003 | summary 输出不显示 | ✅ 已修复 | 2026-05-25 |
| P004 | benchmark 后 history 不刷新 | ✅ 已修复 | 2026-05-25 |
| P005 | benchmark 历史记录共享 | ✅ 已验证 | 2026-05-25 |

---

## 修复详情

### P001 & P002: 侧边栏UI问题
**文件**: `frontend/src/components/sidebar/RunHistoryList.tsx`
**修复**:
- 移除了按钮的 `opacity-0 group-hover:opacity-100`，现在按钮始终可见
- 将时间戳移到按钮前面，在所有状态下都显示
- 添加 `max-w-[120px]` 限制标题宽度，确保截断

### P003: Conditional Route Summary 输出不显示
**文件**: `frontend/src/hooks/useWorkflowEvents.ts`
**修复**:
- 更新 `formatOutputAsMd` 函数，尝试解析 JSON 字符串
- 当后端发送 JSON 字符串作为 output_result 时，前端会先尝试解析为对象，然后提取 summary 和 details 字段

### P004: Benchmark History 自动刷新
**文件**: `frontend/src/components/benchmark/BenchmarkRunner.tsx`
**修复**:
- 添加 500ms 延迟后调用 `fetchRuns()`，确保后端已持久化 run 记录

### P005: Benchmark 历史记录共享
**验证**: 后端每个 workflow 使用独立的 workflow_id 作为 run_id 保存，不存在共享问题。前端 `/api/runs` 端点正确返回所有独立的 run 记录。