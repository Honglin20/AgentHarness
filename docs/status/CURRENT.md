# Current Task

**当前任务**: P0-B+D step rendering（固定高度虚拟化 + inline expand）
**状态**: 实现完成，待用户验收
**日期**: 2026-06-10

## 已完成 ✅

| R 项 | 内容 |
|------|------|
| P0-A | viewStore: showReplay 同步 resetAllStores，防止切换 run 数据累加 |
| P0-C | ScopedCenterPanel: isReplayView() 覆盖 replay-skeleton 阶段 |
| P0-B | StepRow 固定高度（36/400/600px），消除 ResizeObserver 级联 |
| P0-D | Step 点击展开 inline expand（600px cap，单步展开） |

测试：前端 vitest 111/111，tsc 零错误，next build 成功。

## P0-B+D 实现细节

- **pending step**: 36px（标题 only，disabled）
- **in_progress step**: 400px 固定高度，内部 overflow-y-auto + 自动滚动到底部
- **completed/skipped/interrupted**: 36px 折叠，点击 → 600px 展开（内滚）
- **单步展开限制**: 同一 node 同时只展开一个 step
- **estimateSize**: 基于 step 状态返回固定高度，消除虚拟化重叠
- **NodeBlockCard**: 移除 node-level collapse（L2/L3 toggle），始终显示 steps

## 待办（按优先级）

### 🟡 P1

| ID | 任务 | 备注 |
|----|------|------|
| **P1-E** | tool bar 从底部移入 step 内部 | 需事件层改动 |
| **P1-F** | per-step token/KB 显示 | 需后端 per-message token 数据 |
| **P1-R6** | nodeHandler 冗余 addAgentMessage | 待验证 |

### 🟢 P2

| ID | 任务 | 备注 |
|----|------|------|
| **P2-R345** | snapshot-first hydration | 刷新 10s loading，需独立 ADR |
| **P2-R8** | stepExpanded 持久化 | sessionStorage / URL query |
