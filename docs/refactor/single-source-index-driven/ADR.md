# ADR: 单一数据源 + Index-Driven 前端重构

> 日期: 2026-06-17
> 状态: Proposed — 待用户对齐（R3/O1/R1 已讨论定稿，待最终 sign-off）
> 替代/收敛: [`2026-06-16-long-run-replay-architecture.md`](./2026-06-16-long-run-replay-architecture.md) 的 Phase 2-4（那份的目标态保留，本 ADR 收敛实现层冗余通道）
> 关联诊断: [`docs/status/2026-05-27-frontend-data-flow-issues.md`](../status/2026-05-27-frontend-data-flow-issues.md) 技术债务 1-4（三周前已识别但未根治）

---

## TL;DR

NAS 前端"修了 N 次还在坏"的根因不是缺哪个字段，而是**同一份事实被 5 个地方独立计算**，每层契约都是隐式的。本 ADR 决定：

1. `iter_index.json` 是 iter 元数据的**唯一来源**。
2. `{run_id}+iters+{node}+{iter}.json` 是 iter 内容的**唯一来源**（且必须包含 `tool_calls` + `todo_steps`）。
3. **sidecar 在整个生命周期都是 source of truth** — streaming 期间 debounced flush（500ms），完成时 finalize。刷新零丢失，通过 `last_seq` 同步点接续 WS。
4. `snapshot.json` 退化为**manifest**（不含 conversation / agent_io / todo_states）。
5. `run_record.json` 不再持久化 conversation（旧字段保留只读兼容）。
6. 前端永远 fetch，**never filter**。Outline 是 iter_index 的纯投影。
7. E2E 测试是合并门槛 — 不能切所有 iter 的 run 不算重构完成。

---

## 背景

三周前 [`2026-05-27-frontend-data-flow-issues.md`](../status/2026-05-27-frontend-data-flow-issues.md) 已经识别出技术债务：两套事件路由、两套组件、全局/scoped store 混用、无 E2E 测试。之后多次修复都在加新通道或微调一层，没有收敛数据源。

最新一轮（[`2026-06-17-conversation-latest-iter-fix.md`](../releases/2026-06-17-conversation-latest-iter-fix.md)）解决了"snapshot tail-50 切片"，但**没动 outline 从 events 重新算 iter_count 这条路径**，导致用户感知问题依旧。

## 问题量化（从磁盘文件实测）

跑过的 NAS run（`5c6eac84`）：

| 文件 | 实测 | 应有 |
|---|---|---|
| `+iter_index.json` | scout=[1,2,3], selector=[1..6], planner=[1..6]（正确） | — |
| `+outline.json` | **所有节点 iter_count=1** | scout=3, selector=6 |
| `+snapshot.json` | conversation=50 条全 refiner（旧切片） | 全 agent latest-iter |
| `{run_id}.json` | conversation=579 条**全无 iteration 字段** | 带 iter |
| `+iters+scout+1/2/3.json` | output + input_prompt（**无 tool_calls**） | 完整内容 |

具体塌陷链：

1. `outline_compute.py:73-94` 扫 events buffer 算 iter_count → 但 `_has_events=False`，fallback 合成 iter=1 → **下拉菜单只有 iter 1**
2. `collectors.py:314-315` `build_conversation` 用 `invocation_counts` 加 stamp → 但 `_save_incremental` **先读后写 iter_index**（line 63 先读，line 128 才 update），永远滞后 1
3. `collectors.py:_on_*` 完全不 stamp iter → run record 那 579 条天然无 iter 字段
4. `AgentDetailView.tsx:95-125` 的 lazy-load 分支永远不触发（需要 `selectedIter < latestIteration`，但 latestIteration 永远是 1）

**结构性结论**：每层修复都默认上下游是对的，但每层独立计算 → 永远在打地鼠。

---

## 决策

### D1. `iter_index.json` 是 iter 元数据的唯一来源

```json
{
  "scout": [
    {"iter": 1, "status": "completed", "duration_ms": 60, "summary": "...", "started_at": <ts>, "ended_at": <ts>},
    {"iter": 2, ...},
    {"iter": 3, ...}
  ],
  "selector": [...]
}
```

- Outline renderer、iter dropdown、latestIteration 计算 — **全部从这里读**。
- 禁止任何其他位置重新计算 iter_count。
- **关键发现**：`node_factory.py` 已经把 `node_invocation_counts` 作为 universal invariant（每个 return path 都带，见 `test_node_func_return_paths.py`）。这意味着 count 来源是 runtime state 本身，不需要从 events 或 iter_index 倒推。

