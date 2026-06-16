# 长 Run Replay 架构：Snapshot + Incremental + On-demand

> 日期：2026-06-16
> 状态：方案定稿，待排期实施
> 起源：NAS workflow 实测发现（[`2026-06-16-nas-run-findings-and-arch-issues.md`](./2026-06-16-nas-run-findings-and-arch-issues.md) 问题 #4 深化）
> 分支：`main`
> 替代：本计划包含原问题 #4 的"方案 A 重分类"作为 Phase 1 的一部分，是更彻底的根治方案

## 背景

当前刷新页面 → WS subscribe(since_seq=0) → 把 bus buffer 里**所有 critical 事件**重放给前端，前端按 seq 顺序串行 dispatch + rerender。复杂度 O(N)，N 是事件总数。

NAS 长 run（200+ iter × K=3 strategies × 平均 73 bash/agent = 4 万+ tool 事件，加上 node lifecycle / chat / chart 等共 5 万+ 事件）下：
- 刷新延迟 10+ 秒，浏览器可能卡死
- WS buffer 进程内存单调增长到几十 MB
- 多 subscriber 同时刷新会放大问题

问题 #4 的"方案 A 重分类"只能把 buffer 控制在 2000 normal + 50 critical ≈ 2050 事件，刷新降到 1-2 秒。但 1-2 秒仍然慢，且 2000 事件串行 dispatch 仍是主线程阻塞。

**目标**：刷新延迟与 run 长度**完全解耦**，无论跑多久都是 O(1)（< 500ms）。

---

## 目标态用户体验

### 刷新延迟（核心指标）

| Run 长度 | 当前 | 目标态 |
|---|---|---|
| 10 分钟（5 iter） | 1-2s 卡顿 | < 200ms 出骨架，500ms 出主视图 |
| 2 小时（50 iter） | 3-8s 卡顿，输入框无响应 | < 200ms 出骨架，500ms 出主视图 |
| 24 小时（200+ iter） | 10+s，可能浏览器卡死 | < 200ms 出骨架，500ms 出主视图 |

**承诺**：刷新延迟与 run 长度解耦。

### Cycle agent 多轮的 UI 模型（NAS 痛点）

NAS 的 selector / planner / trainer / judger 等会跑 N 轮。目标态分两层呈现：

#### 主视图：只显示**最新 iter** 的状态

刷新后立刻看到：
- DAG 节点状态（基于最新 iter）：selector ✓ iter 7 / planner ✓ iter 7 / trainer 🔄 iter 7 / judger ⏸ ...
- 当前 iter 的 TodoList
- **当前 iter 的 Conversation**（按 iter 隔离，见下文）
- 当前 iter 的 Chart
- Fitness 趋势图（**全量历史**，每 iter 一个点，200 iter 也只有几 KB）

#### 节点详情：iter 下拉选择器，按需加载历史

点击 DAG 上的 selector 节点 → 右侧抽屉打开：

```
┌─────────────────────────────────────┐
│ selector                            │
├─────────────────────────────────────┤
│ Iter: [Iter 7 (latest) ✓ ▾]        │  ← 下拉选择器
├─────────────────────────────────────┤
│ Iter 7 详情：                       │
│ ─ 输入：parent=iter_6_strategy_2    │
│ ─ 工具调用（12 次）：               │
│   • python direction.py detect ...  │
│   • cat budget.json                 │
│   ...                               │
│ ─ 输出：K=3, parent=..., tier=0     │
│ ─ 耗时：8.2s / token: 4.2k          │
└─────────────────────────────────────┘
```

点击下拉 → 展开所有 iter 列表（iter 1 ~ iter N，latest 高亮）→ 选 iter 6 → 调 API 拉那一 iter 详情 → 抽屉内容刷新。

**关键交互**：
- 下拉选择器是**用户主动行为**，不预加载所有 iter
- 切换 iter 后 conversation 也跟着切换（见下文）
- iter 列表只显示 iter 号 + status + duration（轻量），不预取详情

### Conversation 按 iter 隔离（关键简化）

当前 conversation 是全局时间线（所有 iter 的消息按时间混合显示）。**改为按 iter 隔离**：

