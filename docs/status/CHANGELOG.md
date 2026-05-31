# CHANGELOG

---

## 2026-05-31 Grep/Glob 内置工具

### 新增工具
- **新增** `harness/tools/grep_glob.py` — `GrepToolFactory` + `GlobToolFactory`
- **Grep** — 基于 ripgrep 的内容搜索，支持：regex 模式、文件类型过滤、context 行、大小写不敏感、多行模式、glob 过滤、3 种输出模式（files_with_matches / content / count）、head_limit token 预算控制
- **Glob** — 基于 ripgrep 的文件模式匹配，支持递归 glob、修改时间排序、相对路径输出、100 条上限
- **修改** `harness/tools/defaults.py` — grep/glob 注册为默认内置工具（和 bash 同级）
- 两者均自动排除 .git/node_modules/__pycache__/.codegraph 目录
- rg 未安装时返回安装提示，不抛异常

### 测试
- **新增** `tests/tools/test_grep_glob.py` — 13 个测试覆盖：模式搜索、输出模式、类型过滤、大小写、glob 过滤、context 行、递归匹配、无匹配

### README 路线图
- **新增** "工具路线图"章节 — Skill(P1)、TodoWrite(P2)、Monitor(P2)、WebFetch(P3)、WebSearch(P3)

---

## 2026-05-31 codegraph MCP 集成 + glob 工具选择 + ask_human 清理

**Commits:** `81c4f59` `085b13f` `7d77f74` `3d8813f` `57dc2e8` `a6ca245` `8abe15f` `5adc84f` `f522c67`

### codegraph MCP 集成
- **新增** `setup_codegraph_mcp()` — 自动发现 `codegraph` CLI（$PATH → npx fallback），启动 MCP server 并注册工具
- **修改** `harness/api.py` — `Workflow.__init__` 新增 `enable_filesystem_mcp` / `enable_codegraph_mcp` / `codegraph_path` 参数，控制 MCP 加载
- **修改** `install.py` — 安装步骤新增 `npm install -g @colbymchenry/codegraph`
- **新增** `.claude/mcp.json` — Claude Code 自身的 codegraph MCP 配置

### glob 工具选择（Plan B）
- **新增** `ToolRegistry.expand_globs()` — 支持 fnmatch 风格 glob（`codegraph_*`、`*`）和 `!` 排除（`!codegraph_trace`）
- **修改** `harness/engine/macro_graph.py` — `_resolve_agent_config` 调用 `expand_globs()` 展开 glob 模式
- 示例：`tools=["bash", "codegraph_*"]` 自动加载所有 codegraph 工具；`tools=["*", "!codegraph_*"]` 加载除 codegraph 外的所有工具

### ask_human 清理
- **删除** `harness/tools/ask_human.py` — 已被 ask_user 完全替代，无任何 workflow 引用
- **删除** `tests/tools/test_ask_human.py` / `examples/07_ask_human.py`
- **修改** 多文件 — 移除 ask_human 注册、引用、注释

### 示例
- **新增** `examples/16_codegraph_mcp.py` — codegraph MCP 使用演示（find/callers/impact）
- **新增** `examples/17_codegraph_full_tour.py` — 12 步全工具演练，使用 glob 模式 `tools=["bash", "codegraph_*"]`
- **新增** `examples/fixtures/mini_lib/` — 测试 fixture 项目（3 文件、12 节点、19 边的可预测调用图）
- **新增** `workflows/codegraph_demo/` / `workflows/codegraph_full_tour/` — 对应 workflow 和 agent MD

### 缺陷修复
- **修复** `tool span.start` 时间戳过早 — 改用 FIFO 队列按 tool_name 匹配，延迟 start 到 result 返回时
- **修复** `ask_user.py` — `question_id = str(uuid.uuid4())` 被意外删除导致 NameError
- **修复** `sub_agent.py` — 子 agent 泄露 ask_user/ask_human 工具；执行失败时异常冒泡改为 try/except 捕获
- **修复** `llm.py` — httpx.AsyncClient 资源泄漏，新增 `aclose()` 方法
- **修复** eval demo workflow.json 缺少 judge 节点 — 重新 compile+save 材料化

