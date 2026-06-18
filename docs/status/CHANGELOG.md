# CHANGELOG

索引。详细信息见 [`docs/releases/`](../releases/)。
规则：见 [CLAUDE.md — CHANGELOG 规则](../../CLAUDE.md#changelog-规则)。

每条 1-2 句话 + 链接到对应 release note。

---

## 2026-06

- **2026-06-17** — **Single-source index-driven refactor — COMPLETE（82/82 任务）**：7 个 phase 全部完成。NAS 前端"修了 N 次还坏"的结构性根因（5 个数据源独立计算 + 隐式契约）通过收敛单一数据源根治：iter 元数据走 `+iter_index.json`（D1）；iter 内容（tool_calls+todo_steps+output）走 `+iters+{node}+{iter}.json`（D2）；streaming 生命周期由 `InflightSidecarWriter` 管理 + `Bus.add_sync_listener` 实时路由（D7）；snapshot 退化为 < 1KB manifest（D3，原 300KB+）；run_record 不再持久化 conversation（D4）；`/runs/{id}/conversation` 加 Deprecation header（D6）；`/runs/{id}/conversation?node_id&iter_num` 投影 tool_calls 为 tool_call messages；前端 `AgentDetailView` 每个 iter 走 fetch（live WS 优先）；新增 schemas/、`harness/persistence/{sidecar_io,sidecar_writer,validate}.py`、`scripts/{lint_runs,migrate_runs_v1_to_v2}.py`、Makefile。**137 backend + 267 frontend 测试全过**；真实 NAS run `5c6eac84` outline iter_count 14 节点全 match；端到端 D5/D7 契约（streaming→completed + last_seq 同步点）验证。
  → [完整 release note](../releases/2026-06-17-single-source-index-driven-complete.md) | [ADR](../refactor/single-source-index-driven/ADR.md)

- **2026-06-17** — **Phase 5: run_record 清理（single-source 重构 / ADR D4+D6）**：5 个任务。`_save_incremental` 调 `RunStore.save()` 不再传 `conversation`（D4 落地）；`/runs/{id}/conversation` 端点加 `Deprecation: true` + `Sunset` + `Link rel="successor-version"` header + WARNING log；4 个新单测覆盖旧 run record 兼容性（legacy conversation 仍可读、新 run record 写空 list）。32 个 server + E2E 测试全过。runs.py 行数 invariant 从 600 提升到 850（D6 deprecation headers + tool_call projection 新增）。
  → [详情](../releases/2026-06-17-single-source-index-driven-complete.md)

- **2026-06-17** — **Phase 4: snapshot 瘦身（single-source 重构 / ADR D3+D5）**：8 个任务。snapshot 写盘移除 conversation / agent_io / todo_states / conversation_total / nodes_latest（→ latest_iter_by_node）；seq_cursor 重命名为 last_seq（D7 同步点）；加 `version: 2` 标记；前端 `hydrateFromSnapshot` 不再依赖 conversation（保留 legacy 兼容分支）；`AgentDetailView` 每个 iter 走 fetch（live WS 优先，D5 完整落地）；6 个新单测断言 snapshot < 10KB + 字段完整性；`lint_runs.py` I6 区分 v1（warn）/ v2（error）。NAS 9-agent snapshot 从 342KB 降到 736 bytes。267 frontend + 137 backend 测试全过。
  → [详情](../releases/2026-06-17-single-source-index-driven-complete.md)

- **2026-06-17** — **Phase 3: E2E contract tests（single-source 重构 / ADR D5+D7）**：10 个任务。原计划 vitest+msw 替换为 Python TestClient + RunStore DI override，直接测前端依赖的 API 契约表面（10 个 E2E 测试覆盖 outline/iter_counts、iter 切换、agent 切换、refresh 稳定性、streaming 检索、node.completed transition、since_seq 同步点、schema 合规）。前端 240+ 单测已覆盖渲染层，无需 msw 浏览器模拟。
  → [详情](../releases/2026-06-17-single-source-index-driven-complete.md)

- **2026-06-17** — **Phase 2: sidecar 内容完整化 + D7 生命周期（single-source 重构 / ADR D2+D7+O1）**：29 个任务（P2a 7 + P2b 22）。**P2a**: 抽 `_build_iter_data` pure helper；sidecar 写 `tool_calls`（agent_io 复制）+ `todo_steps`（按 iter 过滤，O1 落地）；`_iter_sidecar_to_messages` 投影 tool_calls 为 tool_call messages（含 null tool_result 边界）。**P2b**: 新增 `harness/persistence/sidecar_writer.py`（`InflightSidecarWriter` + `InflightWriterRegistry` + `attach_to_bus`）；lifecycle methods（on_started / on_text_delta / on_tool_call / on_tool_result / finalize / mark_failed / mark_interrupted）；500ms debounce for text + 立即 flush on tool_call 边界；所有写盘走 `save_iter_sidecar_safe`（R3）；`Bus.add_sync_listener`/`remove_sync_listener` 新增（fire-and-forget sync callback for writer）；`mark_interrupted` writer API ready（startup-sweep 调用方留给 runner 集成）。26 单测 + 95 全套 persistence/bus/engine/outline 测试全过；真实 4a8dc827 fixture 验证 scout iter=1 → 25 tool_calls、scout iter=3 → 5 todo_steps；端到端 bus→writer 验证 mid-stream streaming sidecar + final completed sidecar 切换正确。
  → [详情](../releases/2026-06-17-phase-2-sidecar-content-lifecycle.md)

- **2026-06-17** — **Phase 1: outline 走 iter_index（single-source 重构 / ADR D1）**：8 个任务。`compute_outline` 加 `iter_index` 参数，**完全移除** events-based `iter_set` 扫描（events buffer FIFO 在长 NAS run 中淘汰早期 `node.started`，iter_count 永远算不对）；fallback：iter_index=None/{} 时为每个 DAG 节点合成 iter=1 条目（legacy/setup-only run 兼容）。`save_outline_sidecar` 透传 iter_index；`harness/engine/incremental_save.py` 把已读的 `invocation_counts_raw` 传过去（零额外 I/O）。18 outline 测试全过（15 旧 + 3 新）；真实 NAS run `5c6eac84` outline iter counts 与 iter_index 完全一致（scout=3, selector=6, judger=5 等 14 节点全 match）。
  → [详情](../releases/2026-06-17-phase-1-outline-from-iter-index.md)

- **2026-06-17** — **Phase 0: Schema + 原子写盘 + CI lint（single-source 重构）**：18 个任务。新增 `schemas/{snapshot,iter_sidecar,iter_index}.v2.schema.json`（additionalProperties:false + 兼容旧字段）；新增 `harness/persistence/sidecar_io.py`（`atomic_write_json` + `verify_write` + `save_iter_sidecar_safe` —— R3 落地：atomic + verify + retry + log loud + 不 raise）；新增 `harness/persistence/validate.py`（3 个 validate_* 用 jsonschema iter_errors 一次返回所有错误）；`harness/engine/incremental_save.py` 改用 `save_iter_sidecar_safe` 替代直接 `save_iter_sidecar`；新增 `scripts/lint_runs.py`（I1/I3/I6/I7/I8/I9 不变量检查 + schema 校验，`--strict` 模式 post-P4 启用）；新增 `Makefile` 的 `lint-runs` / `lint-runs-strict` / `test-persistence` target；`CLAUDE.md` 加 runs/ 持久化契约段。23 个新单测 + 4/57/4 个真实 runs 文件全部通过 v2 schema 校验。Lint baseline：0 error + 65 warn（全部是 pre-P2b/P4 已知遗留）。
  → [详情](../releases/2026-06-17-phase-0-schema-validation.md)

- **2026-06-17** — **Conversation latest-iter 全量加载 + 历史 iter 按需**：修历史刷新后 outline 列出所有 agent 但点任意一个显示 "iter 1 yet" 的多层 bug。根因：snapshot 切 `conversation[-50:]` 把 NAS 9-agent × 500+ 消息切到只剩最后 agent 尾部 tool_call；`build_conversation` 没写 `iteration` 字段；`hydrateFromSnapshot` 直接 setState raw dict 未经 DTO 转换。修复：(1) `build_conversation` 加 `invocation_counts` 参数 + `message.iteration` 字段；(2) snapshot 不再切 tail，全量 latest-iter 写入（`agent_io` 本来就只保留最新 iter，所以 conversation 天然 latest-iter）；(3) `/runs/{id}/conversation` 加 `node_id`+`iter_num` 参数，按需读 `+iters+{node}+{iter}.json` sidecar；(4) `hydrateFromSnapshot` 改用 `dtoListToMessages`；(5) `AgentDetailView` 切历史 iter 时拉 sidecar + 本地 cache。24 backend + 267 frontend 测试全过。
  → [详情](../releases/2026-06-17-conversation-latest-iter-fix.md)

- **2026-06-17** — **Outline iter collapse + node iter dropdown**：长 loop workflow（NAS）下 cycle agent 跑 N 轮时，sidebar 从"每个 iter 一行"改为"按 nodeId 折叠成一行 + ⇡N badge"。Detail panel 顶部新增 sticky iter dropdown（`NodeIterSelector`，Radix Select），默认显示 latestIter，用户切换后**按 nodeId 保留选择** —— 切到别的 agent 再切回来仍停在原 iter。`outlineStore.selectedKey` → `selectedNodeId` + `selectedIterByNode: Record`，新增 `selectIter` action。`useAgentOutline` 末端加 `groupOutlineByNode` 派生（view 层折叠，sidecar schema 不动）；`useAutoFollowSelection` / `useWaitingAgentToast` 跟着切到 `OutlineGroup[]`。`OutlineItemRow.tsx` 删除（被 `OutlineGroupRow.tsx` 替代）。57 个 outline 测试 + 260 个全量前端测试全过；TypeScript 0 outline 相关错误。
  → [详情](../releases/2026-06-17-outline-iter-collapse.md)

- **2026-06-17** — **`harness run` 后续修复 #2/#3/#4**（Cp1-7 收尾）：修 framework 级 bug + UX/防御性问题。**#4 [P1]** `arun_workflow` 现在真正 dispatch `on_workflow_start/end` hooks（之前 engine 只 dispatch node-level，workflow-level lifecycle 从不触发，让 `ConsoleOutput` 的 🚀 Workflow header 隐形 N 个月、TuiRenderer 不得不加 `start()` workaround）；TuiRenderer 回归纯 `BaseHook`，删 workaround；langgraph interrupt 路径跳过 end dispatch 防 Live flicker；12 个新测试锁定契约。**#2 [P2]** MCP cleanup stderr 噪音从 30-80 行 trace 降到 3 行单行 warning（`disconnect` `except BaseException` catch CancelledError + `cli.py` 装 `sys.unraisablehook` 过滤 "Event loop is closed"）。**#3 [P3]** `sidebar.on_usage_update` 加 fallback 字段名链（`cumulative_input` → `total_input_tokens` → `input_tokens_cumulative`），防御未来 LLMExecutor 字段重命名静默归零。端到端 demo_pipeline 验证：3 agents success / 0 traceback / Token 累积正常显示。
  → [详情](../releases/2026-06-17-cli-run-followup-fixes.md)（commits `b1466c4` / `cf964d5`）

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
