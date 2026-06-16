# NAS 实测发现 + Harness 架构问题

> 日期：2026-06-16
> 状态：分析定稿，待排期实施
> 来源：跑 NAS workflow（timeseries / cifar_cnn）后发现的问题
> 分支：`main`

## 背景

跑完 NAS workflow 后梳理出 5 个问题。判定原则遵循 `CLAUDE.md` 的 bug vs 架构问题分类：

- **Bug**：局部错误、状态丢失、边界未处理 → 最小化 surgical fix
- **架构问题**：跨模块耦合、抽象错位、职责越界、数据/事件流断裂 → 先写设计对齐再改

结论：5 个问题里 1 个 Bug、4 个架构问题（含 1 个 NAS 业务设计问题）。

---

## 第一部分：NAS Workflow 问题（业务设计层）

### 问题 1 — Latency 目标 HITL 缺失，"latency 已 OK 仍继续优化"无出口

**判定**：架构问题（缺失能力 + 与既有设计冲突）

#### 根因（三层叠加）

1. **目标来源全程不交互**：`make_budget.py:69` 接 `--target-latency`，由 scout 在 Step 4.2 透传 `<from workflow inputs>`。目标在 launch 时由 API/CLI 注入，整个 run 期间不可变。
2. **Validator 决策二元无宽放**：`check_target.py:71` `target_met = acc_constraint AND latency_constraint`（严格 AND）；`validator.md:58-65` `target_met=false && abort_recommended=false` → `decision="fail"` → `on_fail: selector` 继续死磕。唯一退出路径是 `abort_recommended=true`（fitness 停滞），不是"latency 够好了用户接受"。
3. **既有约束**：`scout.md:27` cycle 非交互；setup 可交互。

#### 修复方案 A（推荐）— setup 阶段捕获意图 + cycle 内 deterministic

**核心思路**：用户意图在 setup 一次性捕获（包含"接近达标如何处理"），cycle 内 `check_target.py` 按预先约定的策略自动判定，不再中断。

##### Setup 阶段（scout.md Step 2 baseline 跑完后）

扩展现有 baseline 对齐 ask_user（或升级为 LangGraph `interrupt()`），一次问清：

- **目标确认**：baseline latency = X ms（实测）/ target = Y ms（inputs）。是否调整？
- **宽放策略**（关键新增）：当最佳 strategy latency 接近但未达 target 时如何处理？
  - 严格：必须 ≤ target
  - 宽放 1.2x：≤ target * 1.2 + acc 达标 → 接受进 refine
  - 宽放 1.5x：≤ target * 1.5 + acc 达标 → 接受进 refine
  - abort：N 轮无 promising 自动停

把答案写入 `budget.json` 新字段：
```json
{
  "target_latency_ms": <final>,
  "latency_acceptance_ratio": 1.0 | 1.2 | 1.5,
  "no_progress_abort_iters": 3 | null
}
```

##### Cycle 阶段（check_target.py）

```python
ratio = budget.get("latency_acceptance_ratio", 1.0)
latency_constraint = bool(
    best_latency is not None and best_latency <= target_latency * ratio
)
```

扩展 `_detect_abort` 支持 `no_progress_abort_iters` 配置。

##### interrupt vs ask_user 选择

- **interrupt（LangGraph 原生）**：setup 阶段建议用，理由 —— 状态机级别的暂停，可持久化、可刷新重建；`workflow_runtime.py:130-134` 已检测 `__interrupt__`；与 LangGraph checkpointer 配合天然支持 resume；事件类型 `workflow.waiting_for_guidance` 已在 `bus.py:67` 预留（目前无 emit 调用方）。
- **ask_user**：工具层，依赖 LLM 在合适时机调用；ask_user 缺陷已修复（`af923ad` / `01b5c6d`），可用但不如 interrupt 可靠。

##### 落地路径

1. scout 节点 `interrupt({"kind": "baseline_alignment", "baseline": ..., "options": ...})`
2. ws_handler 监听 `__interrupt__` → emit `workflow.waiting_for_guidance`
3. 前端渲染选择 UI → POST `/api/workflows/{id}/resume` 带 resume_value
4. `workflow_runtime.py` 用 resume_value 重跑 scout，scout 把答案写入 budget.json

#### 评估