### D2. `{run_id}+iters+{node}+{iter}.json` 是 iter 内容的唯一来源（含 tool_calls + todo_steps + 生命周期状态）

```json
{
  "iter": 3,
  "node_id": "scout",
  "status": "streaming|completed|failed|interrupted",   // D7 新增
  "last_seq": 134,                                       // D7 新增 — event_bus seq at last flush
  "started_at": <ts>,
  "ended_at": <ts|null>,                                 // null while streaming
  "duration_ms": <int|null>,
  "input_prompt": <str>,
  "system_prompt": <str>,
  "streaming_text": <str>,                               // D7 新增 — 累积 text_delta，完成后清空
  "output_result": <any|null>,                           // null until completed
  "tool_calls": [                                        // D2 新增（当前缺失）
    {"tool_name": "TodoTool", "tool_args": {...}, "tool_result": <any>, "ts": <ts>, "seq": 120},
    ...
  ],
  "todo_steps": [                                        // O1 新增（从 snapshot 迁出）
    {"task_id": "t_1", "content": "...", "status": "completed", ...},
    ...
  ],
  "summary": <str>,
  "tokens": {"input": 1234, "output": 567}               // 可选
}
```

**变更**：
- 当前 sidecar 不含 `tool_calls`。本 ADR 要求加上（从 `agent_io[node].tool_calls` 直接复制 — 数据本来就在内存，只是没写盘）。
- `todo_steps` 从 snapshot 迁入（见 O1 决策）。
- `status` / `last_seq` / `streaming_text` 用于生命周期管理（见 D7 决策）。

### D3. `snapshot.json` 退化为 manifest

```json
{
  "version": 2,
  "run_id": <id>,
  "workflow_name": <name>,
  "status": "running|completed|failed",
  "created_at": <ts>,
  "updated_at": <ts>,
  "dag": <dag>,
  "current_iter": <int>,
  "node_statuses": {<node_id>: "streaming|completed|failed|idle"},
  "latest_iter_by_node": {<node_id>: <int>},  // 从 iter_index 派生，缓存避免前端二次计算
  "fitness_history": [...],  // NAS 专用，其他 workflow 可省
  "agents_snapshot": [...]   // DAG 节点元信息，outline 渲染需要
}
```

**移除**：`conversation`、`agent_io`、`conversation_total`、`todo_states`（迁入 sidecar，见 O1）。

**保留**：`seq_cursor` 重命名为 `last_seq`（全局事件同步点，前端 WS 重连时用）。

**大小**：从 500KB-1MB 降到 < 10KB（NAS 9-agent 场景）。

### D4. `run_record.json` 不再持久化 conversation

- 新写的 run record 移除 `conversation` 字段。
- 旧 run record 保留 `conversation` 字段（只读兼容），前端 hydration 时不读它。

### D5. 前端永远 fetch，never filter

| 时机 | 行为 |
|---|---|
| 进入 run | `GET /runs/{id}/snapshot` → manifest。`GET /runs/{id}/iter_index` → 渲染 outline |
| 点击 agent | `GET /runs/{id}/nodes/{n}/iters/{latest}` → sidecar（可能是 streaming 或 completed）→ 渲染 |
| 切 iter dropdown | `GET /runs/{id}/nodes/{n}/iters/{i}` → swap 内容 |
| WS 重连 / 刷新后 connect | `since_seq = sidecar.last_seq`，后端只发 seq > last_seq 的增量事件 |
| WS 推 `agent.text_delta` | live streaming：增量 append 到当前 streaming_text 显示 |
| WS 推 `agent.tool_call` | live streaming：append 到 tool_calls 显示 |
| WS 推 `node.completed` | 失效该 (nodeId, iter) 缓存，重新 fetch sidecar（拿到 output_result + 最终 tool_calls） |

**移除**：`hydrateFromSnapshot` 里读 conversation 的逻辑、`AgentDetailView` 里 `m.iteration ?? 1 === selectedIter` 的过滤分支。**所有 (nodeId, iter) → 内容的映射走 fetch**。

### D6. 后端 API 收敛

