# NAS Workflow 设计与工具扩展

本目录包含 NAS 迭代优化 workflow 的设计文档和工具 spec。

## 目录结构

| 文件 | 内容 |
|------|------|
| [todo-tool.md](./todo-tool.md) | TODO 工具 — Agent 自驱式步骤追踪，当前已实现 |
| [task-tool.md](./task-tool.md) | Task 工具 — 后台任务生命周期管理（待实现） |
| [code-isolation.md](./code-isolation.md) | 并发代码修改隔离方案（待实现） |
| [refactoring-notes.md](./refactoring-notes.md) | 相关大型文件的重构建议 |
| [nas-workflow-architecture.md](./nas-workflow-architecture.md) | NAS 整体架构设计（待实现） |

## 设计原则

参考 Claude Code 的设计哲学：**信任模型，设计环境**。

- Agent 自建步骤，不靠 frontmatter 硬编码
- 工具描述 + `<system-reminder>` 兜底，不信任 agent 的自觉性
- 事件协议前端无关，任何 UI 框架都能消费
- 每个 tool/state 的生命周期 = 单次 node 执行，不跨节点共享

## 开发优先级

1. ✅ TODO 工具 — 已完成
2. ⬜ Task 工具 — 后台任务管理（sub-agent + 训练进程）
3. ⬜ parallel_tasks 工具 — 组合 TODO + Task 的并发执行器
4. ⬜ 代码隔离方案 — git worktree / symlink
5. ⬜ NAS Orchestrator Agent — 整合所有工具的编排 agent