### 测试
- **新增** `tests/tools/test_registry.py` — 8 个 expand_globs 测试（literal/glob/star/exclusion/dedup/error）
- **新增** `tests/server/test_runner_cancel.py` / `tests/harness/test_resume.py` — resume + cancel 测试

---

## 2026-05-31 sub_agent 工具修复 + token 计数问题

### 缺陷修复（sub_agent）
- **修复** `ask_user.py` — `question_id = str(uuid.uuid4())` 被意外删除，导致 `NameError`，sub_agent 子 agent 调用 ask_user 时直接崩溃
- **修复** `sub_agent.py` — 子 agent 泄露 ask_user/ask_human 工具，这些工具需要 event_bus 和 workflow_id，子 agent 无法正常使用
- **修复** `sub_agent.py` — 子 agent 执行失败时异常冒泡到父 agent，导致整个节点失败；改为 try/except 捕获，返回错误消息字符串
- **修复** `llm.py` — LLMClient 创建的 httpx.AsyncClient 从不关闭，资源泄漏；新增 `aclose()` 方法
- **修复** `sub_agent.py` — finally 中调用 `client.aclose()` 确保资源释放

### ask_human 清理
- **删除** `harness/tools/ask_human.py` — 已被 ask_user 完全替代，无任何 workflow 引用
- **删除** `tests/tools/test_ask_human.py` — 对应测试
- **删除** `examples/07_ask_human.py` — 对应示例
- **修改** `harness/tools/defaults.py` — 移除 ask_human 注册
- **修改** `harness/engine/macro_graph.py` — ask_human → ask_user 注册
- **修改** `harness/tools/sub_agent.py` — _EXCLUDE_FROM_CHILD 移除 ask_human
- **修改** `server/ws_handler.py` / `harness/tools/_human_io.py` / `harness/tools/ask_user.py` — 清理 ask_human 注释

### Token 计数问题（已识别，待修复）
- **问题 1: sub_agent 子 agent token 未计入** — 父 agent 的 usage 只记录自身 LLM 调用，子 agent 的 token 消耗完全丢失
- **问题 2: 缓存命中 token 计费不准确** — DeepSeek 返回 `prompt_cache_hit_tokens`（按 0.1x 计费），harness 仅记录 `input_tokens`（包含缓存命中），导致成本高估。实测：缓存命中时 73% 的 input tokens 被按原价计算
- **问题 3: reasoning_tokens 未单独记录** — DeepSeek 返回 `reasoning_tokens`（含在 output_tokens 中），但 harness 不区分

### 配置
- **新增** `.claude/mcp.json` — 配置 codegraph MCP server（`codegraph serve --mcp`）

---

## 2026-05-30 修复 replay 数据丢失(Bug A + Bug B)

### 缺陷修复
- **修复 Bug A**:刷新后点击 sidebar history 中央/右栏全空白 — `WorkflowScope` 的 reset useEffect 在 `replayEventsToStores` 写入 scoped stores 之后才触发,清空了刚 replay 的数据
- **修复 Bug B**:replay 视图比 live 时显示少 — `replayEvents.ts` 的 `routeReplayEvent` switch 漏了 `step.summary`(BudgetBar 进度条不显示)和 `circular.warning`(右栏 ErrorsTab 看不到警告)

