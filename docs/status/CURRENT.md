# Current Task

**当前任务**: P2-R345 Phase 1 已完成并修复，待 Phase 2/3
**状态**: P0 + P1 + P2-R345 Phase 1 + P2-R8 完成
**日期**: 2026-06-10

## 已完成

| ID | 内容 |
|----|------|
| P0-A | viewStore: showReplay 同步 resetAllStores |
| P0-B | StepRow 固定高度（36/400/600px） |
| P0-C | isReplayView() 覆盖 replay-skeleton |
| P0-D | Step inline expand（600px cap，单步展开） |
| P1-E | Tool calls 按 stepId 归属到 step 内部（已由 P0-B+D 解决） |
| P1-F | Per-step token 归属 + StepRow badge 显示 |
| P2-R8 | stepExpanded 持久化（sessionStorage） |
| P2-R345 P1 | todo_steps snapshot-first hydration（builder.todo_states） |

## 待办

### P2（后续阶段）

| ID | 任务 | 复杂度 |
|----|------|--------|
| **P2-R345 P2** | Store hydrator 注册表（9 个 hydrator 函数提取） | 中等 |
| **P2-R345 P3** | Spans 延迟加载（Analysis tab 按需 fetch） | 中等 |

### 已知限制

- Per-step tokenUsage 不持久化（前端 delta 累积，刷新后丢失；node-level token 正确）