| 端点 | 用途 | 变更 |
|---|---|---|
| `GET /runs/{id}/snapshot` | manifest | 响应体瘦身（D3） |
| `GET /runs/{id}/iter_index` | outline 数据 | **新增**（独立端点，避免和 manifest 耦合） |
| `GET /runs/{id}/nodes/{n}/iters` | iter 列表（轻量） | 已存在 |
| `GET /runs/{id}/nodes/{n}/iters/{i}` | iter 详情 sidecar（含 streaming 状态） | 已存在，**响应加 tool_calls / todo_steps / status / last_seq / streaming_text** |
| `WS /runs/{id}?since_seq=N` | 增量事件 | 已支持 since_seq，**前端总是用 sidecar.last_seq 作为 since_seq** |
| `GET /runs/{id}/conversation` | legacy | **废弃**（保留 1 个版本供旧前端兼容，下个版本删除） |

### D7. sidecar 是生命周期实体（streaming → completed），刷新零丢失

**问题**：node 跑到一半用户刷新页面 → 当前架构下 in-flight 的 text_delta 全丢（sidecar 还没写，event buffer 不持久化）。

**决策**：sidecar 不再是"node 完成才写"，而是**生命周期内同一个文件，状态会演进**：

```
node.started   →  sidecar  {status: "streaming",   last_seq: 100, streaming_text: "",      tool_calls: []}
                     ↓ debounced flush（每 500ms 或 tool_call 完成边界）
streaming 中   →  sidecar  {status: "streaming",   last_seq: 134, streaming_text: "Hello…", tool_calls: [3个]}
                     ↓
node.completed →  sidecar  {status: "completed",   last_seq: 156, output_result: {...},    tool_calls: [18个]}
                     ↓ （streaming_text 清空，output_result 填充）
```

**刷新零丢失契约**：

```
前端刷新
  ├─ GET sidecar → 拿到 (内容, last_seq=N)
  ├─ 渲染内容（带 "Live" 徽章若 status=streaming）
  └─ WS connect with since_seq=N
       ↓
后端只发 seq > N 的增量事件
  ├─ text_delta → append 到 streaming_text
  ├─ tool_call  → append 到 tool_calls
  └─ node.completed → 触发前端重新 fetch sidecar（最终版）
```

**关键不变量**：sidecar.last_seq 是后端和前端的**同步点**。前端永远知道自己拥有"到 seq N 为止"的数据。

**写入策略**：

- node.started：写初始 sidecar（status=streaming, last_seq=current event_bus seq）
- debounced flush：500ms 或 tool_call 完成边界，触发 atomic rename 写入
- node.completed：final atomic rename，status=completed，streaming_text 清空
- atomic rename（tmpfile + `os.rename`）保证文件要么是旧状态要么是新状态，永不半写

**鲁棒性分析**：

| 场景 | 行为 |
|---|---|
| 前端刷新 | sidecar 提供 last_seq，WS 增量接续。零丢失。 |
| WS 短暂断开重连 | 同刷新逻辑，零丢失。 |
| 后端进程崩溃 | 磁盘上是最后一次 flush 的 sidecar。重启后前端 GET sidecar → status=streaming 但 ended_at=null + last_seq 远小于当前 → 前端显示"interrupted"。 |
| 磁盘满 / 写盘失败 | 走 R3 决策：retry + log loud + 不 fail the node |
| 后端重启后 node 没继续跑 | 由 checkpointer 路径决定。若 cycle 终止，下次 snapshot save 把 streaming 状态改 failed/interrupted。 |

**与现有架构的契合**：
- `last_seq` 概念已存在（snapshot.seq_cursor）— 扩展到 sidecar 是自然延伸。
- atomic rename 模式已在 R3（写盘安全）和 outline_save 中使用。
- 不需要新 endpoint（沿用 `/runs/{id}/nodes/{n}/iters/{i}`）。

**风险**：
- 写入压力：debounce 500ms × 1-3 并发 agent = 每秒 2-6 次 atomic rename。NAS 场景完全无压力。
- schema 兼容：旧 sidecar（status 字段缺失）默认按 `completed` 处理 — 反正旧 sidecar 都是完成时才写的。

---

## 不变量（Invariants）

任何 PR 必须不违反以下任一条。CI 应加 invariant 检查：

