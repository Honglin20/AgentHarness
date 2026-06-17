# Current Task

**当前任务**: 前端 review（用户 goal）— **conversation latest-iter 修复已落地，等待真机验证**
**状态**: P0 conversation 修复 + 单测 + build 全过；用户尚未跑真机验证
**日期**: 2026-06-17
**分支**: `main`

## 本次完成

| Commit | 内容 |
|---|---|
| `6b36e67` | fix(conversation): load latest-iter content for all agents + lazy-load historical iters |
| `6b8bc61` | test(conversation): cover iteration field + per-iter sidecar projection |
| `c868505` | chore(frontend): rebuild out/ for conversation iter-fix deployment |

详见 [`docs/releases/2026-06-17-conversation-latest-iter-fix.md`](../releases/2026-06-17-conversation-latest-iter-fix.md)。

## 修复了什么

刷新页面后历史 run outline 显示 9 个 agent 但点任意一个显示 "iter 1 yet" 的多层 bug：

1. snapshot 切 `conversation[-50:]` → NAS 500+ 消息被切到只剩最后 agent 尾部
2. `build_conversation` 没写 `iteration` 字段
3. `hydrateFromSnapshot` 没经 DTO 转换

修复后：
- snapshot 全量写入 latest-iter conversation（agent_io 本来就只保留最新 iter）
- message 带 `iteration` 字段
- 历史 iter 切 dropdown 时拉 `+iters+{node}+{iter}.json` sidecar

## 验证状态

- ✅ backend `test_collectors.py` 24/24
- ✅ frontend vitest 267/267（基线 265 + 新增 2）
- ✅ frontend npm run build
- ⏳ **等待用户真机验证**：启动 server，刷新 NAS run，确认每个 agent 都能看到 latest iter 内容；切历史 iter 验证 sidecar 拉取

## 必读文件

- [`docs/releases/2026-06-17-conversation-latest-iter-fix.md`](../releases/2026-06-17-conversation-latest-iter-fix.md) — 完整诊断 + 修复方案 + 验证矩阵
- `harness/extensions/collectors.py` — `build_conversation` 加 `invocation_counts`
- `harness/engine/incremental_save.py` — snapshot 不切 tail，传 invocation_counts
- `server/routers/runs.py` — conversation 端点加 `node_id` + `iter_num`
- `frontend/src/stores/hydration/hydrateReplay.ts` — `hydrateFromSnapshot` 用 dtoListToMessages
- `frontend/src/components/outline/AgentDetailView.tsx` — 切历史 iter 时拉 sidecar

## 未决项（用户讨论决定不做）

- **per-agent 目录重构**（Phase 2）：现有 sidecar 已能 per-iter 按需加载，本次 P0 不值得做数据迁移
- **`initUser` 死代码**：用户选不动，default user 后端兜底
- **`estimateSize` 虚拟化估算不准**（P1）：用户没选，留待后续
- **running↔history 切换边界 case**（P2）：诊断已完成（activateRun 已部分修复），未做改动
- **30s polling / 性能遗留点**（P2）：诊断已完成，未做改动