- 默认显示**当前 iter** 的消息（如 iter 7 的 selector / planner / trainer 各自的输出 + 该 iter 内的 ask_user 问答）
- 切换 iter 下拉 → conversation 自动过滤到该 iter 的消息
- 单 iter 消息数通常 5-15 条，**无需分页**
- 罕见情况（scout 在 setup 阶段多次 ask_user）单 iter 消息 > 50 条 → 分页 50 条

**好处**：
- 不需要为长 conversation 做复杂的全局分页 + 虚拟滚动
- 每个 iter 是独立视图，用户心智模型清晰（"我在看 iter 7 的事"）
- 加载量从"全部历史"降到"当前 iter"，自然 O(1)

**setup 阶段对话**（project_analyzer / scout，非 cycle）：归入"iter 0"或"setup"分组，cycle 启动前的对话归这里。

### Chart 与 Fitness 序列

- **Fitness 趋势图**：snapshot 全量携带（每 iter 一个数据点：iter_num + fitness + latency + acc），200 iter ≈ 几 KB。前端立刻渲染完整曲线。
- **详细 Chart**（每个 strategy 的 loss_curve / latency_breakdown / params）：按 iter 切换时按需查 API，不在 snapshot 里。

### 不做"完整回放模式"

明确放弃：不提供老的"全量 replay"调试模式。原因：
- snapshot + iter 切换已经能覆盖所有查看需求
- 维护两套刷新逻辑（snapshot-based + replay-based）成本高
- 调试需求可以靠后端日志 + events.jsonl 查询满足

---

## 核心架构

### 三层事件模型

| 层级 | 内容 | 存储 | Replay 策略 |
|---|---|---|---|
| **L1 Hot** | workflow/node lifecycle、chat.question/answer/timeout、workflow.interrupted/waiting_for_guidance、agent.failed_with_classified_reason | critical buffer（无上限） | snapshot 必备 + 全 replay |
| **L2 Warm** | tool_call/tool_result、todo.*、chart.render、agent.text_delta、agent.thinking_delta、agent.usage_update、agent.retry_attempted、node.iter_completed | normal FIFO buffer（容量 1000） | snapshot 摘要 + 最近 N 个 replay |
| **L3 Cold** | 详细 tool 输出 / 完整 text_delta / 历史 agent_io / 单 iter 事件流 | run_store sidecar（按 iter 分片持久化） | 不 replay，按需 API 查 |

关键洞察：**当前问题是 L2 和 L3 都用 L1 的策略**（critical 全保留），buffer 无限膨胀。

### 刷新数据流（目标态）

```
1. 用户刷新 → activateRun(runId)
2. GET /api/runs/{id}/snapshot
   后端返回（增量维护的 latest.json，O(1) 读取）：
   - workflow status / current_iter / seq_cursor
   - DAG nodes 当前 status（latest iter only）
   - 当前 iter 的 todo / outline / chart 摘要
   - 当前 iter 的 conversation（5-15 条）
   - 全量 fitness 序列（200 点）
   - 每个 cycle agent 的 iter 总数
   返回 50-200KB JSON
3. 前端单次 setState hydrate 所有 scoped store
4. WS subscribe(since_seq = snapshot.seq_cursor)
5. WS 推送 seq > cursor 的增量事件
6. UI 立即正确显示（步骤 3 完成），后续小幅更新
```

**刷新延迟 = GET snapshot + 一次 setState + WS 增量订阅**，与 run 长度解耦。

### Cycle agent 多轮的存储模型

后端 run_store 扩展 layout：

```
sessions/{run_id}/
├── events.jsonl                  # 全量事件流（按需查；超 1000 iter 时分片）
├── iter_index.json               # {node_id: [{iter, seq_range, summary, status, duration_ms}]}
├── snapshots/
│   └── latest.json               # L1+L2 摘要，每次 node.iter_completed 时增量更新
├── sidecars/
│   ├── selector/
│   │   ├── iter_1.json           # 完整 iter 详情（input/tool_calls/output）
│   │   ├── iter_2.json
│   │   └── ...
│   ├── planner/iter_*.json
│   ├── trainer/iter_*.json
│   └── ...
└── (既有: outline.json, conversation.json, charts.json, agents_io.json)
```