1. **I1**: `iter_index.json` 中节点 N 的 iter 数 = 磁盘上 `{run_id}+iters+{N}+{i}.json` 文件数（i ∈ index）。
2. **I2**: 每个 sidecar 必有 `iter / node_id / status / started_at`，可选 `ended_at / tool_calls / todo_steps / tokens / streaming_text`。
3. **I3**: `snapshot.latest_iter_by_node[N]` = `max(iter_index[N].iter)`。
4. **I4**: `node_factory` 任何 return path 都带 `node_invocation_counts`（已存在，保留）。
5. **I5**: 写 sidecar 之前，对应的 `iter_index` 条目不存在；写完 sidecar 再 update iter_index（顺序保证 I1）。
6. **I6**: snapshot 大小永远 < 50KB（NAS 9-agent 场景；超了说明塞了不该塞的数据）。
7. **I7**（D7）: sidecar 永远带 `last_seq` 字段。WS 重连契约：前端用 `since_seq = sidecar.last_seq` 接续。
8. **I8**（D7）: sidecar 写盘永远走 atomic rename（`tmpfile + os.rename`），禁止直接 overwrite。
9. **I9**（O1）: `todo_steps` 只存在于 sidecar，不再存于 snapshot。

---

## 分阶段实施

每阶段独立可发布、独立可回滚。前 3 阶段是**纯增量**（不改现有契约），第 4 阶段开始**迁移**。

### Phase 0: Validation（无行为变更）

- 加 JSON Schema 文件：`schemas/snapshot.v2.json`、`schemas/iter_sidecar.v2.json`、`schemas/iter_index.v2.json`
- 加 CI lint：扫描 `runs/` 目录，报告 invariant 违反
- 加 Python helper：`harness/persistence/validate.py`，写盘前 validate，fail loud

**目的**：把"隐式契约"变成"显式断言"。这一阶段就能挡住未来一半的 bug。

### Phase 1: Outline 走 iter_index（最小用户影响）

- 改 `outline_compute.py`：签名加 `iter_index: dict`，移除对 events 的扫描（fallback 兜底）
- 改 `outline_save.py`：传入 iter_index
- 改 `incremental_save.py`：`save_outline_sidecar(iter_index=...)`

**用户感知**：iter dropdown 终于能显示多个 iter。

**风险**：旧 run 没 iter_index 或不完整 → fallback 到当前 events 路径，保持兼容。

### Phase 2: Sidecar 内容补全 + 生命周期管理（拆为 2a / 2b）

#### Phase 2a: sidecar 加 tool_calls + todo_steps（解决"看不到历史 iter 内容"）

- 改 `incremental_save._save_incremental`：写 sidecar 时把 `agent_io[node].tool_calls` 和 `builder.todo_states[node]` 也写进去
- 改 `server/routers/runs.py:_iter_sidecar_to_messages`：把 tool_calls 投影成 ConversationMessage
- 改 `AgentDetailView.tsx`：lazy-load 路径不变（已存在），但现在拉到的 sidecar 内容是完整的

**用户感知**：点 scout iter 1 → 看到 iter 1 的完整 tool_calls + todo（之前只有 output）。

**风险**：旧 sidecar 无 tool_calls / todo_steps → 显示 output + input_prompt（退化，不阻塞）。

#### Phase 2b: sidecar 生命周期 + debounced flush（D7，解决"刷新丢流式"）

- 新增 `harness/persistence/sidecar_writer.py`：`InflightSidecarWriter` 类，订阅 event_bus，管理一个 (node, iter) 的 streaming sidecar
- 在 `node.started` 时创建 writer，500ms debounce 或 tool_call 完成时 flush，node.completed 时 finalize
- 改 sidecar schema：加 `status / last_seq / streaming_text`，node.completed 时 streaming_text 清空 + output_result 填充
- 改前端 `AgentDetailView`：渲染时按 status 区分（streaming 显示 "Live" 徽章 + streaming_text；completed 显示 output_result）
- 改前端 WS 重连：`since_seq = sidecar.last_seq`

**用户感知**：刷新正在跑的 scout iter 3 → 看到已 stream 的内容（带 Live 徽章）+ WS 接续新 token → 完成后无缝切换到最终 sidecar。

**风险**：写入压力测试需验证（NAS 9-agent 并发场景）。

### Phase 3: E2E 测试（North Star）

加 Playwright 或继续 vitest + msw 模拟整套 API：

```
1. 启动 NAS run（mock backend 或录制回放），让 scout 完成 iter 1
2. 刷新页面
3. 点击 scout → 看到 iter 1 完整内容（含 tool_calls）
4. 等 iter 2 完成
5. scout 下拉出现 iter 2
6. 点 iter 1 → 仍看到 iter 1 内容（不是 iter 2）
7. 切到 selector → 看到 selector iter 1
8. 再次刷新 → 全部上述断言仍成立
9. scout 跑 iter 3 中途刷新 → 看到 streaming_text（Live 徽章）+ WS 接续 token
10. iter 3 完成 → 内容无缝切换到 output_result，无闪烁
```

