# 前端性能 Phase 2+3 ADR — Lazy Data + WS 订阅模型

> **For Claude:** 这是 ADR（架构决策文档），**不是 TDD 执行计划**。Phase 2+3 的实际执行计划在 evaluate Phase 0+1 之后再写。本文件的目的是锁定架构选择，便于未来执行时不重新讨论。

**Goal:** 彻底解决前端性能问题：(1) 刷新加载慢，(2) benchmark 多 workflow 并发卡死。通过 **lazy data**（后端按 step 索引持久化 + 按需返回 content）+ **WS 订阅模型**（按需推 streaming token）实现。

**Status:** Proposed —— 待 Phase 0+1 完成、evaluate 后再启动

**Estimated effort:** 1-2 周（5 个 major work blocks）

---

## Context

### 当前架构（已存在的问题）

```
[Agent 后端] ──broadcast 全部 token delta──→ [WS]
                                              │
                                              ▼
                                    [Frontend eventRouter]
                                              │
                                  所有 events 全部 route
                                              │
                                              ▼
                                  [conversationStore.messages]
                                    扁平大数组，所有内容
                                              │
                                              ▼
                                  [ScopedConversationTab]
                                    virtualizer 渲染
```

问题：
- 后端广播一切，前端接收一切、存储一切
- conversation 是扁平数组，刷新时整体 hydrate
- benchmark N 个并发 workflow 时，主线程被 N 路 token 流淹没

### Phase 0+1 修了什么、没修什么

**修了**（见 `docs/plans/2026-06-10-frontend-perf-phase0-1.md`）：
- streaming 渲染管线的 4 个反模式（virtualizer reflow、setVisibleCount 重置、textBatcher 全量拷贝、getNodeCollapsed 不稳定）
- TODO store 的 hydration 缺失 + 中断 step 永久转圈

**没修**：
- 刷新时整个 conversation 数组被全量 hydrate（meta + content 一起）
- benchmark 多 workflow 时所有 events 涌入主线程
- TODO step 内的 agent 输出仍然全量推到前端

**结论**：Phase 0+1 是止血，不动数据流模型。Phase 2+3 是真正的架构升级。

---

## Decision

### 决策 1：后端持久化分两层（meta + content）

**当前**：conversation 是扁平 JSON 数组，每条 message 包含所有字段（type / nodeId / stepId / content / thinking / toolArgs / toolResult / ...）。

**目标**：拆成两层：

| 层 | 字段 | 体积 | 默认是否返回 |
|----|------|------|--------------|
| **meta** | id, type, nodeId, stepId, toolName, status, timestamp | 几百字节/条 | ✅ 始终返回 |
| **content** | content, thinking, toolArgs, toolResult, toolStreamingOutput | KB-MB/条 | ❌ 按需返回 |

存储格式变更：从扁平数组改为按 `(nodeId, stepId)` 索引的结构。

### 决策 2：WS 协议加 subscribe_step / unsubscribe_step

**当前**：后端把所有 `agent.text.delta` / `agent.thinking.delta` / `tool.delta` 广播给所有连接。

**目标**：

| 事件类型 | 广播策略 |
|----------|----------|
| `todo.created` / `todo.updated` | ✅ 始终广播（小，所有客户端都需要） |
| `node.started` / `node.completed` / `node.failed` | ✅ 始终广播 |
| `workflow.*` / `chart.*` | ✅ 始终广播 |
| `agent.text.delta` / `agent.thinking.delta` | ❌ **仅推送给订阅了该 step 的客户端** |
| `tool.delta` | ❌ 同上 |
| `agent.step.progress`（新事件） | ✅ 始终广播（500ms 频次，只带 chars 计数，用于 budget bar） |

新 WS 消息（client → server）：

```json
{ "type": "subscribe_step", "workflow_id": "...", "node_id": "...", "step_id": "..." }
{ "type": "unsubscribe_step", "workflow_id": "...", "node_id": "...", "step_id": "..." }
```

后端维护 per-connection 订阅集合。当客户端订阅时：
1. 推送该 step 的 buffered content（一次性的"快照"）
2. 后续 delta 实时推送

当客户端取消订阅或断开连接时：停止推送。

### 决策 3：老 run 走 legacy 路径（只对新 run 生效）

- 老 run 的扁平持久化数据保留原样，不做迁移
- 老 run 渲染走"全量加载 + 不 lazy"的 legacy 路径（性能同今天）
- 新 run（启用新格式后）走 lazy 路径

理由：老 run 是历史归档，用户能接受慢。迁移成本不值得。

### 决策 4：完成 step 走 HTTP，进行中 step 走 WS

- **完成 step 的内容**：前端用 HTTP `GET /runs/{id}/steps/{nodeId}/{stepId}/messages` 一次性 fetch（静态数据，可缓存）
- **进行中 step 的内容**：前端 WS subscribe，先收 buffered snapshot，再收 live delta

