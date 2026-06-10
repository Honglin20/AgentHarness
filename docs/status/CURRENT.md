# Current Task

**当前任务**: P1 frontend 优化
**状态**: P0 全部完成，P1-F 完成，P1-E 待做
**日期**: 2026-06-10

## 已完成 ✅

| ID | 内容 |
|----|------|
| P0-A | viewStore: showReplay 同步 resetAllStores，防止切换 run 数据累加 |
| P0-C | ScopedCenterPanel: isReplayView() 覆盖 replay-skeleton |
| P0-B | StepRow 固定高度（36/400/600px），消除 ResizeObserver 级联 |
| P0-D | Step 点击展开 inline expand（600px cap，单步展开） |
| P1-F | Per-step token 归属：usage_update delta 累加 + StepRow badge 显示 |

## 待办

### 🟡 P1

| ID | 任务 | 备注 |
|----|------|------|
| **P1-E** | tool bar 从底部移入 step 内部 | 纯前端，medium |
| **P1-R6** | nodeHandler 冗余 addAgentMessage | 已验证有幂等保护，无需改动 |

### 🟢 P2

| ID | 任务 | 备注 |
|----|------|------|
| **P2-R345** | snapshot-first hydration | 刷新 10s loading |
| **P2-R8** | stepExpanded 持久化 | sessionStorage |