### 结构性重构(消除 live/replay 两套 router 漂移)
- **新增** `routeEvent.ts` — 共享 router,live/replay 共用同一 switch,通过 `RouteContext.persistence` 区分模式(`null` ⇔ replay 模式,跳过 API 副作用)
- **改造** `eventRouter.ts` — `routeEventToStores` 委托共享 `routeEvent`,仅保留 live 特有的 batch/single dispatch 与 saveConversation/saveCharts
- **改造** `replayEvents.ts` — 删除 `routeReplayEvent` / 本地 `resetAllStores` / `formatOutputAsMd`,改为调用共享 `routeEvent`(replay ctx 持 `persistence: null`)
- **改造** `WorkflowScope.tsx` — 删除 reset useEffect 与本地 `resetAllStores`,降格为纯 DI 容器。Reset 责任下放:
  - live:`routeEvent` 在 `workflow.started` 时 reset,带幂等保护(同一 workflow + 已有 nodes 时跳过,防止 WS 重连 since_seq=0 清空数据)
  - replay:`replayEventsToStores` / `loadLegacyRunData` 入口显式 reset

---

## 2026-05-30 条件路由缺陷修复 + 跨重启恢复

### 缺陷修复
- **修复** `after=None` 条件专属节点被错误识别为根节点 — `deps is not None and not deps` 替代 `not deps`，`after=None` 的 agent 不再从 START 触发
- **修复** `Agent.from_dict` 将 `after` 默认值从 `[]` 改为 `None` — 保持 `after=None` 语义不丢失
- **修复** `_build_agents_snapshot` 缺失 `on_pass`/`on_fail`/`eval` 字段 — snapshot/rerun/resume 现在完整保留条件路由信息
- **修复** `AgentDef.after` 类型从 `list[str]` 改为 `list[str] | None` — 匹配实际 `after=None` 用法
- **修复** `AgentSnapshot` 缺少 `on_pass`/`on_fail`/`eval` 字段 — 前端可读取条件边信息

### 跨重启恢复
- **新增** `_reconstruct_run_to_repo` — 进程重启后从磁盘记录重建 Workflow 并注入 repo，支持 resume
- **修改** `resume_run` — 检测到 repo 无记录时自动尝试从磁盘重建（仅 paused 状态）
- **修改** `resume_run` — 自动补 compile + checkpointer（重建的 workflow 未编译）
- **修改** `rerun` — 用 `Agent.from_dict` 保留 on_pass/on_fail/eval，替代旧的 `Agent(name=..., after=...)`

### 数据持久化增强
- **新增** `work_dir` 字段贯穿 RunStore / Runner / routes — 用于 MCP 重连
- **修改** 暂停运行持久化 — 合并已有磁盘记录（保留 agent_io/conversation/events），不再覆盖丢失
- **修改** `get_run` API — 返回 `events` 和 `work_dir` 字段
- **修改** `RunDetail` schema — 新增 `events: list[dict] | None`、`work_dir: str | None`

### 测试
- **新增** `test_agents_snapshot_includes_conditional_edges` — 验证 snapshot 包含 on_pass/on_fail/eval
- **新增** `test_agent_snapshot_schema_accepts_new_fields` — 验证 AgentSnapshot schema 接受新字段

---

## 2026-05-29 可视化增强：Waterfall Timeline + BudgetBar + Regression UI

**Commits:** `f52abdb` `c34a852` `86c0025` `1852810` `f545967` `9fc15d3` `b37c162`

### 后端改动
- **修改** `harness/engine/llm_executor.py` — `span.start`/`span.end` 事件新增 `ts` 字段（epoch ms），4 处 emit 调用
- **修改** `server/routes.py` — `workflow.started` 事件新增 `envelope` 字段（3 处：create/resume/rerun）
- **新增** `tests/harness/engine/test_span_tracing.py` — TestSpanTimestamps 验证 LLM 和 tool span 时间戳

