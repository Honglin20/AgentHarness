# CHANGELOG

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