每个 cycle agent 完成一次（node.completed）→ 后端：
1. 写 `sidecars/{node}/iter_{N}.json`（L3 详细）
2. 更新 `iter_index.json`（追加该 node 的 iter 记录）
3. 更新 `snapshots/latest.json`（latest iter 字段）
4. emit `node.iter_completed`（L2，仅 summary）

---

## 后端接口设计

### 新增 API

#### `GET /api/runs/{id}/snapshot`

```json
{
  "run_id": "...",
  "workflow_name": "nas",
  "status": "running",
  "current_iter": 7,
  "seq_cursor": 4521,
  "dag": {...},
  "nodes": {
    "selector": {
      "status": "completed",
      "latest_iter": 7,
      "total_iters": 7,
      "latest_duration_ms": 8200,
      "latest_summary": "K=3, parent=strat_2"
    },
    "trainer": {
      "status": "running",
      "latest_iter": 7,
      "total_iters": 7
    }
  },
  "current_iter_state": {
    "todo": [...],
    "outline": [...],
    "conversation": [...],
    "charts": [...]
  },
  "fitness_history": [
    {"iter": 1, "fitness": 0.65, "latency_ms": 48, "acc": 0.92},
    {"iter": 2, "fitness": 0.71, ...},
    ...
  ]
}
```

实现：读 `snapshots/latest.json` + 内存 node lifecycle 状态。O(1)。

#### `GET /api/runs/{id}/nodes/{node}/iters`

```json
{
  "node_id": "selector",
  "iters": [
    {"iter": 7, "status": "completed", "duration_ms": 8200, "summary": "K=3, parent=strat_2"},
    {"iter": 6, "status": "completed", "duration_ms": 7500, "summary": "K=3, parent=strat_1"},
    {"iter": 5, "status": "completed", "duration_ms": 6800, "summary": "K=3, parent=baseline"},
    ...
  ]
}
```

实现：读 `iter_index.json[node]`。O(1)。

#### `GET /api/runs/{id}/nodes/{node}/iters/{n}`

```json
{
  "iter": 7,
  "input": {...},
  "tool_calls": [
    {"seq": 4525, "tool": "bash", "args": {...}, "result_truncated": "..."},
    ...
  ],
  "output": {...},
  "events_seq_range": [4521, 4633],
  "duration_ms": 8200,
  "token_usage": {...}
}
```

实现：读 `sidecars/{node}/iter_{n}.json`。O(1)。

#### `GET /api/runs/{id}/conversation?iter={n}&offset=0&limit=50`

按 iter 过滤的 conversation。单 iter 消息少时直接返回；多时分页 50。

实现：从 conversation.jsonl 按 iter 字段过滤（事件持久化时打 iter 标签）。

### 现有 API 改造

- `GET /api/runs/{id}` 主记录保持不变（轻量字段，不依赖 snapshot）
- 各 sidecar API（`/conversation` `/outline` `/charts` `/events`）保留，作为 L3 查询的 fallback（旧 run 没有 iter sidecar 时降级使用）

### 事件持久化打 iter 标签

每个事件持久化到 events.jsonl 时，根据当前 cycle 状态打 `iter` 字段：

```json
{"seq": 4525, "type": "agent.tool_call", "iter": 7, "node_id": "selector", "payload": {...}}
```

让 conversation / 冷数据查询能按 iter 过滤。iter 字段从 `node_invocation_counts` 推导。

---

## 前端改造

### activateRun 流程改造

`frontend/src/lib/activateRun.ts` running 分支：

```diff
  if (full.status === "running") {
+   // 新流程：先 snapshot hydrate，再 WS 增量订阅
+   const snapshot = await fetchSnapshot(runId);
+   if (seq !== _activateSeq) return;
+
+   // 单次 setState hydrate 所有 scoped store
+   hydrateFromSnapshot(snapshot);
+
+   // WS 只接收 snapshot 之后的事件
+   useAppViewStore.getState().setRunMode("live");
+   // useWorkflowWS 内部用 snapshot.seq_cursor 调 subscribe
+   wsSubscribeSinceRef.current = snapshot.seq_cursor;
+
    // 既有：showLive + setWorkflow ...
  }
```

旧流程（fetchRun → WS subscribe(0) → 全量 replay）保留作为 fallback，用于 snapshot API 不可用的情况。

### Scoped store 新增字段

`workflowStore.NodeState`：