两条路径在 UI 层对用户透明：点击展开都立即看到内容。

---

## 数据流（目标架构）

```
[Agent 后端]
    │
    ├─ step.meta events (always broadcast)
    │   → todo.created, todo.updated, node.*, workflow.*
    │   → [所有客户端收] (小)
    │
    ├─ step.progress events (new, broadcast)
    │   → agent.step.progress { chars, last_update_ts }  每 500ms
    │   → [所有客户端收] (小，用于 budget bar)
    │
    └─ step.content events (subscription-gated)
        │   → agent.text.delta, tool.delta
        │
        ▼
    [Subscription Manager (per-connection)]
        │
        ├─ Client A 订阅 step1 → 推 buffered + live delta
        ├─ Client B 没订阅      → 不推
        └─ Client C 订阅 step2 → 推 step2


[Frontend on user expand]
    │
    ├─ if step.status === "completed":
    │     HTTP GET /runs/{id}/steps/{nodeId}/{stepId}/messages
    │     → 一次性返回，渲染
    │
    └─ if step.status === "in_progress":
          WS send subscribe_step
          → 收 buffered snapshot (一次性)
          → 收 live delta (持续)
          → 用户 collapse 时 send unsubscribe_step
```

---

## Major Work Blocks

### Block 1: 后端持久化重构（2-3 天）

**目标**：conversation 持久化从扁平数组改为按 step 索引。

**关键改动**：
- `server/_helpers.py` 或 conversation 持久化路径：写时拆 meta/content 两层
- 现有 events 持久化保留（用于 replay fallback）
- meta 索引文件（小，便于 list 加载）+ content 分桶文件（按 step）

**TDD 执行计划**：待 evaluate 后单独写。

**风险**：
- 写放大（每个 delta 现在要写两次：events buffer + content bucket）—— 用 append-only log 缓解
- atomicity：meta 写成功但 content 失败时的恢复

### Block 2: 后端 API 拆分（1-2 天）

**目标**：API 支持按需返回 meta 或 content。

**新端点**：
- `GET /runs/{id}/conversation?meta=1` → 只返回 meta（小）
- `GET /runs/{id}/steps/{nodeId}/{stepId}/messages` → 返回单 step 内容
- 老 API `GET /runs/{id}/conversation`（无 query）→ 保留，老 run 用

**改动文件**：
- `server/routes/conversation.py`（或对应路由文件）
- `server/schemas.py`（response schema 拆 meta/content）

### Block 3: WS 订阅 Manager（2-3 天）

**目标**：后端 WS 协议加 subscribe/unsubscribe，按订阅推送。

**关键改动**：
- WS handler 加 subscribe_step / unsubscribe_step 消息类型
- 新增 `SubscriptionManager` class（per-connection 订阅集合 + 路由）
- `agent.text.delta` 等事件发送前查订阅集合
- 订阅时推送 buffered snapshot（从 Block 1 的 content bucket 读）

**风险**：
- WS reconnect 时的订阅恢复
- 多浏览器 tab 场景（每 tab 独立连接，独立订阅集合）
- 订阅"还没开始的 step"的边界情况（step 还没创建）

### Block 4: 前端 store 重构（2-3 天）

**目标**：conversation store 从扁平数组改为 step-indexed 树形。

**新结构**：

```ts
interface ConversationState {
  // 始终加载（小）
  stepMeta: Record<string, NodeMeta>;  // key = nodeId
  standaloneMessages: ConversationMessage[];  // user / system / question / 无 stepId

  // 按需加载（懒）
  stepContent: Record<string, ConversationMessage[]>;  // key = `${nodeId}::${stepId}`

  // 当前订阅的 step（最多 1-2 个）
  subscribedSteps: Set<string>;

  // actions...
}
```

**改动文件**：
- `frontend/src/contexts/workflow-context/stores/conversation.ts` —— 重写
- `frontend/src/lib/conversion/dtoToMessage.ts` —— 加 metaOnly 解析
- `frontend/src/stores/hydration/hydrateReplay.ts` —— 走 meta-only API

### Block 5: 前端 UI 重做（1-2 天）

**目标**：ScopedConversationTab 改成 step-based 渲染，展开时 lazy fetch/subscribe。

**改动文件**：
- `frontend/src/components/conversation/ScopedConversationTab.tsx` —— 重写
- `frontend/src/components/conversation/groupNodes.ts` —— 简化（默认就是 step 树）
- 新增 `frontend/src/hooks/useStepContent.ts` —— 管理 subscribe/fetch/cleanup

**关键行为**：
- 默认只渲染 stepMeta + standaloneMessages（极快）
- 用户展开 step：调用 `useStepContent(stepId)` → 内部判断 completed vs in_progress → fetch 或 subscribe
- 用户折叠 step：cleanup（unsubscribe 或丢弃 content）

