# CHANGELOG

索引。详细信息见 [`docs/releases/`](../releases/)。
规则：见 [CLAUDE.md — CHANGELOG 规则](../../CLAUDE.md#changelog-规则)。

每条 1-2 句话 + 链接到对应 release note。

---

## 2026-06

- **2026-06-16** — **ask_user P1 review follow-ups**：float timeout 接受 / stdin EOFError raise（不再 silent return）/ 进程级 asyncio.Lock 防止并发 prompt 交错。补 5 个测试缺口（float、EOF、stdin lock 序列化、interrupted skip、orphan answer）。
  → [详情](../releases/2026-06-16-ask-user-refresh-timeout-cli.md)（commit `01b5c6d`）

- **2026-06-16** — **ask_user 三缺陷 P0 修复**：(1) emit `chat.answer` / `chat.timeout` 让 WS replay 后刷新场景正确还原（不再"刷新后再次询问"）；(2) `HARNESS_ASK_USER_TIMEOUT` env 替代硬编码 60s，默认 `-1`=无限；(3) bus 为 None 时走 stdin fallback，CLI / `python run_workflow(ui=False)` 模式可用。
  → [详情](../releases/2026-06-16-ask-user-refresh-timeout-cli.md)（commit `af923ad`）

- **2026-06-12** — **失败节点 IO 展示（浅版本）**：`node.failed` 事件加 `io_data`（input_prompt + system_prompt）,前端 agentIO store 路由打通,`AgentMessage` 去掉 `isDone` 门控,output tab fallback 到 streaming 累积文本。格式错误时终于能看到 agent 实际输入/输出了。
  → [详情](../releases/2026-06-12-failed-node-io-display.md)

- **2026-06-12** — **AppView + Hydration 重构**：用 URL 派生的 `AppView` 作为"当前页面"单一真相 + `WorkflowEntry.hydration` 显式字段，根治"刷新运行页面返回 portal"和"首次点 history 不加载"两个 bug。统一 `activateRun` 入口（seq + abort race），删除 `useUrlState` + `portalStore.syncUrl` 双 URL 系统和 `WorkflowScope` pre-populate race。新增 45 个测试（appViewUrl / activateRun / useAppViewUrlSync），全 221/221 通过。
  → [详情](../releases/2026-06-12-appview-hydration-refactor.md)

- **2026-06-12** — **Outline Toast Hook Split (Plan G)**：拆 `useAutoFollowSelection` 为 `useWaitingAgentToast` + `useAutoFollowSelection`，toast 边沿触发改用 `questionId`（带 `__no_qid__` fallback），修复同一 agent 二次 ask 时漏 toast 的 Bug 2。补 11 个 hook 测试。
  → [详情](../releases/2026-06-12-outline-toast-hook-split.md)

- **2026-06-12** — **Outline Review Batch A**：3 项 surgical fix（UI 1 border 冲突、Arch 2 keydown listener 改 ref-based、retry badge 加 status 门控）。Plan G (Batch B) 已就绪待执行。
  → [详情](../releases/2026-06-12-outline-review-batch-a.md)

- **2026-06-12** — **Outline Iter Isolation Hardening (Plan F)**：iter 下沉到后端（`node_invocation_counts` state + `node.started` payload + `StepEntry.iteration`），前端从事件读，不再 counter 自增。后端 = 唯一真值，前端 = 渲染投射。
  → [详情](../releases/2026-06-12-outline-iter-hardening.md)

- **2026-06-12** — **Outline Iter Isolation (Plan E)**：`TodoStep.iteration` + `OutlineItem.isLatestIter` 派生 + `NodeBlockCard` 按 iter 过滤 todo。历史 iter 的 token/retry/duration badge 通过 UI 降级处理。
  → [详情](../releases/2026-06-12-outline-iter-isolation.md)

- **2026-06-11** — **Outline + Master-Detail Conversation View**：Linear 风格 agent 列表 + master-detail 切换 + j/k 导航 + auto-follow + ask_user toast。
  → [详情](../releases/2026-06-11-outline-master-detail.md)

---

## 历史（2026-05-27 ~ 2026-06-10）

合并前未拆分的归档，详见 [`docs/releases/HISTORICAL.md`](../releases/HISTORICAL.md)。
