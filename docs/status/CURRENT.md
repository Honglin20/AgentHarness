# Current Task

**当前任务**: Phase 5 完成 — 基座加固阶段性收尾
**状态**: ✅ Phase 1-5 全部完成；多个 P2/P3 待办项累积待处理
**日期**: 2026-06-09

---

## Phase 进度总览

| Phase | 状态 | 核心成果 |
|-------|------|---------|
| 1 P0 紧急修复 | ✅ | 历史持久化 / 竞态 / WS 错误处理 |
| 2 前端根因架构 | ✅ | 5 大根因全解决（双轨 store / switch / 循环依赖 / god component）|
| 3 验证 + 隔离 + 性能 | ✅ | Zod / ErrorBoundary / memo / 内存清理 |
| 4 后端根因架构 | ✅ | 事件管线 / macro graph 拆分 / token 计费 |
| 5 Server 现代化 | ✅ | routes 拆分 / DI / auth / 校验 / 抽象层 |

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

- **pytest**: 511+ passed（3 个 pre-existing chart failures 不相关）
- **vitest**: 10/10 frontend 测试通过
- **npm run build**: ✅
- **tsc --noEmit**: ✅ 零错误

---

## ⚠️ 未完成任务清单

### 已发现的 Bug（来自 review）

#### [BUG-1] LlmProfileSettings 路由漏 `require_admin_dep`
- **位置**: `server/routers/profiles.py`
- **问题**: Phase 5 review fix 把 `require_admin_dep` 接到了 `users.py`，但其他 admin-only 端点（如 profile CRUD）的 `is_admin` 检查可能仍是内联的
- **影响**: 维护一致性问题（部分用 dep，部分内联）

#### [BUG-2] `_safe_path` 仍可能存在于其他位置
- **位置**: 待 grep 验证
- **问题**: Phase 5 review fix 修了 `runs.py:79,119`，但全仓可能还有其他 `_safe_path` 调用绕过 interface

### 性能/正确性 P2 项

#### [P2-1] WS schemas 不拒绝 extra fields
- **位置**: `server/schemas.py` WS 消息 schema
- **问题**: Pydantic v2 默认忽略额外字段，前端发送 `workflow_id` 在 `agent.stop_and_regenerate` 的 payload 里，但 schema 没声明 — 这是 latent drift

#### [P2-2] `chart_render` localhost bypass 在反代下变 auth 漏洞
- **位置**: `server/routers/tools.py:53-60`
- **状态**: 已加 SECURITY 注释，但需要部署文档同步

#### [P2-3] Phase 4 提到的 sub-agent 集成测试缺失
- **状态**: TokenAggregator 接好了 sub_agent.py，但没有集成测试验证 token 真的聚合到父 agent

### 测试覆盖缺口

#### [TEST-1] 前端组件测试覆盖率极低
- **现状**: 167 个 TS 文件，只有 2 个测试文件（`storeCache.test.ts` + `cacheRoundtrip.test.ts`）
- **目标**: 至少给 `LlmProfileSettings.tsx`、`BenchmarkCompare.tsx`、`RunHistoryList.tsx` 加组件测试

#### [TEST-2] WS handler TestClient 测试 hang
- **位置**: `tests/server/test_ws_handler.py` 5 个 TestClient 测试
- **问题**: 在当前环境 deadlock，需要 FastAPI lifespan + 不同测试 runner
- **影响**: WS 消息 schema 改动缺自动化回归

#### [TEST-3] E2E 真实 LLM 测试缺
- **状态**: Phase 3 计划 Task 11 提到，至今未做

### 已知 pre-existing 失败

| 测试 | 原因 |
|------|------|
| `test_chart.py::test_payload_structure` (×3) | 与本次工作无关，pre-existing |
| `test_runner_cancel.py` (×2) | RunStore work_dir 持久化问题，pre-existing |
| `test_routes_new_layout::test_put_agent_md_*` (×2) | Phase 5 Task 7 拆分时签名错配，待修 |

### 文档/清理

#### [DOC-1] Phase 3 计划文件丢了
- **状态**: `.claude/plans/elegant-sprouting-rivest.md` 已不在 tree 中
- **影响**: Phase 3 历史记录断裂

#### [DOC-2] frontend/out build artifacts 待重生
- **状态**: 子 agent 误操作回退了 4 个 build 产物
- **影响**: 不影响功能，但部署前必须 `npm run build` 重生

### Phase 5 review 后续

#### [REV-1] `_helpers.get_event_bus` 删除后的连锁清理
- **状态**: 已删 shim，但 ws_handler.py 的 `_new_bus` import 还是从 _helpers 来，需 verify 路径合理

#### [REV-2] require_admin_dep 在 workflows.py 的"owner-or-admin"检查未迁移
- **状态**: review fix 报告说这是正确行为（非纯 admin gate），但应在 `_helpers.py` 提取 `require_owner_or_admin_dep` 让模式统一

---

## 未实现的 Phase 候选

| 候选 | 描述 | 优先级 |
|------|------|--------|
| Phase 6A | 前端大组件拆分（LlmProfileSettings 776 / BenchmarkCompare 712 / RunHistoryList 471 行） | 中 |
| Phase 6B | macro_graph 终极拆分（1,019 → < 400 行）+ Workflow 类拆分 | 中 |
| Phase 6C | 后端生产化（工具调用重试 / interrupt 持久化 / dead-letter queue） | 中 |
| NAS | TODO/Task/parallel_tasks/代码隔离/Orchestrator 5 个 feature | 高 |

## 必读文件

- `docs/plans/2026-06-08-foundation-hardening-review.md` — 全面 review 报告
- `docs/plans/2026-06-08-phase5-server-modernization.md` — Phase 5 实施计划
- `docs/plans/2026-06-07-phase4-root-cause-architecture.md` — Phase 4 计划
- `docs/plans/2026-06-08-frontend-cache-dedup-token-display.md` — Phase 4 bonus tasks
- `docs/nas/` — NAS 工作流设计文档（5 个 feature 路线图）
