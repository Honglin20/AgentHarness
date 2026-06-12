# Current Task

**当前任务**: AppView + Hydration 重构已完成代码，等待用户浏览器手测验收
**状态**: 6 phase 全部完成；typecheck/lint/build/单测全绿；dev server 启动 OK
**日期**: 2026-06-12
**分支**: `main`

## 必读文件

- `docs/releases/2026-06-12-appview-hydration-refactor.md` — 详细 release note
- `docs/plans/2026-06-12-appview-hydration-refactor.md` — 完整方案
- `CLAUDE.md` — 协作规则 + CHANGELOG 规则

## 待办：浏览器手测（5 场景）

代码层验证已全部通过（typecheck/lint/build/单测 221/221/dev server 启动）。需要用户在浏览器里验证以下场景：

- [ ] 刷新运行页面 → 立即 skeleton（不闪 portal）→ 内容无缝替换
- [ ] 首次点 history → 立即 skeleton → hydrate 完成
- [ ] 点 running 状态的 history → skeleton → WS 实时进度
- [ ] 双击 history → 第二次激活生效，第一次副作用取消
- [ ] 老 URL `/?wid=R&wf=name` → 自动迁移到 `/?view=run&id=R` 并加载

启动 dev server：`cd frontend && npm run dev`，访问 http://localhost:3000

## 已知 follow-up（不阻塞）

- **`dummyWorkflowStore` mirror 删除** —— 仍负载 template-preview 的 selectedTemplate 读取，需重构 scoped store hook 模式
- **`viewStore.activeView` 与 `runMode` 收敛** —— 两套机制当前共存，可后续统一
- **代码提交** —— 全部改动尚未 commit，等手测通过后由用户决定 commit/push 节奏

## 候选 next focus

| 选项 | 说明 |
|------|------|
| **A. 浏览器手测** | 跑上面 5 场景；若 OK 则 commit |
| **B. 删 dummyWorkflowStore** | 重构 scoped store hook 模式 |
| **C. NAS 任务 4** | NAS Orchestrator Agent MD（待实现） |