### 前端改动 — Waterfall Timeline
- **新增** `frontend/src/stores/spanStore.ts` — zustand store 收集 span 事件，提供 `computeWaterfallData()` 生成瀑布图数据
- **新增** `frontend/src/components/output/charts/WaterfallChartWidget.tsx` — SVG Gantt 图，每 agent 一行，LLM/tool 分色
- **修改** `frontend/src/types/events.ts` — `ChartPayload.chart_type` 新增 `"waterfall"`；`SpanStartPayload`/`SpanEndPayload` 新增 `ts: number`；`WorkflowStartedPayload` 新增 `envelope`
- **修改** `frontend/src/components/output/ChartWidget.tsx` — 注册 waterfall case
- **修改** `frontend/src/lib/summary/runSummary.ts` — `computeRunSummary` 新增可选 `spanStore` 参数，workflow 完成时生成 "Execution Timeline" 图表
- **修改** `frontend/src/contexts/workflow-context/eventRouter.ts` — 激活 span handler（替换 no-op），传入 scoped spanStore
- **修改** `frontend/src/hooks/useWorkflowEvents.ts` — 激活 span handler
- **修改** `frontend/src/contexts/workflow-context/workflowStores.ts` — 新增 `createSpanStore` factory

### 前端改动 — BudgetBar
- **新增** `frontend/src/components/diagnostics/BudgetBar.tsx` — 3 个进度条（Tokens/Steps/Duration），>80% 黄色，>100% 红色，无 envelope 时隐藏
- **修改** `frontend/src/stores/workflowStore.ts` — state 新增 `envelope` 字段
- **修改** `frontend/src/components/diagnostics/DiagnosticsPanel.tsx` — 集成 BudgetBar

### 前端改动 — Regression UI
- **修改** `frontend/src/components/benchmark/BenchmarkCompare.tsx` — 新增 Regression tab，调用 `GET /api/benchmarks/{name}/regression`，红/绿色标记 regressed/improved

### Code Review 修复 (`b37c162`)
- ChartWidget 缺少 waterfall case（waterfall 是死代码）→ 已补
- runSummary 读单例 spanStore，scoped 上下文无数据 → 传入 scoped store
- BudgetBar barColor 用 capped pct，红色永远不触发 → 改用 rawPct
- waterfall start_ms 竞态可能为负 → Math.max(0, ...) 钳制
- RegressionTab HTTP 400 显示原始错误 → 解析 backend detail 消息

### 行为
- Analysis Tab 完成后新增 "Execution Timeline" 瀑布图，展示每个 agent 的 LLM/tool 调用时序
- 配置 envelope 时，Diagnostics 面板顶部显示预算进度条
- Benchmark Compare 新增 Regression tab，对比两次运行的 score/cost/latency/tokens 回归

---

## 2026-05-28 System Prompt 优化 — Schema 精简 + 工具调用引导 + Token 图表合并 + 前端格式化修复

**Commits:** `49afc7c` `d0b8258` `db835b2` `2243960` `ae11dba`

### 后端改动
- **修改** `harness/engine/macro_graph.py` — `_strip_schema()` 递归移除 JSON Schema 冗余字段（title/anyOf/default），agent system prompt token 减少 ~36%；Output Format 段落新增 "Before each tool call, briefly state what you intend to do and why" 引导
- **修改** `harness/api.py` — `AgentResult` 字段加 `Field(description=...)` 引导 LLM 区分 summary（结论）和 details（推理过程）
- **修改** `harness/extensions/plugins/perf_metrics.py` — token usage 从 N 张独立柱状图合并为单张分组柱状图（hue=kind: input/output），所有 agent 在同一张图中
- **修复** `_strip_schema` 对 `$ref` + null anyOf 的休眠 bug（`Optional[SubModel]` 场景）

### 前端改动
- **修改** `eventRouter.ts` / `useWorkflowEvents.ts` / `replayEvents.ts` — `node.completed` 时始终用 `formatOutputAsMd` 替换 streaming 内容，修复结构化输出显示原始 dict 的问题

### 行为
- LLM 在调用工具前会先解释意图
- Agent 输出 JSON 更精简（~36% token 节省），details 字段包含推理过程
- Analysis tab 中 token usage 只有一张图，包含所有 agent 的 input/output 对比
- 前端不再显示 `{"summary": "...", "details": "..."}` 原始 dict

---

## 2026-05-28 修复工具调用前端渲染：Write/Edit DiffView 空白

**Commit:** (pending)

