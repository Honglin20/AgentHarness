# Current Task

**当前任务**: 全部 P0+P1 完成，待做 P2
**状态**: P0-A/B/C/D + P1-E/F 完成
**日期**: 2026-06-10

## 已完成 ✅

| ID | 内容 |
|----|------|
| P0-A | viewStore: showReplay 同步 resetAllStores |
| P0-B | StepRow 固定高度（36/400/600px） |
| P0-C | isReplayView() 覆盖 replay-skeleton |
| P0-D | Step inline expand（600px cap，单步展开） |
| P1-E | Tool calls 按 stepId 归属到 step 内部（已由 P0-B+D 解决） |
| P1-F | Per-step token 归属 + StepRow badge 显示 |

## 待办

### 🟢 P2

| ID | 任务 | 复杂度 |
|----|------|--------|
| **P2-R345** | snapshot-first hydration（刷新 10s loading） | 复杂，需 ADR |
| **P2-R8** | stepExpanded 持久化（sessionStorage） | 简单 |