| 维度 | 评估 |
|---|---|
| 鲁棒性 | High — interrupt 是状态机原生，可持久化；cycle 完全 deterministic |
| 可扩展性 | High — 同一 interrupt 模式可用于 project_analyzer 的 partial 字段补全（替代 scout.md:78 的 ask_user 兜底） |
| 风险 | 中 — ws_handler 需新增 resume API；前端需新增 waiting_for_guidance 渲染；check_target.py 改动要兼容旧 budget.json（默认 ratio=1.0） |
| 工作量 | 1.5-2 天 |

---

### 问题 3 — Coder + Runner sub_agent 合并（用户提议）

**判定**：架构问题（DAG 重构 trade-off）

#### 用户原意

当前流程：
```
planner → K × coder sub_agent（写 diff）→ planner 收集 diff path
       → trainer 收集 diff + 自判 tier → K × runner sub_agent（跑 run_strategy.py）
```

提议合并为：
```
planner → K × coder_runner sub_agent（写 diff + 跑 run_strategy.py 一步到位）
```

#### 客观判断：部分场景合理，不应作默认

**合并的代价**：

| 当前解耦 | 合并后 |
|---|---|
| trainer 自判 tier（根据上轮 OOM / fitness 区分度动态调整） | tier 决策必须前移到 selector，否则 sub_agent 不知道用什么 tier |
| trainer 收集 K 个 strategy 后统一处理失败 | 失败处理下放到 sub_agent，K 个独立失败恢复路径 |
| diff 写失败 → planner 知道，不浪费训练资源 | diff 写失败 → sub_agent 可能瞎跑 training（git apply 失败时 run_strategy.py 报错，但 sub_agent 不一定能正确诊断） |

**适合合并**：短训练（< 2 分钟）/ 简单 diff（parametric）/ 不需要动态 tier。
**不适合合并**：长训练（CNN、Transformer）/ structural_global 类 / 需要根据上轮结果调整 tier。

#### 推荐方案 — 保留解耦默认，新增 `fast_mode` 配置

`workflow.json` 顶层加 `inputs.fast_mode`（默认 false）。selector 读 flag 决定走哪条路径：

- **fast_mode=false（当前）**：planner / trainer 分离，trainer 自判 tier。
- **fast_mode=true（新增）**：
  - selector 把 effective_tier 写入 `parent.json`（不让 trainer 自判）
  - planner issue 的 sub_agent task 内嵌"写 diff + 跑 run_strategy.py"，每个 sub_agent 一次完成
  - trainer 节点退化成 thin aggregator，甚至合并到 judger

#### 评估

| 维度 | 评估 |
|---|---|
| 鲁棒性 | Medium — fast_mode 下 sub_agent task 复杂度上升，单个 sub_agent 失败处理变难 |
| 可扩展性 | High — 用户按项目选模式；未来可加 "auto"（selector 根据上轮失败率自动选） |
| 风险 | 中 — 需改 planner.md / trainer.md / selector.md / workflow.json schema；fast_mode 下 Fitness 收敛行为变化需重新验证 |
| 工作量 | 2-3 天 |

**强不建议**直接把合并当默认。NAS 搜索空间大、失败率高，解耦的"trainer 自判 tier + 统一失败处理"是收敛关键保障。

#### 关联

替代了 trainer 加结构化文件工具（`read_text_file` / `read_json`）的方案 —— 那只是减少 bash 调用数（73 → 30），不解决根本的状态传递开销。合并方案才是结构性优化，但代价更高。

---

## 第二部分：Harness 架构问题（通用框架层）

### 问题 2 — HITL 机制盘点（澄清问题）

**结论**：框架**已经有 HITL 基础设施**，但业务层从未启用。

| 机制 | 现状 | 适用 |
|---|---|---|
| `ask_user` 工具 | 可用（缺陷已修复 `af923ad` / `01b5c6d`） | agent 主动问简单选择题 |
| **LangGraph `interrupt()`** | **完全支持但零调用方**。`workflow_runtime.py:130-134` 检测 `__interrupt__`，写入 `result.interrupted/interrupt_value` | NAS latency HITL 用这个 |
| Stop-and-Regenerate (`_check_interrupt`) | 已用，`llm_executor.py:460` 每 iter step 检查 | 用户主动打断生成（不是问问题） |
| `workflow.interrupted` 事件 | 定义在 `bus.py:66` CRITICAL_EVENT_TYPES，**无 emit 调用方** | interrupt 发生时通知前端 |
| `workflow.waiting_for_guidance` 事件 | 定义在 `bus.py:67`，**无 emit 调用方** | interrupt 等待用户回应时通知前端 |

