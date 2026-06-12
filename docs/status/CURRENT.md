# Current Task

**当前任务**: 等待用户决定 next focus（outline iter isolation 已 merge 到 main）
**状态**: outline + Plan E + Plan F 全部完成并合入 main；待手测 + 选 next
**日期**: 2026-06-12
**分支**: `main` (HEAD: `69f3b1f`)

## 必读文件

- `docs/plans/2026-06-12-outline-iter-hardening.md` — Plan F 设计
- `docs/releases/2026-06-12-outline-iter-hardening.md` — Plan F 实际产出
- `CLAUDE.md` — 协作规则 + CHANGELOG 规则

## 候选 next focus

| 选项 | 说明 |
|------|------|
| **A. 浏览器手测 outline** | 5 场景：NAS loop / Replay / Timeline / 单 iter / interrupted |
| **B. NAS 任务 4** | NAS Orchestrator Agent MD（待实现） |
| **C. NAS 任务 5** | 3 层 MD 历史写入（待实现） |
| **D. Outline follow-up** | 装 `@testing-library/react` 补 T4 / `NodeCompletedPayload.iteration` invariant 测试 |

## 已知 follow-up（小，不阻塞）

- **Task 6.2 跳过** — `@testing-library/react` 未安装，NodeBlockCard 组件级测试未写（核心逻辑已有单元测试覆盖）
- **`NodeCompletedPayload.iteration` 未加** — LangGraph 不 pipeline 同 node，实际不触发；可加 invariant 测试 pin
- **Backend pytest testpaths** — `pyproject.toml` 配置 `testpaths=["tests"]`，但 `harness/` 下的测试需要 explicit path 调用

## NAS 待做（项目级）

| # | 任务 | 状态 |
|---|------|------|
| 3 | 代码隔离方案独立测试 | 待验证 |
| 4 | NAS Orchestrator Agent MD | 待实现 |
| 5 | 3 层 MD 历史写入 | 待实现 |
