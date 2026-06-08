# 基座加固 Review 报告 — Phase 5 候选工作清单

> 审查范围: harness/ + server/ + frontend/src/
> 审查维度: 软件设计原则、鲁棒性、可扩展性、代码整洁
> 输出: 优先级清单 + 解决方案

---

## 一、整体健康度

| 维度 | 评级 | 一句话总结 |
|------|------|-----------|
| 架构骨架 | B+ | Phase 2/4 重构后骨架清晰（scoped stores、event registry、priority bus）|
| 后端实现 | C | macro_graph 仍是 1,014 行 god-class；16 处静默吞异常 |
| 服务层 | C- | routes.py 2,166 行混合 6 域；auth 漏洞、无 DI |
| 前端组件 | C | 3 个超大文件（LlmProfileSettings 776 / BenchmarkCompare 712 / RunHistoryList 471）|
| 测试覆盖 | D | 前端 167 TS 文件只有 2 个测试文件（1.2% 文件覆盖）|

**核心问题**: 三个层面都有"还能跑"但违反 SRP 的巨型文件/类。功能正常但每加一个 feature 都在累积技术债。

---

## 二、Critical 发现（P0 — 阻塞生产化）

### Backend P0

**[B-P0-1] `macro_graph.py` node_func 闭包仍是 505 行的 god-function**
- 文件: `harness/engine/macro_graph.py:462-967`
- 问题: 单个嵌套函数处理 15+ 关注点（验证、构建、执行、重试、interrupt、emit、persist）
- Phase 4 只提取了 5 个纯函数（node_phases.py），但**主控制流仍是巨型闭包**
- 影响: 任何 LLM 执行相关 bug 都要在这个函数里调试；无法单测执行流程

**[B-P0-2] 16 处 `except Exception: pass` 静默吞异常**
- 文件: `harness/api.py:129`、`run_store.py:76`、`tools/mcp_bridge.py:167` 等 12 个文件
- 问题: 持久化失败、MCP 断连、增量保存失败全部静默
- 影响: 生产 bug 不可追踪；用户数据可能丢失但 UI 不知情

**[B-P0-3] `Workflow` 类 SRP 违反 — 一个类做 6 件事**
- 文件: `harness/api.py:160-560`
- 问题: `Workflow` 同时负责：定义、编译、执行、持久化、UI 启动、benchmark
- 影响: 任何工作流相关变更都要改这个核心类；测试需要全栈 mock

### Server P0

**[S-P0-1] `routes.py` 2,166 行混合 6 个业务域**
- 文件: `server/routes.py`
- 问题: auth / workflows / agents / tools / benchmarks / runs 全在一个文件
- 影响: 维护困难、合并冲突高发、无法独立测试某域

**[S-P0-2] Auth 漏洞 — 3 个端点零授权**
- 文件: `server/routes.py:235`（save_profile）、`473`（chart_render）、`server/ws_handler.py:588`（batch WS）
- 问题: 任意用户可修改 LLM profiles / 发伪 chart 事件 / 匿名连 batch WS
- 影响: 多用户环境下越权风险

**[S-P0-3] 输入校验绕过 — 5 端点 + WS 路径无 schema**
- 文件: `server/routes.py:74, 416, 600, 817, 851, 877` + `ws_handler.py:536-581`
- 问题: 直接 `request.json()` + `json.loads()`，无 Pydantic 验证
- 影响: 字段类型错误在 business logic 里炸，不是在入口

**[S-P0-4] RunStore 无抽象层 — 锁死文件存储**
- 问题: 30+ 处直接 `RunStore()` 实例化
- 影响: 换 PostgreSQL/Redis 要改 30+ 处；无接口契约

### Frontend P0

**[F-P0-1] `eventRouter.ts` race condition 自相矛盾**
- 文件: `frontend/src/contexts/workflow-context/eventRouter.ts:158-180`
- 问题: 注释说"快照 selectedRunId 消除竞态"，但 `dispatchBatchEvent` 在 line 180 又读了一次
- 影响: 用户快速切 workflow 时事件可能错投

**[F-P0-2] `WorkflowManager.cleanupTimer` 内存泄漏**
- 文件: `frontend/src/contexts/workflow-context/WorkflowManager.ts:246`
- 问题: `setInterval` 没在 `destroy()` 里 `clearInterval`
- 影响: 每销毁一个 workflow 泄漏一个 timer

**[F-P0-3] 三个超大组件违反 SRP**
- `LlmProfileSettings.tsx` 776 行（CRUD + 全局设置 + 3 tab UI）
- `BenchmarkCompare.tsx` 712 行（5 tab 全在一个文件）
- `RunHistoryList.tsx` 471 行（pagination + selection + live updates）

---

## 三、Important 发现（P1 — 应该修）

### Backend P1

- **[B-P1-1]** StopSignalManager 混用 async + sync lock，check-then-act 仍可竞态（`stop_signal.py:79,105`）— Phase 4 review fix 不彻底
- **[B-P1-2]** 10 个模块级全局可变状态（`_bus`、`_active_builders`、`_running_procs`、`_global_registry` 等）— 跨 workflow 污染、测试隔离差
- **[B-P1-3]** `Workflow.list_saved()` 3 段近似复制（shared/private/legacy DAG 构建，`api.py:376-456`）
- **[B-P1-4]** 工具注册硬编码 if-else（`macro_graph.py:162-167`）— 加工具要改核心
- **[B-P1-5]** 24+ 处 `Any` 类型（`event_bus: Any`、`resume_value: Any`、MCP `_session_cm: Any`）

### Server P1

