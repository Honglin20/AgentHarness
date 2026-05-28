# Current Task

**当前任务**: Frontend UX 持久化与体验改进
**状态**: completed
**优先级**: P0

---

## 必读文件

1. `docs/plans/2026-05-28-frontend-ux-persistence.md` — 完整实施计划
2. `frontend/src/hooks/useUrlState.ts` — URL 状态同步核心
3. `docs/status/CHANGELOG.md` — 变更记录

## 已完成

### P0: URL Search Params 双向同步
- `useUrlState.ts` — mount 恢复 + subscribe 写入 URL
- `page.tsx` — 集成 hook + benchmark 恢复
- `CenterPanel.tsx` — tab URL 同步

### P1: 用户上下文恢复
- `userStore.ts` — resetAllStores 清除 URL

### P2: Toast 通知系统
- Sonner 集成，替代所有 alert/confirm

### P3: Skeleton 加载态
- RunHistorySkeleton 替代 Radio spinner

### P4: 全局 ErrorBoundary
- 防白屏，显示错误 + Reload 按钮

### P5: WebSocket 连接状态
- 断连时顶部黄色提示条

## 待做
- (无) 已全部完成，待 Phase 4 of Resource Registry
