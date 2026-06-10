# 前端显示混乱根因报告 + 改进方案

> 2026-06-10 · 不修 bug，只定位根因（架构 vs bug）· 含鲁棒性/可扩展性/风险/设计原则评估

## 1. 执行摘要

定性结论：**绝大多数是架构问题，不是局部 bug**。问题集中在三处契约缺失 + 一处职责越界：

- **后端 agent 完成判定漏了一个 gate**（缺 step 完成验证）→ 所有 step 跳步/提前结束现象的源头
- **TODO 工具职责不完整**（无 replace/批量收尾）→ 用户期望的"动态更新步骤"硬性不可达
- **前端 hydration 用 replay-then-live 而非快照**，叠加多个同步 O(N) 全量遍历 → 10s 加载 + 刷新后状态不一致
- **ask_user 卡片 UX 越界**：组件默认折叠，调用处未传 collapsed，把"已回答的交互"当成"已经不重要"

CLAUDE.md 明确写了"修复需要改动 ≥3 个不相关文件 = 架构问题"——本次要修的文件 ≥ 8 个，属于**典型架构问题**，禁止打补丁绕过。

---

## 2. 根因矩阵（已交叉验证，全部带 file:line）

| # | 根因 | 位置 | 类别 | 严重度 |
|---|------|------|------|--------|
| **R1** | 后端 agent 完成判定**没有 step 完成检查**。output schema validation (462-476) + envelope check (553-584) 通过就直接 `safe_emit("node.completed", ...)` (598)，TODO step 状态从未被读取 | `harness/engine/node_factory.py:456-603` | 架构（缺 gate） | **致命** |
| **R2** | TODO 工具只支持 `op: Literal["create","update","list"]`，`create` 走 `state.steps.extend(new_steps)` (130) **只追加不替换**；缺少"批量收尾"语义 | `harness/tools/todo.py:99-146` | 功能缺失 | **高** |
| **R3** | 前端 hydration `loadRunFromPersistedData` 用 3 个同步 `for (const event of events)` 全量遍历 (274-289, 364-389) + 同步 `computeRunSummary` (440-443) 阻塞主线程 | `frontend/src/contexts/workflow-context/replayEvents.ts` | 性能/架构 | **高** |
| **R4** | 切换 run 时**全量 `resetAllStores` + 8 个 store 全量 setState**，无 diff/patch | `replayEvents.ts:232-445` | 架构 | 高 |
| **R5** | 每次 WS subscribe 都全量推送 buffer (sort + N 次 put_nowait)，buffer_size=2000 的 completed run 一上线就吃 2k events JSON | `harness/extensions/bus.py:209-228` | 架构（重复劳动） | 中 |
| **R6** | `node.completed` 事件 handler 有冗余 `addAgentMessage`：找不到 streaming 消息时**再次创建 agent message** (57) → 多 NodeBlock 重复 | `frontend/src/contexts/workflow-context/routing/nodeHandlers.ts:56-72` | bug/架构 | 中 |
| **R7** | `AgentQuestionCard` 默认 `collapsed="auto"`，`isCompact = collapsed==="auto" && !isPending` (107)，**非 pending 自动折叠成一行**；`ScopedConversationTab` 调用处未传 collapsed prop → 继承默认 → ask_user 被隐藏 | `AgentQuestionCard.tsx:107` + `ScopedConversationTab.tsx:286` | UX 越界（架构） | 高 |
| **R8** | step 展开状态 `stepExpanded` 是**组件 local state** (`useState<Record<string,boolean>>`)，刷新/切换 agent 后丢失 | `ScopedConversationTab.tsx:591` | 架构（缺持久化） | 中 |
| **R9** | `currentStepIdByNode` 在 step status=completed 时**不清理** (todoHandlers.ts:42-48)，导致最后一段 agent 输出仍带旧 stepId，step 边界串台 | `frontend/src/contexts/workflow-context/routing/todoHandlers.ts:42-48` | bug | 低 |
| **R10** | 已应用的补丁 `forceTerminalSteps` (commit 2d0cbd9) 和 hydration section 7.5 (commit 4be7da2) 都是**症状治疗**：把"还停在 in_progress 的 step"强制 terminal，但没解决 R1（为什么 step 会停在 in_progress） | `frontend/src/contexts/workflow-context/stores/todo.ts:98-115` + `replayEvents.ts:352-405` | 技术债 | 中 |

---

## 3. 用户六大 bug → 根因映射