---

## Migration Path

### Stage 1: Backend can serve both flat and indexed（Block 1+2 完成后）

后端能同时支持两种格式：
- 新 run：写入 indexed 格式，API 返回 meta-only 或 step-content
- 老 run：保留扁平格式，API 返回全量（legacy）

前端 unaware，继续走旧逻辑。

### Stage 2: Frontend new run uses indexed（Block 3+4+5 完成后）

前端 hydration 时检查 run 格式（`run._format_version` 或类似 flag）：
- 新格式 → meta-only API → lazy 加载 content
- 老格式 → legacy 全量加载

### Stage 3: Evaluation

跑 1-2 周后评估：
- 刷新速度是否达标（目标：1 万条 message 的 run < 1 秒可见）
- benchmark 多 workflow 是否流畅
- WS 订阅协议稳定性

如果达标 → Phase 4（UI 完全重做，删 legacy 路径）。如果不达标 → 调整。

---

## Risks

| 风险 | 严重度 | 缓解 |
|------|--------|------|
| WS reconnect 时订阅丢失 → 用户看不到 live stream | 中 | reconnect 后前端自动重新 subscribe 当前展开的 step |
| 订阅"还没开始的 step" → 后端 404 或 hang | 中 | 前端只允许订阅 `status === "in_progress"` 的 step；completed 走 HTTP |
| Block 1 持久化重构导致老 run 损坏 | 高 | Stage 1 完全不动老 run 数据；新格式独立路径 |
| WS 订阅协议破坏现有 benchmark 测试 | 中 | 后端保留 broadcast fallback flag（环境变量），CI 测试用旧路径 |
| meta/content 拆分后字段不一致（meta 说有 N 条但 content 少） | 中 | Block 1 写时保持 atomicity（同事务）；运行时 discrepancy 走 fallback |
| Step 展开 → fetch → 用户已经切走 → 浪费请求 | 低 | 前端用 AbortController；后端短路 |

---

## Open Questions（待 evaluate 时讨论）

1. **meta-only API 的 pagination**：1 万条 message 的 run，meta list 仍然不小（几百 KB）。要不要也分页？建议：先不做，几百 KB 在现代网络下可接受，分页增加复杂度。

2. **content bucket 的物理格式**：每条 message 一个 JSON 文件（可能 1 万个小文件），还是按 step 一个 JSON 数组？建议：按 step 一个 JSON 数组，每 step 通常 < 100 条 message。

3. **subscription 限制**：单连接最多订阅几个 step？建议：不限，但实际 UI 同一时刻用户能看的 step 不超过 1-2 个。

4. **老 run fallback 的退役时间**：什么时候可以删 legacy 路径？建议：6 个月后或新格式稳定 1 个月后，看哪个先到。

5. **是否需要在 Block 1 引入 events v2**：当前 events buffer 也有大小上限（CRITICAL_EVENT_TYPES 走独立 buffer），conversation events 是否要单独走 critical？建议：不用，meta 层始终全广播，不依赖 events buffer 的 critical 机制。

---

## References

- Phase 0+1 执行计划：`docs/plans/2026-06-10-frontend-perf-phase0-1.md`
- 架构讨论：本对话（2026-06-10）
- 相关代码：
  - `frontend/src/contexts/workflow-context/eventRouter.ts` —— 当前 broadcast 模型
  - `frontend/src/contexts/workflow-context/replayEvents.ts` —— 当前 hydration
  - `frontend/src/contexts/workflow-context/stores/conversation.ts` —— 当前扁平 store
  - `harness/extensions/bus.py` —— 后端 WS broadcast
  - `server/routes/` —— API 端点

---

## Decisions Locked

| 决策 | 选择 | 理由 |
|------|------|------|
| Streaming 机制 | WS 订阅模型 | 客户端过滤解决不了 benchmark 多 workflow 卡死 |
| 旧 run 处理 | 只对新 run 生效 | 老 run 是历史归档，迁移成本不值得 |
| 完成内容 delivery | HTTP fetch | 静态数据，可缓存，简单 |
| 进行中内容 delivery | WS subscribe | 实时性 + 不污染主线程 |
| Backend 持久化 | meta + content 分层 | 刷新只加载 meta，按需加载 content |

---

## Execution Trigger

本 ADR 不是执行计划。启动 Phase 2+3 的触发条件：

1. ✅ Phase 0+1 已合并并部署
2. ✅ 实际使用 1-2 周后，仍然觉得"刷新慢"或"benchmark 卡"（如果 Phase 0+1 已经够用，本 ADR 可以归档）
3. ✅ 用户主动说"启动 Phase 2+3"

满足以上三条后，按 Block 1-5 顺序写 TDD 执行计划，每个 Block 一个独立 PR。