**关键发现**：基础设施已就绪，缺的是 (1) agent MD 写明何时调 `interrupt()`，(2) ws_handler resume API，(3) 前端 waiting UI。问题 1 的方案 A 实施时顺带启用。

---

### 问题 4 — CRITICAL_EVENT_TYPES 错分类导致 buffer 单调增长

**判定**：架构问题（事件优先级错分类）

#### 根因

`bus.py:56-103` 的 `CRITICAL_EVENT_TYPES` 把过多事件标为 critical。按 `CLAUDE.md` 契约：

> 「下游错过这个事件，UI 会永久错误吗？」→ critical；「能被后续事件或刷新重建吗？」→ normal

当前分类问题：

| 事件 | 当前 | 应该 | 理由 |
|---|---|---|---|
| `workflow.started/completed/error/cancelled/resumed` | critical | **critical** ✓ | 错过 = UI 永久错误 |
| `node.started/completed/failed` | critical | **critical** ✓ | 错过 = DAG 状态错 |
| `chat.question/answer/timeout` | critical | **critical** ✓ | 错过 = ask_user 卡死 |
| `workflow.interrupted/waiting_for_guidance` | critical | **critical** ✓ | 错过 = HITL 永久阻塞 |
| `agent.failed_with_classified_reason` | critical | **critical** ✓ | 最终失败状态 |
| `agent.tool_call` / `agent.tool_result` | critical | **normal** ✗ | UI 可从 node.completed 重建 |
| `agent.tool_output_truncated` | critical | **normal** ✗ | 同上 |
| `bash.background_completed` | critical | **normal** ✗ | 后台任务完成通知 |
| `agent.retry_attempted` | critical | **normal** ✗ | retry 历史，可从最终失败推导 |
| `todo.created/updated/bulk_completed/replaced` | critical | **normal** ✗ | UI 可刷新重建 |
| `chart.render` | critical | **normal** ✗ | chart 数据在 run_store sidecar |
| `followup.started/completed/failed` | critical | **normal** ✗ | 临时对话 |

#### 副作用（你问的"会不会导致错误"）

**不会导致功能性错误**：
- 事件内容正确，没有数据错乱
- emit 是 fire-and-forget，不影响业务逻辑
- 警告明说 "appending anyway"，事件**没有被丢**

**会导致三类性能/体验退化**：
1. **进程内存单调增长**：trainer 73 bash → 73 tool_call + 73 tool_result = 146 critical 事件；一个完整 NAS run（10 iter × K=3 × 73 + 其他 agent）≈ 2500+ critical 事件 × 1-2KB = 数 MB 常驻；长跑 server 几小时不重启 → 几十 MB
2. **WS 重连/刷新 replay 风暴**：`bus.py:217-228` subscribe() 把所有 critical buffer 重放到新订阅者 → 每次刷新页面 / 新开 tab / WS 断线重连，后端推几千事件 → 体感 1-3 秒"卡住"
3. **设计脆弱性**：默认 `_subscriber_queue_size = 0`（unlimited），所以不触发 QueueFull；若运维配置了上限（如 1000），刷新时会丢事件，UI 状态不完整

详细机制讨论见本文档附录 A。

#### 修复方案 A（推荐）— 重分类 CRITICAL_EVENT_TYPES

```python
CRITICAL_EVENT_TYPES = frozenset({
    # 真正 critical：错过即永久错误
    "workflow.started", "workflow.completed", "workflow.error",
    "workflow.cancelled", "workflow.resumed",
    "workflow.interrupted", "workflow.waiting_for_guidance",
    "workflow.audit",
    "node.started", "node.completed", "node.failed",
    "chat.question", "chat.answer", "chat.timeout",
    "agent.failed_with_classified_reason",
})
# 其余全部默认 normal（FIFO 可淘汰）
```

#### 评估