| 用户报告 | 对应根因 |
|----------|----------|
| ① step 没做完就跳到下一个 agent | **R1**（核心），R10 让它"看起来"修了但没修 |
| ① 刷新后状态不一致/不顺畅 | **R3 + R4 + R10**（hydration 是 replay 重建，依赖事件完整性，而 R1 导致事件不完整） |
| ② 刷新后 10s loading | **R3 + R4 + R5**（同步全量遍历 + 全量 setState + 后端 WS replay） |
| ③ 显示多个 analyzer 重复 | **R6**（双重 addAgentMessage）+ 可能 nodeId 重复触发 |
| ③ "Load 4 earlier messages (↑ 4 hidden)" | `ScopedConversationTab.tsx:686` 分页机制（VISIBLE_WINDOW=50），但 3 个 agent 产生 >50 条 message 是正常的——**真正的问题是 R6 导致的 message 数量虚高** |
| ④ ask_user 被隐藏 | **R7**（明确） |
| ⑤ 已完成 step 看不到细节 | **R8**（展开状态丢失）+ step 详情本身已持久化，但 UI 不持久化展开记忆 |
| 期望"动态更新后续步骤" | **R2**（功能缺失，硬性不可达） |
| 期望"step 可点击展开+可返回追溯" | 数据已具备（messages 数组含所有 tool_call/question/text），缺 **R8 + UI 导航** |

---

## 4. 违反 CLAUDE.md 契约检查

| 契约 | 违反点 |
|------|--------|
| "Fail loud" | R1 的静默跳步——agent 没做完也"成功"结束，无任何告警 |
| "事件/数据流断裂 = 架构问题" | R1+R10：后端事件不完整，前端用 forceTerminal 补 |
| "可扩展：新能力通过新增而非修改核心路径" | R2：要支持动态 step 必须改 TODO 工具核心 op 类型 |
| "性能：默认无 N+1、无全量重渲、无重复请求" | R3+R4+R5：每次切换 run 全量遍历 + 全量 setState + 后端全量 replay |
| "易定位：失败能追溯到一个明确的层" | R6：nodeHandler 在 node.completed 中创建 message 是路由层混入渲染职责 |
| "扩展系统职责分界" | R6：eventRouter 应只负责路由，但 nodeHandler 里在写 conversation store 的内容（addAgentMessage + 改 content）|
| "Priority 契约（CRITICAL_EVENT_TYPES）" | todo.created/updated 已是 critical（不丢事件），但 R1 是"事件根本没发"——契约管不到 |

---

## 5. 改进方案（分三阶段）

### 阶段 A：解决"step 必须做完才能 next agent" + 动态更新步骤（修 R1 + R2）

**A1. 后端加 step completion gate**（`harness/engine/node_factory.py`，在 envelope check 之后、`safe_emit("node.completed")` 之前）

判定逻辑：
- 读 `deps._todo_state`
- 如果 `has_plan == False` → emit `node.failed` (error_type="NoTodoPlan")（用户明确："未来每个 agent 都有 TODO"）
- 如果存在 non-terminal step (status ∈ {pending, in_progress}) → emit `node.failed` (error_type="UnfinishedSteps")

**A2. TODO 工具扩展 op**（`harness/tools/todo.py`）

- `op="complete_remaining"`：把所有 non-terminal step 批量置为 `status`（completed/skipped），可选 `reason`
- `op="replace"`：清空 step 列表，用新 items 重建（用于 LLM 重新规划）

详细设计见 TODO 优化章节。

### 阶段 B：解决"刷新慢 + 状态不一致"（修 R3 + R4 + R5）

**B1. 后端持久化 snapshot，前端优先读 snapshot 而非 replay**
- 后端：`_save_incremental` 同时写每个 store 的 `state_snapshot.json`
- 前端：`loadRunFromPersistedData` 改为 snapshot-first → setState snapshot（O(1)）→ 只 replay 增量事件
- WS buffer replay 也改 `since_seq`（已有参数）

**B2. computeRunSummary 移到 worker thread 或 lazy**
用 `requestIdleCallback` 或 Web Worker 异步算。

### 阶段 C：解决"ask_user 隐藏 + step 不可追溯"（修 R6 + R7 + R8）

**C1. ask_user 默认展开**（`ScopedConversationTab.tsx:286`）显式传 `collapsed={false}`

**C2. step 展开状态持久化到 URL 或 sessionStorage**（`ScopedConversationTab.tsx:591`）

**C3. 删除 nodeHandler 中的冗余 addAgentMessage**（`nodeHandlers.ts:56-72`），改为 fail loud

**C4. currentStepIdByNode 清理**（`todoHandlers.ts:42-48`）

---

## 6. 方案评估

### 6.1 鲁棒性评估

| 方案 | 边界场景 | 失败处理 |
|------|---------|---------|
| A1 step gate | 未用 TODO 工具的 agent / 用户主动允许部分 / LLM 跳步意图 | 用户场景统一为"每个 agent 必有 TODO"，gate 直接 hard fail；逃逸通过 `complete_remaining` 而非配置开关 |
| A2 op=complete_remaining | 当前 in_progress 步骤的处理 | 一并置为指定 status；event critical 不丢 |
| A2 op=replace | 替换时 token 已花 | emit `todo.replaced` critical，前端按 node_id 全量替换；step id 重生成 |
| B1 snapshot | snapshot 写失败 / snapshot 与 events 不一致 | fallback 全量 replay（保留现有逻辑兜底）；snapshot 加 checksum |
| B2 lazy summary | summary 算完前用户切换 run | AbortController 取消 |
| C1 默认展开 | 大量 ask_user 历史 | 用户可手动 collapse；列表虚拟化已有 |
| C3 删除冗余 addAgentMessage | node.started 真的丢失（WS 重连） | fail loud → 触发 WS 重订阅 |

