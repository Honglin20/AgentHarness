# Current Task

**当前任务**: 隔离加固完成 — 进入性能 / UX 阶段
**状态**: ✅ Phase 1-5 + 6B + 归类 + 隔离修复；性能/UX 优化待启动；NAS 最后
**日期**: 2026-06-09（隔离修复批）

---

## Phase 进度总览

| Phase | 状态 | 核心成果 |
|-------|------|---------|
| 1 P0 紧急修复 | ✅ | 历史持久化 / 竞态 / WS 错误处理 |
| 2 前端根因架构 | ✅ | 5 大根因全解决（双轨 store / switch / 循环依赖 / god component）|
| 3 验证 + 隔离 + 性能 | ✅ | Zod / ErrorBoundary / memo / 内存清理 |
| 4 后端根因架构 | ✅ | 事件管线 / macro graph 拆分 / token 计费 |
| 5 Server 现代化 | ✅ | routes 拆分 / DI / auth / 校验 / 抽象层 |
| 6B God files 拆分 | ✅ | macro_graph.py 1019→30 shim / api.py 967→41 shim |
| 7 harness/ 归类 | ✅ | 16 文件 → core/persistence/users/benchmark 4 子包 |
| 隔离加固 | ✅ | 5 个 leak 修复（chart fallback / todo store reset / payload wid） |

## 本会话累积的 45 个 commits

```
docs: plan + NAS design docs
feat: TODO tool — agent-driven step planning + reminder tracker
fix: commit orphaned node_phases.py
[Phase 5 review fixes — 9 commits]
[Phase 5 implementation — 13 commits]
[Phase 4 review fixes — 12 commits]
[Phase 4 implementation — 9 commits]
[Phase 3 leftover]
```

## 验证状态

- **pytest**: 659 passed / 4 failed（4 个 pre-existing failures，与本次工作无关）
- **vitest**: 10/10 frontend 测试通过
- **npm run build**: ✅
- **tsc --noEmit**: ✅ 零错误

### 本批修复（2026-06-09 基线）

- ✅ `test_runner_cancel.py` ×2 — 反映 Phase 4 sidecar 持久化新约定（events 走 sidecar / work_dir 始终设 key）
- ✅ `test_routes_new_layout::test_put_agent_md_*` ×2 — 反映 Phase 5 路由签名（`body` 改显式参数）
- ✅ `test_ws_handler::test_ws_*` ×2 — 修了 `_rebuild_bus_from_events` 仍读旧 inline events 的产品 bug + TestClient hang（lifespan MCP subprocess 清理卡 anyio task group，加 `HARNESS_SKIP_MCP` env 隔离测试）
- ✅ frontend build type 错误 ×2 — `WorkflowStores` 类型缺 `todo` 字段（commit ec1d0af TODO tool 集成遗漏）；`RunHistoryList` 用已重命名的 `initialLoading`/`refreshing`
- ✅ DOC-2 frontend/out build artifacts 重生

---

## ⚠️ 未完成任务清单

### 已发现的 Bug（来自 review）

> 2026-06-09: BUG-1（auth 相关）已主动放弃，专注功能完整性。

#### [BUG-2 已关闭] `_safe_path` 全仓已无残留
- **状态**: 实地 grep 确认 `server/` 0 个外部 `store._safe_path` 调用；`harness/run_store.py` 内部用法是私有方法本身，符合封装。

### 功能/正确性待办

#### [P2-1] WS schemas 不拒绝 extra fields
- **位置**: `server/schemas.py` WS 消息 schema
- **问题**: Pydantic v2 默认忽略额外字段，前端发送 `workflow_id` 在 `agent.stop_and_regenerate` 的 payload 里，但 schema 没声明 — latent drift

#### [P2-3] Phase 4 提到的 sub-agent 集成测试缺失
- **状态**: TokenAggregator 接好了 sub_agent.py，但没有集成测试验证 token 真的聚合到父 agent

### 测试覆盖缺口

#### [TEST-1] 前端组件测试覆盖率极低
- **现状**: 167 个 TS 文件，只有 2 个测试文件（`storeCache.test.ts` + `cacheRoundtrip.test.ts`）
- **目标**: 至少给 `LlmProfileSettings.tsx`、`BenchmarkCompare.tsx`、`RunHistoryList.tsx` 加组件测试

#### [TEST-2 已解决] WS handler TestClient 测试 hang
- **状态**: 加 `HARNESS_SKIP_MCP=1` 测试环境隔离 MCP subprocess + lifespan cleanup 5s 超时兜底；14 个 WS 测试全过
- **根因**: anyio cancel scope + MCP stdio subprocess cleanup 在 TestClient teardown 路径死锁

#### [TEST-3] E2E 真实 LLM 测试缺
- **状态**: Phase 3 计划 Task 11 提到，至今未做

### 已知 pre-existing 失败（本批未处理）

| 测试 | 原因 |
|------|------|
| `test_chart.py::test_payload_structure` (×3) | 与本次工作无关 |
| `test_phase2_integration::test_workflow_run_with_tools_mocked` (×1) | mock 没拦截 pydantic_ai.Agent.run，实际打 OpenAI API 返回 400；CURRENT.md 此前漏标 |

### 文档/清理

#### [DOC-1] Phase 3 计划文件丢了
- **状态**: `.claude/plans/elegant-sprouting-rivest.md` 已不在 tree 中
- **影响**: Phase 3 历史记录断裂

#### [DOC-2 已关闭] frontend/out build artifacts 已重生
- **状态**: 实际是 frontend 类型错误导致 build 失败，本批修复类型 + 重生

### Phase 5 review 后续

#### [REV-1] `_helpers.get_event_bus` 删除后的连锁清理
- **状态**: 已删 shim，但 ws_handler.py 的 `_new_bus` import 还是从 _helpers 来，需 verify 路径合理

#### [REV-2 已关闭] require_admin_dep owner-or-admin 抽象（auth 相关，本批不做）

---

## 未实现的 Phase 候选

| 候选 | 描述 | 优先级 |
|------|------|--------|
| 性能/UX | WS 流式渲染 / 长 conversation 虚拟化 / API 响应优化 / 首屏拆分 | 高 |
| Phase 6A | 前端大组件拆分（LlmProfileSettings 777 / BenchmarkCompare 712 / RunHistoryList 471 行） | 中 |
| Phase 6B 进一步 | 拆 `node_factory.make_node_func` 652 行闭包（Phase 7 候选） | 低 |
| Phase 6C | 后端生产化（工具调用重试 / interrupt 持久化 / dead-letter queue） | 中 |
| NAS | TODO/Task/parallel_tasks/代码隔离/Orchestrator 5 个 feature（TODO 已完成） | 低（最后做） |

## 必读文件

- `docs/plans/2026-06-08-foundation-hardening-review.md` — 全面 review 报告
- `docs/plans/2026-06-08-phase5-server-modernization.md` — Phase 5 实施计划
- `docs/plans/2026-06-07-phase4-root-cause-architecture.md` — Phase 4 计划
- `docs/plans/2026-06-08-frontend-cache-dedup-token-display.md` — Phase 4 bonus tasks
- `docs/nas/` — NAS 工作流设计文档（5 个 feature 路线图）
