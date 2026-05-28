# Current Task

**当前任务**: Benchmark 修复 + 用户隔离
**状态**: completed
**优先级**: P0

---

## 完成内容

### 后端（4 commits）
1. `harness/benchmark_store.py` — save_benchmark/list_benchmarks/list_results 新增 user_id 参数
2. `server/routes.py` — 8 个 benchmark 端点全部加 get_current_user + ownership check
3. `tests/test_benchmark_isolation.py` — 5 个测试覆盖用户隔离场景
4. `server/routes.py` — batch metadata 存储 user_id，修复 ownership check

### 前端（3 commits）
1. `BenchmarkRunner.tsx` — 去掉全局 store，改用 WorkflowManager + fetchWithAuth
2. `Sidebar/BenchmarkCompare/ScopedCenterPanel` — 全部 fetch → fetchWithAuth
3. `useWorkflowEvents.ts` — 清理 legacy batch code，setActiveWorkflowId 标记 @deprecated

### 验证
- 220 backend tests pass
- TypeScript 编译无错误
- Frontend build 成功

## Commits (0a63c28..9173fda)
```
9173fda build: deploy frontend with batch metadata fix
8733ae0 fix(benchmark): store user_id in batch metadata + fix workflow definitions auth
58a09f8 build: deploy frontend with benchmark isolation support
ab3998e fix(benchmark): add auth headers and clean up legacy batch code
eed3e12 fix(benchmark): rewrite BenchmarkRunner to use scoped stores
4ec60a3 test(benchmark): add user isolation tests for BenchmarkStore
cb541e8 feat(benchmark): enforce user isolation on all API endpoints
e77aa77 feat(benchmark): add user_id to BenchmarkStore for isolation
```