```ts
interface NodeState {
  // 既有字段...
  latestIter?: number;
  totalIters?: number;
  latestIterStatus?: "running" | "completed" | "failed";
  latestIterSummary?: string;
}

interface WorkflowState {
  // 既有字段...
  currentIter?: number;
  fitnessHistory?: Array<{iter: number; fitness: number; latency_ms: number; acc: number}>;
  selectedIter?: number | "latest";  // 用户在下拉选的 iter
}
```

### 节点详情抽屉：iter 下拉选择器

`AgentIODrawer.tsx`（或新组件）：

```tsx
function NodeIterSelector({ nodeId, totalIters, latestIter }: Props) {
  const [open, setOpen] = useState(false);
  const [iters, setIters] = useState<IterSummary[] | null>(null);
  const selectedIter = useScopedWorkflowStore(s => s.selectedIter) ?? "latest";

  // 用户点开下拉时才加载 iter 列表
  useEffect(() => {
    if (open && !iters) {
      fetchNodeIters(nodeId).then(setIters);
    }
  }, [open]);

  return (
    <Dropdown>
      <DropdownTrigger>
        Iter {selectedIter === "latest" ? `${latestIter} (latest)` : selectedIter}
      </DropdownTrigger>
      <DropdownMenu>
        {iters?.map(it => (
          <DropdownItem key={it.iter} onClick={() => selectIter(it.iter)}>
            Iter {it.iter} {it.iter === latestIter && "(latest)"} — {it.status} — {it.duration_ms}ms
          </DropdownItem>
        ))}
      </DropdownMenu>
    </Dropdown>
  );
}
```

选择某个 iter → 触发 `fetchNodeIterDetail(nodeId, iterNum)` → 更新抽屉内容 + 同时切换 conversation 到该 iter。

### Conversation 按 iter 过滤

`useConversationMessages()` hook 改造：

```ts
function useConversationMessages() {
  const selectedIter = useScopedWorkflowStore(s => s.selectedIter) ?? "latest";
  const currentIter = useScopedWorkflowStore(s => s.currentIter);

  const effectiveIter = selectedIter === "latest" ? currentIter : selectedIter;

  const allMessages = useScopedStore(s => s.conversation.messages);
  return allMessages.filter(m => m.iter === effectiveIter);
}
```

切换 iter 下拉 → conversation 自动重新过滤。

### Fitness 趋势图全量渲染

`FitnessChart.tsx`：

```tsx
function FitnessChart() {
  // 直接读 snapshot 里的全量序列，无需分页 / 虚拟滚动
  const history = useScopedWorkflowStore(s => s.fitnessHistory);
  return <LineChart data={history} ... />;
}
```

200 iter × 4 字段 × 8 bytes ≈ 6.4KB，无性能压力。

---

## 实施路径

### Phase 1 — 事件分层 + Snapshot API（P0 基础）

**目标**：刷新不再 O(N)。主视图行为不变（仍按时间线显示），但底层换成 snapshot。

**改动**：
- 后端 `bus.py`：重分类 `CRITICAL_EVENT_TYPES`（L1 hot 只保留生命周期 + chat + 失败）
- 后端 `node_factory.py`：cycle agent 完成时增量写 `snapshots/latest.json`
- 后端新增 `GET /api/runs/{id}/snapshot`
- 后端事件持久化打 `iter` 标签
- 前端 `activateRun.ts`：running 分支改走 snapshot hydrate

**验收**：
- 跑 50 iter NAS，刷新延迟 < 500ms（当前 3-8s）
- WS 进程内存稳定（不再单调增长）
- 旧 run（无 snapshot）降级走老路径，体验不退化

**工作量**：4-5 天

### Phase 2 — Cycle iter 持久化 + 查询 API

**目标**：cycle agent 多轮可追溯。

**改动**：
- 后端 `node_factory.py`：cycle agent 完成时写 `sidecars/{node}/iter_{N}.json` + 更新 `iter_index.json`
- 后端新增 `GET /api/runs/{id}/nodes/{node}/iters` 和 `GET .../iters/{n}`
- 后端新增事件 `node.iter_completed`（L2，summary only）

**验收**：
- 跑 50 iter NAS，API 能查到 selector 所有 iter 详情
- iter 切换 < 1s

**工作量**：2-3 天