| 维度 | 评估 |
|---|---|
| 鲁棒性 | High — normal 事件 FIFO 淘汰本来就是设计；agent_io sidecar（run_store）是事实来源 |
| 可扩展性 | High — 未来新事件默认 normal，不需要每个都加白名单 |
| 风险 | 中 — 前端如果完全依赖 WS replay 重建 UI（不查 sidecar），late subscriber 可能漏 tool 历史。**需先确认前端是否对 tool 历史 / chart / todo 有 sidecar 兜底** |
| 工作量 | 改 frozenset 30 分钟；前端 sidecar 兜底验证半天 |

#### 附录 A — 长期"刷新慢"机制详解

**当前数据流**（critical 全保留）：

```
事件 emit → critical buffer 持续累积（无上限）
                ↓
用户刷新 / 新订阅 → subscribe(since_seq=N)
                ↓
buffer 里 seq>N 的事件全部入 subscriber queue
                ↓
queue → 前端按 seq 顺序处理（store dispatch + React rerender）
```

每个事件触发：JSON parse → store dispatch → selector 重算 → React rerender。几千事件串行处理 = 几秒。

**方案 A 修复后数据流**：

```
事件 emit → critical buffer（只保留生命周期 + 失败）
                ↓
normal 事件 → FIFO buffer（_buffer_size=2000 上限，超了淘汰最老）
                ↓
用户刷新 / 新订阅 → subscribe(since_seq=N)
                ↓
critical 全 replay + normal 只 replay 最近 2000 个
                ↓
前端从 run_store sidecar 读取 tool 历史 / chart / todo（不依赖 buffer）
```

**能否从根本上解决**：**能**，前提是前端对 tool 历史 / chart / todo 的渲染查 run_store sidecar（HTTP `/api/workflows/{id}/events` 或 `agent_io`），不全靠 bus buffer。

如果前端某处只靠 buffer replay（不查 sidecar），方案 A 会让那处在长 run 后期看不到早期 tool 历史 —— 此时要么 (a) 前端补 sidecar 查询，要么 (b) 给特定 event 类型保留 critical 但加单独上限。

**验证步骤**（实施前必做）：
1. grep 前端代码，找出所有消费 `agent.tool_result` / `chart.render` / `todo.*` 的 reducer
2. 检查这些 reducer 的数据来源：纯 WS 事件 / sidecar API / 两者结合
3. 纯 WS 的需要补 sidecar 兜底；两者结合的可直接走方案 A

---

### 问题 5 — 历史切换到运行中 workflow 切不过去

**判定**：Bug（两个 view store 状态不同步）

#### 根因（精确定位）

项目里有**两个职责重叠的 view store**：

| Store | 文件 | 状态 |
|---|---|---|
| `useAppViewStore` | `frontend/src/stores/appView.ts` | `view: {kind:"run", runId}` + `runMode: "live"\|"replay-skeleton"\|"replay"` |
| `useViewStore` | `frontend/src/stores/viewStore.ts` | `activeView: {type:"live"\|"replay"\|"replay-skeleton", runId, run?}` |

`WorkflowCenterPanel.tsx:35-50` 的 `useActiveWorkflowId()` **优先读 useViewStore**：

```ts
if (isReplayView(activeView)) return getActiveRunId(activeView);  // ← 返回 history runId
if (activeBatchId) return selectedRunId;
return workflowId;
```

而 `activateRun.ts:85-100` 的 running 分支**只更新 useAppViewStore**，**没有调 useViewStore.showLive()**。

#### 切换流程时序（bug 触发路径）

1. 用户在历史 replay：`useViewStore.activeView = {type:"replay", runId: historyRunId}`，`useAppViewStore = {kind:"run", runId: historyRunId, runMode:"replay"}`
2. 用户点"切换到 running"：`activateRun(runningId)`
3. `useAppViewStore.view = {kind:"run", runId: runningId}`，`runMode` 经历 `replay-skeleton` → `live`
4. **`useViewStore.activeView` 仍然是 `{type:"replay", runId: historyRunId}`** ← BUG
5. `useActiveWorkflowId()` 优先读 useViewStore → 返回 historyRunId
6. page.tsx 用 `activeWorkflowId` 包 `<WorkflowScope workflowId={historyRunId}>`
7. 所有 scoped hooks（`useConversationMessages`、`useWorkflowStatus` 等）读 history 的 store
8. **更糟**：`WorkflowCenterPanel.tsx:63` 的 `useWorkflowWS(isLiveRun ? workflowId : null)` 用错误的 workflowId 连 WS —— running workflow 的事件**根本没被订阅**