### 根因
- PydanticAI v1.98.0 的 `ToolCallPart.args` 类型为 `str | dict | None`，后端直接透传给前端
- 前端 `getStringArg()` 假设 args 是 dict，当 args 为 JSON 字符串时所有字段提取静默返回 `undefined`
- `edit_file` 的参数名不匹配：MCP filesystem server 使用 `edits: [{oldText, newText}]`，前端期望 `old_string`/`new_string`

### 后端改动
- **修改** `harness/engine/llm_executor.py` — `_emit_tool_call()` 将 `part.args` 归一化为 dict（JSON 字符串 → json.loads → dict）
- **修改** `harness/engine/llm_executor.py` — `_fire_tool_call_hook()` 修复硬编码 `tool_args={}`，改为从 `self.tool_calls` 取已归一化的 args

### 前端改动
- **修改** `frontend/src/components/conversation/ToolCallMessage.tsx`:
  - 新增 `normalizeArgs()` 防御性解析（兼容 string/dict/historical 数据）
  - `edit_file` 渲染支持 MCP 实际格式 `edits: [{oldText, newText}]`，多 edit 批量显示
  - 新增 `read_text_file` 特殊渲染（MCP 替代 `read_file` 的新工具）
  - `_raw` 兜底时 fallback 到通用 `<pre>` 而非显示空 DiffView
  - 提取 `FILE_TOOLS` Set 消除重复工具名列表

### 行为
- write_file: DiffView 正确显示写入内容
- edit_file: DiffView 正确显示多 edit diff（兼容 MCP `edits[]` 和扁平 `old_string`/`new_string`）
- read_text_file: FileContentView 语法高亮渲染
- 历史运行记录（string args）: 防御性解析兜底

---

## 2026-05-28 README 更新 + 根目录冗余文件清理

**Commit:** (pending)

### 改动
- **更新** `README.md` — 新增"项目根目录解析"章节（三级优先链 + 两层发现机制）、新增 `pip install` 安装方式、新增 CLI 命令参考、更新项目结构（paths.py, registry.py, cli.py, builtin/, runs/）
- **删除** `main.py` — 旧版 demo，已被 `examples/01_minimal.py` 替代
- **删除** `hello.py`, `hello_printer.py`, `fibonacci.py` — 与项目无关的 AI 编程练习产物

---

## 2026-05-28 结构化输出 schema 注入 + fail-fast 上游错误传播 + Console prompt 可见性

**Commits:** (pending)

### 改动
- **修改** `harness/engine/macro_graph.py` — 三项改动:
  - 自动将 `result_type`（默认 AgentResult）的 JSON schema 追加到 system prompt 末尾，LLM 明确知道输出格式要求
  - node_func 执行前检查所有 upstream deps 是否有 error，有则 skip 当前节点并 emit `node.failed`
  - `ext_ctx.messages` 从只有 user message 改为包含 `[system, user]` 两条消息
- **修改** `harness/extensions/base.py` — `AgentConfig` 新增 `system_prompt: str | None` 字段
- **修改** `harness/extensions/console.py` — 三项改动:
  - `_extract_system_prompt` 新增 config fallback 路径
  - 新增 `show_full_prompt=True` 参数，默认不截断 system/user prompt
  - `on_node_start` 传入 `ctx.config` 提取 system prompt

### 行为
- LLM 收到的 system prompt 包含 MD 文件内容 + JSON schema 格式要求，减少 retry
- 节点 retry 耗尽后 error 写入 state.errors，下游节点检测到上游失败自动 skip（fail-fast）
- ConsoleOutput 完整显示 system prompt（含 schema）和 user prompt
- 268 passed, 0 regression

---

## 2026-05-28 集中式项目根目录路径解析 — 支持 pip install 外部目录使用

**Commits:**
- `a6f8709` feat: add harness/paths.py — centralized project root resolution
- `644c86b` refactor: migrate 8 modules to centralized paths from harness/paths.py
- `4c56fdc` fix: add doc comment to get_project_root + align ResourceRegistry with paths module