### 6.2 可扩展性评估

| 维度 | 评估 |
|------|------|
| **OCP** | A2 通过新增 op 而非改 create 分支 ✓；B1 snapshot 加新 store 字段是纯新增 ✓；C3 fail loud 是替换逻辑而非打补丁 ✓ |
| **职责单一** | A1 gate 放在 node_factory 是正确的层；C3 把"路由"和"创建"分离 ✓ |
| **未来场景** | NAS 迭代搜索（多轮 agent 重规划）→ A2 是前置依赖；多 agent 并行 → B1 snapshot 是基础 |
| **配置化** | A1 不再引入 `allow_partial_steps` 配置——用户明确"每个 agent 必有 TODO"，hard gate 即可 |

### 6.3 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| A1 step gate 误伤现有正常 agent | 低 | 中 | 用户明确"未来每个 agent 都有 TODO"，不接受 warn-only，直接 hard gate |
| A1 改动 LangGraph 状态机返回路径，影响 retry/conditional edges | 中 | 高 | gate 失败走 `node.failed` 与现有失败路径一致 |
| B1 snapshot 文件与 events 不一致（崩溃）| 中 | 高 | fallback 全量 replay（已有代码）+ snapshot checksum 校验 |
| B1 改动持久化格式，老 run 数据需要迁移 | 高 | 中 | 用户明确"不需要适配旧 run"，旧 run 直接 fail loud 提示重新跑 |
| C1 ask_user 默认展开会让长 conversation 变长 | 低 | 低 | 已有虚拟化 + 用户可手动 collapse |
| C3 删除冗余 addAgentMessage 后，WS 重连场景首条消息可能丢 | 中 | 中 | fail loud → 触发重订阅 + 后端 R5 snapshot 推送会补齐 |

### 6.4 软件设计原则评估

| 原则 | 当前 | 方案后 |
|------|------|--------|
| **SRP** | R6：nodeHandler 既路由又创建消息 | ✓ 路由只路由，fail loud 由专门层处理 |
| **OCP** | R2：加 step 必须改 create | ✓ 新增 op="replace" / "complete_remaining" |
| **ISP** | R7：AgentQuestionCard 一个组件承担两种渲染模式 | 建议拆 Compact/Full 或调用方显式选择 |
| **DIP** | R1：node_factory 直接读 `deps._todo_state` | 可抽象 `StepCompletionChecker` 接口（可选优化） |
| **Fail loud** | R1+R6+R10：全静默 | ✓ 全部改 emit error / 显式失败 |
| **YAGNI** | — | 不做 step 依赖/嵌套/优先级（顺序隐含），不做旧 run 兼容 |
| **Surfaces conflicts** | R10：forceTerminal 既允许提前结束又假装完成 | ✓ A1 明确"未完成 = 失败"，不模糊 |

---

## 7. 推荐执行顺序

| 优先级 | 任务 | 验证方式 | 影响范围 |
|--------|------|---------|--------|
| **P0** | A1 step gate (hard) + A2 op 扩展 | 跑 benchmark workflow，gate 不挡合法流程 | node_factory + todo.py + todoHandlers + todoStore |
| **P0** | C1 ask_user 默认展开 + C3 删除冗余 addAgentMessage | 手动跑包含 ask_user 的 multi-agent run | AgentQuestionCard + nodeHandlers + ScopedConversationTab |
| **P1** | C2 stepExpanded 持久化 + C4 currentStepIdByNode 清理 + R9 fix | 手动验证刷新后展开状态保留 | ScopedConversationTab + todoHandlers |
| **P1** | B1 snapshot-first hydration | 测：刷新 5k events 的 completed run，loading 从 10s → <1s | run_store 后端 + replayEvents 前端 |
| **P2** | 删除 R10 forceTerminalSteps 补丁（A1 上线后不再需要） | 确认 A1 hard gate 下不存在"in_progress 但 workflow 结束"场景 | todo.ts |

---

## 8. 一句话结论

**这不是 UI bug 的集合，是"agent 完成判定契约缺失"（R1）+ "持久化用 replay 代替 snapshot"（R3+R4+R5）两个架构缺陷的级联表现**。所有补丁（forceTerminal、hydration section）都是在修症状而非根因——这就是为什么"修了还是慢、还是不一致"。建议从 A1（step gate）和 B1（snapshot-first）两条主线切入，其他都是衍生。
