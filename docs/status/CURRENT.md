# Current Task

**当前任务**: outline review 全部修复完成（Batch A + B），等待 browser 烟测 + 选 next focus
**状态**: Plan G 已合入 main；浏览器手测待跑（Bug 2 / toast 行为）
**日期**: 2026-06-12
**分支**: `main` (HEAD: `df5f406`)

## 必读文件

- `docs/releases/2026-06-12-outline-toast-hook-split.md` — Plan G 实际产出
- `docs/releases/2026-06-12-outline-review-batch-a.md` — Batch A 产出
- `CLAUDE.md` — 协作规则 + CHANGELOG 规则

## 待办（不阻塞，需用户配合）

### Browser 烟测 Plan G Task 1.4 / 3.2

dev server 起来后，在含 ask_user 的 workflow 里验证：

- [ ] 第一次 ask: toast 出现 + outline 自动 select（autoFollow 默认 on）
- [ ] 答完
- [ ] **同一 agent** 第二次 ask: toast 再次出现（Bug 2 核心 case）
- [ ] toggle autoFollow off (Pinned)：第三次 ask 来自不同 agent → toast 仍出现，但 selection 不变

如果某项行为异常，回头看 `useWaitingAgentToast.ts` 的 questionId 边沿逻辑。

## 候选 next focus

| 选项 | 说明 |
|------|------|
| **A. 浏览器手测 outline** | 5 场景：NAS loop / Replay / Timeline / 单 iter / interrupted（含 Plan G toast 验证） |
| **B. NAS 任务 4** | NAS Orchestrator Agent MD（待实现） |
| **C. NAS 任务 5** | 3 层 MD 历史写入（待实现） |
| **D. Outline 二轮 review** | Arch 4（AgentDetailView ref 桥接清理） + j/k 导航组件测试 |

## 已知 follow-up（小，不阻塞）

- **Arch 4 · AgentDetailView ref 桥接 pattern** — 旧 pattern 复用，可作单独清理任务
- **j/k 导航无组件测试** — listener 重构已完成，逻辑被 derive 测试覆盖，缺组件级 e2e
- **`NodeCompletedPayload.iteration` 未加** — LangGraph 不 pipeline 同 node，实际不触发；可加 invariant 测试 pin

## NAS 待做（项目级）

| # | 任务 | 状态 |
|---|------|------|
| 3 | 代码隔离方案独立测试 | 待验证 |
| 4 | NAS Orchestrator Agent MD | 待实现 |
| 5 | 3 层 MD 历史写入 | 待实现 |