### Phase 3 — 前端 iter 下拉 + Conversation 按 iter 隔离

**目标**：UI 体验闭环，cycle 多轮可点击访问。

**改动**：
- 前端 `NodeIterSelector` 组件（下拉选择器）
- 前端 `AgentIODrawer` 集成 iter 切换
- 前端 `useConversationMessages` 按 iter 过滤
- 前端 DAG 节点显示 `latestIter/totalIters`

**验收**：
- 点击 selector 节点 → 抽屉打开 → 下拉默认 latest
- 切到 iter 6 → 1s 内加载 iter 6 详情 + conversation 切换

**工作量**：3-4 天

### Phase 4 — Fitness 全量序列 + Chart 按需

**目标**：长 run 下 fitness 趋势图全量可见，详细 chart 按需。

**改动**：
- 后端 snapshot 携带 fitness_history 全量
- 前端 FitnessChart 渲染全量序列
- 详细 chart（loss_curve / latency_breakdown）走 iter sidecar 按需查

**验收**：
- 跑 200 iter NAS，fitness 趋势图秒级渲染完整曲线
- 切换 iter 时详细 chart 1s 内加载

**工作量**：2 天

---

## 关键技术决策

### 决策 1：Snapshot 更新策略 — 增量维护（B 方案）

snapshot 不在每次 API 请求时构造，而是增量维护在 `snapshots/latest.json`：

- 每次 `node.completed` / `node.iter_completed` / `todo.updated` / `chat.answer` 时增量更新对应字段
- API 读取时直接 `read_json()` + return，O(1)
- 写失败 fail loud：emit `snapshot.stale` 事件，前端显示"数据可能滞后"提示

**理由**：cycle agent 跑很多次，反正事件流也在更新，把 snapshot 维护成本分摊到事件处理是合理的。

**替代方案 A（on-demand 构造）**：每次请求时从 events.jsonl 实时聚合。每次 100ms+ 计算，不划算。否决。

### 决策 2：Snapshot 一致性 — seq_cursor + 幂等 reducer

snapshot 携带 `seq_cursor = 构造开始时的 bus._seq`：

- 前端 WS `subscribe(since_seq=cursor)`
- 构造期间产生的事件（cursor+1 ~ 当前）会被 WS 推送
- 这些事件可能已经被 snapshot 反映（如 node.completed 已写 latest.json，对应事件又通过 WS 推送一次）
- 前端 reducer 必须**幂等**：按 event seq 去重（已有 `_replaySeq` 模式可参考扩展）

**审计点**：实施前需审计所有 scoped store reducer，确保对同一 seq 事件的重复处理是安全的（setState 时跳过已处理的 seq）。

### 决策 3：WS 还是 SSE — 保持 WS

WS 双向（用户 ask_user 回答、followup、stop-regenerate 也要走）。SSE 单向需要额外 HTTP POST 配合。不换。

### 决策 4：兼容旧 run

旧 run（无 snapshot / iter sidecar）：
- snapshot API 检测 `latest.json` 不存在 → fallback 到老路径：从 events.jsonl 实时聚合（慢但可用，可能 1-3s）
- iter API 检测 sidecar 不存在 → 404，前端显示"该 run 无 iter 详情（旧格式）"

不维护两套 hydration 逻辑（明确放弃"完整回放模式"），但 API 层做 fallback。

### 决策 5：events.jsonl 分片（超长 run）

预期：24h run 可能 5 万+ 事件，events.jsonl 几 GB。按 iter 分片：

```
sidecars/_events/
├── iter_001_050.jsonl
├── iter_051_100.jsonl
└── ...
```

每 50 iter 一片。查询时按 iter 定位分片。**Phase 2 内做掉，不留技术债**。

### 决策 6：Snapshot 内容边界 — 全量 fitness

fitness_history 全量进 snapshot（200 iter ≈ 6KB）。**用户确认**。

替代方案（只放最近 N 个）否决理由：用户看趋势图就是要看完整曲线，截断的趋势图失去决策价值。6KB 无性能压力。

### 决策 7：Iter 切换 UI — 下拉选择器

**用户确认**。否决 tab 切换器（iter 多了拥挤）和时间轴（占空间）。