- **[S-P1-1]** 4 个超长 handler 函数（`_create_and_start_workflow` 151 行 / `_handle_followup` 185 行 / `_enrich_benchmark_result` 110 行 / `run_benchmark` 107 行）
- **[S-P1-2]** 容量检查 TOCTOU（`routes.py:1098-1100` check 后 submit 前可被抢占）
- **[S-P1-3]** WS disconnect 不 cancel background forward task（`ws_handler.py:161-180`）
- **[S-P1-4]** 无 rate limiting / quota 钩子
- **[S-P1-5]** 无 dead-letter queue — 失败事件直接丢

### Frontend P1

- **[F-P1-1]** AbortController 未在 unmount 时清理（`RunHistoryList.tsx:266-268`）
- **[F-P1-2]** 全应用只有 root ErrorBoundary，子路由无隔离
- **[F-P1-3]** 7 个文件硬编码 timeout（3000ms toast / 5min cleanup / 30s poll 等）
- **[F-P1-4]** 3 种 store 访问模式混用（global / scoped / manual API），无文档
- **[F-P1-5]** 测试覆盖 1.2%（167 文件 vs 2 测试）— 重构无安全网

---

## 四、Minor 发现（P2 — 清理项）

- Dead code: `server/event_bus.py` 整个 deprecated shim、`bash.py:19` 未用 export
- 命名不一致: `_check_*` vs `get_*` 前缀混用
- 类型注释缺失: `list_runs()`、`_forward_events_filtered()` 无返回类型
- Magic numbers: `max_concurrent=50`、`if len(run_ids) > 100`、`2.0s` cancel grace
- 前端: `console.log` 残留、`as any` 散落、i18n 缺失

---

## 五、Top 10 推荐修复（按 ROI 排序）

| # | 修复项 | ROI | 工作量 | 风险 |
|---|--------|-----|--------|------|
| 1 | **拆分 routes.py 为 6 个 domain router** | 🔴 极高 | 2 天 | 低 |
| 2 | **抽取 `@require_auth` + 补 3 个 auth 漏洞端点** | 🔴 极高（安全）| 1 天 | 低 |
| 3 | **替换 16 处 `except: pass` → 显式 logging + re-raise** | 🔴 极高（可观测）| 1.5 天 | 低 |
| 4 | **拆 `LlmProfileSettings.tsx` 为 3 文件** | 🟠 高 | 1 天 | 低 |
| 5 | **拆 `BenchmarkCompare.tsx` 5 tab 为 5 文件** | 🟠 高 | 1 天 | 低 |
| 6 | **继续拆 `macro_graph.node_func` 闭包** | 🟠 高 | 3 天 | 中 |
| 7 | **RunStore 抽象层 + DI（FastAPI Depends）** | 🟠 高（可扩展）| 2 天 | 中 |
| 8 | **Pydantic schema 覆盖所有 raw request.json()** | 🟠 高 | 1 天 | 低 |
| 9 | **前端 constants.ts + cleanup hooks 巡检** | 🟡 中 | 0.5 天 | 低 |
| 10 | **前端测试基础设施（vitest 已就位 → 加组件测试）** | 🟡 中 | 持续 | 低 |

---

## 六、Phase 5 候选方案（三选一）

### 方案 A: "服务器现代化" — 聚焦 server/ 重构（推荐）

**目标**: 把 server/ 从 C- 拉到 B+
**任务清单**: Top 10 中的 #1, #2, #3, #7, #8 + S-P1-3（WS cleanup）+ S-P1-4（rate limiting）
**工作量**: 7-10 天
**收益**: 
- 安全漏洞修复（auth + validation）
- 可扩展性（DI + RunStore 抽象 → 可换 DB）
- 可观测性（无静默失败）
**风险**: 中 — routes.py 拆分会改大量 import

### 方案 B: "前端整洁化" — 聚焦组件 + 类型

**目标**: 把 frontend 从 C 拉到 B+
**任务清单**: Top 10 中的 #4, #5, #9, #10 + F-P0-1（eventRouter race）+ F-P0-2（timer leak）+ F-P1-2（ErrorBoundary）
**工作量**: 5-7 天
**收益**: 
- 维护性大幅提升（3 个 god component 拆开）
- 测试覆盖从 1.2% → 20%+
- 内存泄漏 + race 修复
**风险**: 低 — 纯拆分

### 方案 C: "macro_graph 终极拆分" — 后端核心攻坚

**目标**: 把 macro_graph.py 从 1,014 行降到 < 400 行
**任务清单**: Top 10 中的 #6 + B-P0-1（node_func 闭包拆分）+ B-P0-3（Workflow 类拆分）+ B-P1-1（lock 修正）+ B-P1-2（去全局状态）
**工作量**: 8-12 天
**收益**: 
- 后端核心可测试
- 全局状态去除后并发安全
- 但**收益偏底层**，用户感知不强
**风险**: 高 — macro_graph 是核心路径，闭包拆分容易引入回归

---

## 七、推荐顺序

**强烈推荐: 方案 A 优先（服务器现代化）**

理由:
1. **安全漏洞必须先堵** — auth + validation 是生产阻塞项
2. **DI 改造是其他方案的前置** — 没有 RunStore 抽象，方案 B/C 的可测试性提升都受限
3. **routes.py 拆分是最高 ROI** — 2 天工作量换来 60+ 端点的可维护性
4. **server 是其他层的地基** — backend/frontend 测试都需要 mock server 接口

执行顺序（建议 3 周完成）:
- Week 1: 安全（auth + validation + exception logging）
- Week 2: 拆分（routes.py → domain routers + DI 层）
- Week 3: RunStore 抽象 + WS cleanup + rate limiting

完成后再决定是否做方案 B 或 C。
