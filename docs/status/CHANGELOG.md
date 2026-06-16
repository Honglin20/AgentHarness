# CHANGELOG

索引。详细信息见 [`docs/releases/`](../releases/)。
规则：见 [CLAUDE.md — CHANGELOG 规则](../../CLAUDE.md#changelog-规则)。

每条 1-2 句话 + 链接到对应 release note。

---

## 2026-06

- **2026-06-17** — **`harness run` TUI 渲染层（Cp5-7）**：Rich Live 双栏 TUI 落地 —— `TuiRenderer(BaseHook)` 把 `SidebarPanel`（Agents / Fitness sparkline / Tokens / Tools）+ `MainPanel`（流式 LLM 思考 + tool 调用）通过 `rich.live.Live` + `Layout` 组合成实时刷新 UI。`compact.py` 在非 TTY 自动降级到 `ConsoleOutput`（防 ANSI 光标码污染 CI 日志）。`cycle_events.py` 提供可选 `cycle.start/end` 契约让迭代 workflow 显示 "iter N/M" + fitness sparkline。TuiRenderer 同时是 BaseHook **和** bus subscriber，订阅 cycle.end + streaming `agent.usage_update`。106 个测试全过。
  → [详情](../releases/2026-06-17-cli-run-tui.md)

- **2026-06-17** — **NAS workflow: SCOUT collector 化 + planner 变化额度契约**：5 个 setup sub_agent（adapter_generator / domain_analyzer / baseline_runner / tier_planner / metrics_identifier）从 scout 内嵌提升为 DAG 顶层节点，scout 退化为路径汇总 collector（200→100 行，request_limit 500→200）。每个 setup 节点有独立 result_type，中间过程（grep/read/smoke/retry）全部进入 event bus 可见。planner 的"≤3 位置"约束从 prompt 措辞提升到 schema (StrategyInfo model_validator) + helper (validate_manifest.py) + judger (fitness.py contract_violation + type_diversity_penalty) 三层契约；新增 `structural_global` + `new_model_path` 路径支持 planner 提新模型，adapter `get_model` 通过 importlib 动态加载，不动 `_construct_model` 契约边界。candidate_pool 加 `--top-k-per-type` 多样性筛选。
  → [详情](../releases/2026-06-17-nas-scout-decompose-and-change-quota.md)（commits `2cc1b18` / `19fdea3` / `6f04716` / `2abd7d2`）

- **2026-06-17** — **`harness run` CLI + 持久化（Cp1-4）**：新增 `harness run <name>` 命令端到端跑 workflow 并写到与 server 相同的 `runs/` 目录，前端 `GET /api/runs` 自动发现 CLI 历史、零前端修改可 replay。`StdinCoordinator` 单例让 ask_user 在 CLI 模式 opt-in 走 stdin（不影响 WS 路径），`cli_runner.run_with_persistence()` 封装 bus 注入 + Collectors + RunStore.save。`demo_pipeline` 端到端验证通过（3 agents success / 518 events）。Cp5-8（Rich Live TUI 渲染）待启动。
  → [详情](../releases/2026-06-17-cli-run-persistence.md)

- **2026-06-16** — **阶段 3 review follow-ups**：修 C1 critical bug —— UTF-8 字节预算超限（CJK / emoji 内容原代码会超 limit 50%+）；改在字节域切分 + 加防御性 re-trim。补 G1 测试（`test_multibyte_byte_budget_respected` + 小 env 极限用例）。同步把 `import logging` 和 `_lookup_limit_for_event` 移到模块 top-level（消除误导性 lazy 注释）。
- **2026-06-16** — **阶段 3 工具结果截断**：新增 `harness/tools/_truncate.py` 模块，按工具类型限制返回值字节数（bash 8KB / codegraph_* 6KB / sub_agent 4KB），从源头降低 message_history 增长。`_wrap_fn` 重构为无条件截断（不再依赖 dedup_guard），`LLMExecutor.run()` 用 `truncation_context` 注入 (bus, wid, node, agent) 让截断事件 emit `agent.tool_output_truncated`。env `HARNESS_TOOL_RESULT_LIMIT_BYTES` 全局覆盖（0 禁用）。19 个新测试。
  → [详情](../releases/2026-06-16-tool-result-truncation.md)

- **2026-06-16** — **阶段 2 review follow-ups**：(1) BudgetBar 缺 last_* 时不再 fallback 到 cumulative（否则会显示误导的 125% 红条），改为隐藏 Window 行；(2) `cache_hit` 拆为 `cumulative_cache_hit` + `last_cache_hit`（对称）；(3) 加 `negative delta` 测试（clamp + ext.error）+ `setNodeUsage` store 行为测试（确保 last 缺失时保持 undefined）。
  → [详情](../releases/2026-06-16-token-stats-semantic-split.md)

- **2026-06-16** — **阶段 2 Token 统计语义分离**：区分「累计消耗」（cost）和「当前上下文窗口」（window）。LLMExecutor 加 baseline + delta 计算，`agent.usage_update` 事件附 last_input/output/cache_hit；BudgetBar 拆双进度条：Cost 行（累计 / envelope）+ Window 行（max 单次 / 模型上下文上限）。retry 边界 + 旧事件兼容全覆盖。78 后端 + 8 前端测试全过。
  → [详情](../releases/2026-06-16-token-stats-semantic-split.md)

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
