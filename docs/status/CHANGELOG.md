# CHANGELOG

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
