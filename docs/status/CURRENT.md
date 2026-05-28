# Current Task

**当前任务**: Resource Registry + CLI Command
**状态**: completed (Phase 1-3)
**优先级**: P1

---

## 必读文件

1. `docs/specs/2026-05-28-resource-registry-and-cli.md` — 完整 SPEC + 实施记录
2. `harness/registry.py` — 核心：ResourceRegistry 两层发现
3. `harness/cli.py` — CLI 入口：`harness ui` / `harness list`
4. `server/app.py` — `_resolve_frontend_dir()` 前端三路径 fallback

## 已完成

### Phase 1: 核心 Registry + 内置资源
- `harness/registry.py` — ResourceRegistry + 全局单例 (22 测试)
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

## 验证
- 248/248 测试通过（1 个预先存在的失败无关）
- `harness list` 从任意目录显示 builtin 资源
- pip install 模拟：`Workflow.list_saved()` 返回 builtin + scope 字段

## 待做 (Phase 4)
- 前端 scope badge (builtin/project)
- Builtin 资源只读控制 (隐藏 Delete, 禁用 Save)