### 改动
- **新增** `harness/paths.py` — `get_project_root()` 三级优先链：HARNESS_PROJECT_ROOT env → CWD heuristic → package parent fallback；+ 7 个派生路径函数
- **新增** `tests/test_paths.py` — 20 个测试覆盖 env 覆盖、CWD heuristic、fallback、派生路径
- **迁移** 8 个模块，消除所有 `Path(__file__).resolve().parent.parent` 硬编码：
  - `harness/api.py` — `_WORKFLOWS_DIR`, `_BENCHMARKS_DIR`
  - `harness/config.py` — `_ENV_FILE`
  - `harness/compiler/md_parser.py` — `_SHARED_AGENTS_DIR`
  - `harness/run_store.py` — `_DEFAULT_RUNS_DIR`
  - `harness/benchmark_store.py` — `_BENCHMARKS_DIR`
  - `harness/checkpoint.py` — `_DEFAULT_DB_PATH`
  - `harness/prep_executor.py` — `_benchmark_dir()`
  - `harness/engine/micro_agent.py` — `_SHARED_SCRIPTS_DIR`
- **修改** `harness/registry.py` — `ResourceRegistry.__init__` 默认使用 `get_project_root()` 替代 `Path.cwd()`

### 行为
- 开发模式（editable install）：CWD heuristic 识别 repo 根目录，零配置
- pip install 后外部目录：`cd my-project && harness ui` 自动以 CWD 为项目根
- 显式指定：`harness ui --project-root /path/to/project`
- `config.py` 的 `.env` 搜索增加 CWD 优先级
- 268 passed, 0 regression

---

## 2026-05-28 NodeCtx Agent 配置元数据补全 — Console + Frontend

**Commit:** (pending)

### 改动
- **新增** `AgentConfig` dataclass — 聚合 agent 配置元数据 (model, retries, tools, tool_info, agent_md_path, critique, result_type_name)
- **修改** `NodeCtx` — 新增 `config: AgentConfig | None = None` 字段，默认 None 向后兼容
- **修改** `macro_graph.py` — 构造 NodeCtx 时填充 AgentConfig；修复 WorkflowCtx.workflow_name 为空；node.started 事件增加 model 字段
- **修改** `console.py` — 新增 4 个 toggle 开关 (show_model, show_tools, show_config, show_critique)，按开关显示 agent 配置信息
- **修改** 前端事件类型/Store/UI — NodeStartedPayload 增加 model，NodeState 增加 model?，AgentMessage 显示 model badge

### 行为
- Console plugin 默认显示 model、tools、critique；show_config=False 时隐藏路径/重试/schema
- 前端 agent 消息头显示 model badge（如事件中包含 model）
- 所有新字段有默认值，不影响现有功能

---

## 2026-05-28 Agent 工作目录 (work_dir) 支持

**Commit:** (pending)

### 后端改动
- **修改** `harness/api.py` — `Workflow.setup(work_dir=)` 接受显式参数传给 MCP filesystem server；`run()` / `_execute()` 加 `work_dir` 参数并校验；默认 MCP workdir 从 `agents_dir` 改为 `os.getcwd()`
- **修改** `server/runner.py` — `setup(work_dir=work_dir)` 显式传递；`work_dir: "/"` 跳过 forbidden 检查允许全盘访问
- **修改** `server/routes.py` — resume 路径从 repo 恢复 `work_dir`；batch 端点转发 `work_dir`
- **修改** `server/schemas.py` — `CreateBatchRequest` 加 `work_dir` 字段

### 前端改动
- **新增** `frontend/src/stores/settingsStore.ts` — Zustand store + localStorage 持久化 `defaultWorkDir`
- **修改** `HeaderBar.tsx` — Settings popover 加 "Default Work Directory" 输入框
- **修改** `WorkflowLauncher.tsx` — 初始值从 settingsStore 读取，去掉 Browse 按钮，更新提示文字
- **修改** `CenterPanel.tsx` / `ScopedCenterPanel.tsx` — POST body 传 `work_dir`