**这是 Phase 4 的合并门槛**：测试不通过禁止进入迁移阶段。

### Phase 4: Snapshot 瘦身（移除冗余通道）

- 改 `_save_incremental`：snapshot 不再写 `conversation / agent_io / conversation_total`
- 改 `hydrateFromSnapshot`：不再读 conversation
- 改 `AgentDetailView`：latest iter 也走 fetch（不再读 scoped conversation store）

**用户感知**：刷新更快（< 200ms 出骨架，无论 run 多长）。

**风险**：live streaming 体验需验证 — text_delta 仍走 WS，但 latest iter 的"最终内容"必须从 sidecar fetch。需要确认 AgentDetailView 的渲染策略：live 期间实时 WS，node 完成后切换到 sidecar。

### Phase 5: Run record 清理

- `save()` 不再传 conversation
- 旧 run record 的 `conversation` 字段保留只读
- 删除 `/runs/{id}/conversation` 端点（deprecated 一个版本后）

### Phase 6: 旧数据迁移（可选）

写一个迁移脚本：扫描所有 `runs/*.json`，如果 events.json 存在，从 events 重建 tool_calls 写入对应 sidecar。**只有用户报告"老 run 看不了历史"才跑**，不做自动迁移。

---

## 验证矩阵

| 阶段 | 单测 | 集成测 | E2E | 真机 |
|---|---|---|---|---|
| Phase 0 | schema 校验 | CI lint | — | — |
| Phase 1 | `test_outline_compute` | — | — | dropdown 显示多 iter |
| Phase 2a | `test_collectors` / `test_iter_sidecar` | — | — | 历史 iter 有 tool_calls + todo |
| Phase 2b | `test_sidecar_writer` (debounce / atomic / seq) | 写入压力测试 | — | 刷新 scout iter 3 不丢流式 |
| Phase 3 | — | — | ✅ vitest+msw | — |
| Phase 4 | hydration 测 | snapshot 大小断言 | ✅ | 刷新 < 500ms |
| Phase 5 | run_record schema | — | ✅ | 老 run 仍可读 |

## 工作量（更新）

| Phase | 工作量 | 备注 |
|---|---|---|
| 0. Schema + CI lint + `save_iter_sidecar_safe` 封装 | 0.5 天 | 含 R3 retry/verify |
| 1. outline 走 iter_index | 0.5 天 | `outline_compute.py` 改签名，删 events 扫描 |
| 2a. sidecar 加 tool_calls + todo_steps | 0.5 天 | incremental_save 加字段 + sidecar projection |
| 2b. InflightSidecarWriter + D7 生命周期 | 1.5 天 | 含前端 streaming 状态渲染 + WS since_seq 接续 |
| 3. E2E 测试 | 1 天 | vitest + msw（不引入 Playwright） |
| 4. snapshot 瘦身 | 0.5 天 | 移除冗余字段，前端 hydration 改路径 |
| 5. run_record 清理 | 0.5 天 | 移除 conversation 写入，保留读兼容 |
| **总计** | **5 天** | 不含 Phase 6 迁移 |

---

## 替代方案（ruled out）

### A. 继续打补丁：让 outline 扫 events 时正确处理 iter

否定理由：events buffer 是 FIFO，长 run 中早期 node.started 会被淘汰。outline 永远不可能从 events 算出正确的 iter_count。**这是结构性问题，不是 bug**。

### B. snapshot 内嵌全量 conversation（不分 iter）

否定理由：NAS 长 run 500+ 消息 → snapshot 1MB+。每次 node 完成 rewrite 整个 snapshot = O(N) 写盘。本 ADR 的 D3 显式禁止。

### C. 把 iter 信息塞到每条 conversation message 里，前端按 iter 过滤

否定理由：就是当前失败的方案。问题在于"全量 conversation"和"按 iter 过滤"两个 O(N) 操作叠加。本 ADR D5 显式禁止前端 filter。

### D. 用 SQLite 替代 JSON 文件

否定理由：当前痛点是**数据源不收敛**，不是 JSON 性能问题。换 SQLite 解决不了 outline 算错 iter_count 的问题，反而引入 schema migration 复杂度。本 ADR 保持 JSON，但收敛来源。若未来单 run 真的出现性能问题（10k+ iter），再考虑。

---

## 风险与开放问题

### R1: Live streaming 和 sidecar 的边界 → ✅ 已决策（升级为 D7）

**问题**：node 跑到一半用户刷新页面 → 当前架构下 in-flight 的 text_delta 全丢。