下拉选择器：
- 默认折叠显示 "Iter 7 (latest)"
- 点击展开所有 iter 列表（轻量字段：iter / status / duration）
- 选择后 conversation 自动跟着切换

### 决策 8：Conversation 分页 — 按 iter 隔离，单 iter > 50 才分页

**用户确认**。conversation 不再是全局时间线，而是按 iter 切片。单 iter 消息少（5-15 条），通常无需分页。

罕见情况（scout setup 阶段多次 ask_user）单 iter > 50 条 → 分页 50。

### 决策 9：放弃"完整回放模式"

**用户确认**。snapshot + iter 切换 + sidecar API 覆盖所有查看需求。维护两套刷新逻辑成本高，不值得。

调试需求靠后端日志 + 直接查 events.jsonl 满足。

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| Snapshot 构造与事件流竞争 | seq_cursor + reducer 幂等审计（决策 2） |
| Sidecar 写入失败导致 snapshot 不一致 | fail loud + emit `snapshot.stale` + 前端提示 |
| Reducer 不幂等导致重复事件污染 | Phase 1 实施前先审计 + 单测覆盖所有 reducer |
| 旧 run fallback 性能差 | API 层缓存聚合结果（5 分钟 TTL）；前端显示"加载历史中" |
| 24h run events.jsonl 过大 | 按 iter 分片（决策 5） |
| 历史 iter API 被滥用（爬取整个 run） | rate limit + 单次最多返 100 iter |
| Conversation 按 iter 隔离破坏跨 iter 上下文 | scout setup 归 iter 0；同一 cycle 内的 ask_user 自然在同一 iter |
| cycle 边界判断错误（planner 完成但 selector 没重新进） | 用 node_invocation_counts 严格推导 iter 号，加单测 |

---

## 工作量与排期

| Phase | 工作量 | 价值 | 优先级 |
|---|---|---|---|
| 1 事件分层 + Snapshot | 4-5 天 | 解决刷新慢（根治） | **P0** |
| 2 Cycle iter 持久化 | 2-3 天 | 多轮可追溯基础 | **P1** |
| 3 前端 iter 下拉 + Conversation 隔离 | 3-4 天 | UI 体验闭环 | **P1** |
| 4 Fitness 全量 + Chart 按需 | 2 天 | 趋势图完整可见 | **P2** |
| **总计** | **11-14 天**（2-3 周） | 长 run 体验根治 | — |

Phase 1 独立可上线（刷新慢立即解决）。Phase 2-4 按需排。

---

## 与既有计划的关系

- **包含**：原问题 #4（CRITICAL_EVENT_TYPES 错分类）的"方案 A 重分类"成为 Phase 1 第一步
- **包含**：原问题 #5（activateRun 加 showLive）是 Phase 1 前置 surgical fix（独立修，不阻塞本计划）
- **不冲突**：阶段 3 工具结果截断（`2026-06-16-tooling-token-phase-plan.md`）独立推进，本计划专注 replay 架构
- **依赖**：ws-seq-cursor（`2026-05-30-ws-seq-cursor.md`）的 since_seq 机制是 Phase 1 基础

---

## 后续延展（不在本计划内）

- **跨 run 对比**：基于 fitness_history 全量，可扩展"两个 run 的 fitness 曲线对比"功能
- **自动 replay 录制**：把某个 iter 的完整事件流打包导出，用于离线分享 / bug 报告
- **Snapshot 增量推送**：WS 不只推 L1 事件，还推送 snapshot diff（如 todo 变更），减少前端 reducer 工作

这些是长 run 架构落地后的自然延展，单独立项。

---

## 关联文档

- 问题起源：[`2026-06-16-nas-run-findings-and-arch-issues.md`](./2026-06-16-nas-run-findings-and-arch-issues.md)
- 上一版刷新方案：[`2026-05-30-ws-seq-cursor.md`](./2026-05-30-ws-seq-cursor.md)（since_seq 机制）
- 既有 sidecar 设计：[`2026-05-27-backend-owned-data-persistence.md`](./2026-05-27-backend-owned-data-persistence.md)
- AppView 重构：[`2026-06-12-appview-hydration-refactor.md`](./2026-06-12-appview-hydration-refactor.md)（hydration 流程基础）
- memory: `token-stats-vs-context-window.md` / `tooling-ask-user-defects.md`