### 行为
- 不传 `work_dir` → agent 可访问启动脚本所在目录的所有文件
- 传 `work_dir: "/some/path"` → agent 访问该目录
- 传 `work_dir: "/"` → agent 全盘访问
- 前端 Settings 设默认目录 → 所有启动入口自动使用；WorkflowLauncher 可覆盖

---

## 2026-05-28 Frontend UX 持久化与体验改进

**Commit:** (pending)

### P0: URL Search Params 双向同步
- **新增** `frontend/src/hooks/useUrlState.ts` — 双向同步 URL params ↔ Zustand stores
- **修改** `page.tsx` — 集成 useUrlState + benchmark 恢复事件监听
- **修改** `CenterPanel.tsx` — tab 状态从 URL 初始化，切换时同步到 URL
- 刷新后自动恢复 workflow / replay run / active tab / benchmark 视图

### P1: 用户上下文恢复
- **修改** `userStore.ts` — `resetAllStores()` 清除 URL params，回到首页
- 切换用户或点击 Logo 时 URL 参数被正确清除

### P2: Toast 通知系统
- **新增** `frontend/src/components/ui/sonner.tsx` — Sonner Toaster 组件
- **新增** `frontend/src/lib/confirm.ts` — showSuccess / showError / confirmAction
- **修改** `layout.tsx` — 挂载 Toaster
- **修改** `TemplateLibrary.tsx` — alert() → showError()
- **修改** `RunHistoryList.tsx` — confirm() → confirmAction()
- **依赖** sonner (npm)

### P3: Skeleton 加载态
- **新增** `frontend/src/components/ui/skeleton.tsx`
- **新增** `frontend/src/components/sidebar/RunHistorySkeleton.tsx`
- **修改** `RunHistoryList.tsx` — 加载中状态从 Radio spinner 替换为 skeleton

### P4: 全局 ErrorBoundary
- **新增** `frontend/src/components/ErrorBoundary.tsx` — React class component 防白屏
- **修改** `page.tsx` — 包裹 ErrorBoundary

### P5: WebSocket 连接状态指示
- **新增** `frontend/src/components/layout/ConnectionStatusBar.tsx`
- **修改** `useWorkflowWS.ts` — 暴露 isConnected
- **修改** `WorkflowCenterPanel.tsx` — 渲染连接状态条（断连时显示黄色提示）

### 构建产物
- `frontend/out/` 重新构建

---

## 2026-05-27 ~ 2026-05-28 Resource Registry + CLI Command

**Commits:**
- `75a9e06` feat: resource registry + CLI command + pre-built frontend
- `5a005a3` fix(benchmark): batch WebSocket not connecting for default user

### Phase 1: 核心 Registry + 内置资源
- `harness/registry.py` — ResourceRegistry 两层发现（Builtin + Project）+ 全局单例 (22 tests)
- `harness/builtin/workflows/demo_pipeline/` — 内置 workflow
- `harness/builtin/benchmarks/smoke-test/` — 内置 benchmark
- `harness/builtin/frontend/` — 预构建前端 (4.2MB)
- `pyproject.toml` — package-data + console_scripts

### Phase 2: CLI 命令
- `harness/cli.py` — `harness ui` + `harness list`

### Phase 3: 后端最小适配
- `harness/api.py` — Workflow.load/list_saved/Benchmark._execute 加 registry fallback
- `harness/benchmark_store.py` — load_benchmark 加 registry fallback
- `server/routes.py` — _validate_workflow_dir 加 registry fallback
- `server/app.py` — _resolve_frontend_dir 三路径 fallback

### 待做 Phase 4
- 前端 scope badge (builtin/project)
- Builtin 资源只读控制 (隐藏 Delete, 禁用 Save)

---

## 2026-05-27 WS 事件流修复 + 前端重构 + Benchmark 隔离

**Commit:** `a391274` fix: WS event stream + frontend refactor + benchmark isolation

---

## 2026-05-27 清理一次性报告文件

**Commit:** `e62a2d6` chore: remove one-time report MD files from root