#### 修复方案 A（推荐）— activateRun running 分支调 showLive

```diff
--- a/frontend/src/lib/activateRun.ts
+++ b/frontend/src/lib/activateRun.ts
@@ -82,6 +82,11 @@ export async function activateRun(runId: string): Promise<void> {

   if (full.status === "running") {
+    // 关键修复：清掉旧 replay 状态。如果不调，useViewStore.activeView
+    // 仍指向 history runId，useActiveWorkflowId() 会优先返回它，
+    // WorkflowScope 包错 workflowId，scoped stores 继续读 history。
+    // 见 WorkflowCenterPanel.tsx:35-50 useActiveWorkflowId 的优先级。
+    useViewStore.getState().showLive();
+
     useWorkflowStore.getState().setWorkflow(
       runId,
       full.workflow_name,
       full.dag ?? null,
     );
```

`showLive()` (`viewStore.ts:76-86`) 已经会：
- `resetAllStores(scoped.stores)` for the prior replay runId（清干净旧数据）
- `useOutlineStore.getState().reset()`
- `set({activeView: {type: "live"}})`

#### 评估

| 维度 | 评估 |
|---|---|
| 鲁棒性 | High — showLive 是既有 API，race-safe（_replaySeq 守护） |
| 可扩展性 | High — 任何 replay→live 切换路径都受益 |
| 风险 | 低 — 单行修改；最坏情况 history 的 store 被清，但 history 数据在 run_store sidecar 里，重新 activate 又能恢复 |
| 工作量 | 改 5 分钟 + 手测 30 分钟 |

#### 验证清单

1. 跑一个 NAS workflow（进入 cycle）
2. 切到历史中某个完成的 run → 看到 history 消息
3. 切回正在跑的 workflow → 中间 panel 立刻切换到 running workflow 的实时消息
4. WS 状态：ConnectionStatusBar 显示 connected
5. 检查 scoped store：`useWorkflowStatus()` 返回 runningId 的状态，不是 history 的

---

## 总览与优先级

| # | 问题 | 判定 | 优先级 | 工作量 |
|---|---|---|---|---|
| 5 | activateRun 加 showLive | Bug | **P0** | 半小时 |
| 4 | 重分类 CRITICAL_EVENT_TYPES | 架构问题 | **P1**（需先验证 sidecar 兜底） | 半天-1 天 |
| 1 | setup 阶段 latency HITL + cycle deterministic | 架构问题（NAS 业务设计） | **P1** | 1.5-2 天 |
| 2 | HITL 机制盘点 | 澄清问题 | 跟随 #1 启用 | — |
| 3 | coder + runner sub_agent 合并（fast_mode） | 架构问题（NAS DAG 重构） | **P2** | 2-3 天 |

### 跨问题架构观察

1. **Cycle 非交互是合理约束**。HITL 应该上提到 setup，把"接近达标如何处理"等意图在 setup 一次性捕获，cycle 内 deterministic 决策。
2. **事件分类需要复核机制**。CRITICAL_EVENT_TYPES 当初一次写死没有 review。建议加注释「每个 critical 必须有『错过即永久错误』的具体理由」，PR review 时强制 check。
3. **两个 view store 长期应合并**。`useAppViewStore` + `useViewStore` 职责重叠是 bug 5 的根因，类似 race 还可能在别处复现。本次只做 surgical fix（加 showLive），合并单独立项。

---

## 关联文档

- [NAS workflow 改进计划](./2026-06-13-nas-improvements.md) — 上一轮 NAS 设计讨论
- [Token 统计语义分离](./2026-06-16-token-stats-semantic-split.md) — 阶段 2 完成
- [工具与 Token 四阶段计划](./2026-06-16-tooling-token-phase-plan.md) — 阶段 3 待启动
- `docs/nas/nas-workflow-architecture.md` — NAS 架构总览
- memory: `nas-workflow-requirements.md` / `tooling-ask-user-defects.md` / `token-stats-vs-context-window.md`