**决策**：见 **D7 — sidecar 是生命周期实体**。通过 debounced flush + `last_seq` 同步点实现刷新零丢失。

### R2: 多 subscriber 并发刷新

**问题**：当前架构是单进程 FastAPI，问题不大。但如果未来多 worker 部署，sidecar 写盘和读盘的原子性需要保证。

**决策**：写盘用 atomic rename（`tmpfile` + `os.rename`），POSIX 保证原子性。Phase 0 时统一加上。多 worker 部署时再考虑 file lock，当前不阻塞。

### R3: sidecar 写盘失败 → ✅ 已决策

**问题**：`builder.agent_io[node] = io_data` 每次覆盖。如果 sidecar 写盘失败（exception 被吞），那一 iter 的数据就丢了。

**决策**：retry 1 次 + 失败 log loud + 不 fail the node + 加写后验证。

```python
def save_iter_sidecar_safe(run_id, node_id, iter_num, data):
    path = ...
    # 1. atomic write（tmpfile + os.rename）
    # 2. 写后立即 verify（防磁盘满 / 权限问题静默失败）
    # 3. 失败重试 1 次
    # 4. 还失败 → log WARNING + 前端 toast 提示
    #    不 raise — node 本身已完成，业务结果正确，只是观测数据丢
```

**理由**：业务运行（node 产出 output_result）和持久化（写 sidecar）是两个关注点。sidecar 丢 = 观测损失，不阻塞业务。但要 log loud 避免静默丢失。

**Phase 0 时落地**（统一封装 `save_iter_sidecar_safe`，所有写 sidecar 的路径走这函数）。

### R4: 旧数据迁移工作量

**问题**：磁盘上 4 个 NAS run，3 个是旧格式。用户点开看到不对的怎么办？

**决策**：
- Phase 1（outline 走 iter_index）让旧 run 的 iter dropdown 立即正确（iter_index 文件本来就对）
- Phase 2a 之后旧 run 的历史 iter 内容只能看到 output（无 tool_calls），但不再"看不到 iter 1"
- Phase 2b 之后旧 run 的 streaming 状态显示为 interrupted（无 last_seq，前端按 completed 兜底）
- 完全恢复需要 Phase 6 迁移脚本（如果用户需要）

### O1: todo_states 是否也走 sidecar？ → ✅ 已决策

**决策**：todo_states 按 (node, iter) 拆进 sidecar。

实测 todo_states 当前结构已经是 per-node + per-step-iter：
```python
{
  "project_analyzer": [
    {"task_id": "t_1", "content": "...", "status": "completed", "iteration": 1, ...},
    {"task_id": "t_2", "content": "...", "status": "in_progress", "iteration": 2, ...}
  ],
  ...
}
```

sidecar 增加 `todo_steps` 字段（filter 出 iteration === this sidecar's iter 的 steps）。snapshot 移除 todo_states（Phase 4）。前端通过 sidecar 拿 todo，无需独立 endpoint。

**已加入 D2 schema**。

### O2: `nodes_latest` 字段是否冗余？

`snapshot.nodes_latest[nid].latest_iter` 看起来和 `iter_index` 重复。Phase 4 时合并到 `latest_iter_by_node`。

---

## 对齐检查表

用户请确认以下决策：

- [x] **D1**: iter_index 是唯一来源（不再扫 events）
- [x] **D2**: sidecar 必须含 tool_calls + todo_steps + 生命周期字段（status / last_seq / streaming_text）
- [x] **D3**: snapshot 移除 conversation / todo_states（< 10KB manifest）
- [x] **D4**: run record 不再写 conversation（旧字段保留只读）
- [x] **D5**: 前端永远 fetch，never filter；WS 用 sidecar.last_seq 接续
- [x] **D6**: API 收敛方向 OK（`/runs/{id}/conversation` 废弃）
- [x] **D7**: sidecar 是生命周期实体，streaming 期间 debounced flush，刷新零丢失
- [x] **R3**: sidecar 写盘失败 retry 1 次 + log loud + 不 fail the node + 写后验证
- [x] **O1**: todo_states 拆进 sidecar（按 iter 过滤）
- [ ] **Phase 顺序**：0 → 1 → 2a → 2b → 3(E2E) → 4 → 5 → 6
- [ ] **E2E 是 Phase 4 合并门槛**
- [ ] **工作量 5 天**（Phase 2b 占 1.5 天）可接受

如全部 OK，下一步写 Phase 0 的 implementation plan。
