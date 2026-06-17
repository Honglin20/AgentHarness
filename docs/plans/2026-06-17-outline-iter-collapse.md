# Outline Iter Collapse + Node Iter Dropdown

> 日期：2026-06-17
> 状态：方案定稿，待执行
> 起源：[`2026-06-16-long-run-replay-architecture.md`](./2026-06-16-long-run-replay-architecture.md) Phase 3 主体（节点级 iter 下拉抽屉）+ 用户反馈"sidebar list 不该平铺"
> 分支：`main`（建议新开 `feat/outline-iter-collapse`）

---

## 背景

长 loop workflow（NAS：selector / planner / trainer / judger 各跑 N 轮）下，当前 outline 把每个 iter 平铺成独立 row：

```
selector (iter 1)
selector (iter 2)
selector (iter 3)
planner  (iter 1)
...
```

50 iter × 4 agent = 200 行 sidebar list，噪音大、难定位、j-k 导航累。

后端 Phase 2 已就绪（commit `7062d51`）：iter sidecar + iter_index + `GET /runs/{id}/nodes/{node}/iters[/n]` + snapshot mirror iter_index + `nodes_latest[node_id].latest_iter`。**纯前端工作**。

---

## 目标态 UX

### Sidebar（折叠）

```
┌─ Agents ──────────┐
│ selector   ⇡3     │   ← 同 nodeId 合并 1 行，⇡N 标 iter 数（>1 才显示）
│ planner    ⇡3     │
│ trainer    ⇡3     │
│ judger     ⇡2     │
└───────────────────┘
```

- 同一 nodeId 的多 iter **折叠成一行**（用最新 iter 的 status / activity 渲染）
- 单 iter 的 agent 行为不变（无 ⇡ badge）
- j/k 导航在折叠后的行间跳

### Detail Panel（iter dropdown）

```
┌─ selector  ⌄ Iter 3 (latest) ────────┐  ← 顶部 iter dropdown
├──────────────────────────────────────┤
│  [NodeBlockCard for iter 3 content]  │
│   Input / Tool calls / Output        │
│   Conversation filtered to iter 3    │
└──────────────────────────────────────┘

点击 dropdown → 展开：
   ✓ Iter 3 (latest) — completed — 8.2s
     Iter 2          — completed — 7.5s
     Iter 1          — completed — 6.8s

选 Iter 2 → 抽屉刷新到 iter 2 内容 + conversation 自动跟着切
```

- 默认显示 `latestIter`
- 切换 dropdown → 整个 detail（input / tools / output / conversation）切到选中 iter

### 不做的

- ❌ DAG view 节点 `latestIter` 标记 —— 独立 PR，避免 scope creep
- ❌ 全局 conversation iter filter（phase 3b 已做）—— 保留，与节点级 filter 叠加
- ❌ 后端任何改动 —— Phase 2 完全就绪

---

## 实施路径

### Phase 1 — 派生层：`groupOutlineByNode`

**目标**：在 view 层把 `OutlineItem[]` 按 nodeId 折叠成 `OutlineGroup[]`，不动 sidecar / deriveOutlineItems。

**改动**：

新文件 `frontend/src/components/outline/groupOutlineByNode.ts`：

```ts
export interface OutlineGroup {
  nodeId: string;
  name: string;
  /** 折叠组用最新 iter 的 status / activity / badges 渲染 sidebar 行 */
  latest: OutlineItem;
  iterCount: number;
  latestIteration: number;
  /** 全部 iter（按 iteration 升序），dropdown 用 */
  iters: OutlineItem[];
  /** 沿用 OutlineItem.order —— 取组里最小（最早出现的）order */
  order: number;
}

export function groupOutlineByNode(items: OutlineItem[]): OutlineGroup[] {
  // 1. 按 nodeId groupBy
  // 2. 每组内按 iteration 排序
  // 3. latest = max iteration 的 item
  // 4. order = min(orders) —— 保持首次出现的顺序
}
```

**测试**：
- 单 iter agent → group 里 iterCount=1，latest=自身
- 多 iter agent → latest=最高 iter，iters 升序
- 顺序保持首次出现序
- 空数组 → 空数组

**工作量**：0.5 天

---

### Phase 2 — UI 层：`OutlineGroupRow` + `NodeIterSelector`

**目标**：两个新组件。

#### 2a. `OutlineGroupRow.tsx`

替代当前 `OutlineItemRow`（在 `AgentOutline.tsx` 内 map 时用）：

```tsx
function OutlineGroupRow({ group, selected, onSelect }: Props) {
  return (
    <button
      onClick={() => onSelect(group.nodeId)}
      className={selected ? "bg-blue-500/10" : ""}
    >
      <StatusDot status={group.latest.status} />
      <span>{group.name}</span>
      {group.iterCount > 1 && (
        <span className="badge" title={`${group.iterCount} iterations`}>
          ⇡{group.iterCount}
        </span>
      )}
    </button>
  );
}
```

- 复用 `OutlineItemRow` 的视觉风格（status dot / activity subtitle / 左 border 高亮）
- badge 风格：`⇡N`，鼠标 hover 显示 tooltip "N iterations"
- `selected` 判断从 `selectedKey === item.key` 改为 `selectedNodeId === group.nodeId`

#### 2b. `NodeIterSelector.tsx`（dropdown）

```tsx
function NodeIterSelector({ nodeId, iterCount, latestIter }: Props) {
  // iter_index 已在 snapshot mirror，从 workflowStore.nodes_latest[nodeId] 读
  // 单 iter 直接渲染 "Iter 1"，不显示 dropdown trigger
  if (iterCount <= 1) return <span>Iter 1</span>;

  return (
    <Dropdown>
      <DropdownTrigger>
        Iter {selectedIter} {selectedIter === latestIter && "(latest)"} ▾
      </DropdownTrigger>
      <DropdownMenu>
        {iters.map((it) => (
          <DropdownItem key={it.iter} onClick={() => selectIter(nodeId, it.iter)}>
            Iter {it.iter} {it.iter === latestIter && "(latest)"} — {it.status}
          </DropdownItem>
        ))}
      </DropdownMenu>
    </Dropdown>
  );
}
```

- iter 列表来源：snapshot 里的 `iter_index[nodeId]`（已被 Phase 2 mirror 进 snapshot）
- 选中状态：从 outline store 的 `selectedIterByNode[nodeId]` 读，缺省 = `latestIter`

**工作量**：1 天（含 dropdown 交互细节 + 边界）

---

### Phase 3 — Store 重构：selection 二元组

**目标**：解耦 "选中的 agent" 和 "选中的 iter"。

**改动 `outlineStore.ts`**：

```ts
interface OutlineState {
  // 删除：selectedKey: string | null
  selectedNodeId: string | null;                    // 当前选中的 agent
  selectedIterByNode: Record<string, number>;       // 每个 agent 用户选的 iter
  autoFollow: boolean;
  viewMode: OutlineViewMode;

  select: (nodeId: string | null, keepAutoFollow?: boolean) => void;
  selectIter: (nodeId: string, iter: number) => void;  // 新增
  // 其余不变
}
```

- `select(nodeId)` 切换 agent，**不重置 selectedIterByNode[nodeId]**（保留用户之前选的 iter，或回退到 latest）
- `selectIter(nodeId, iter)` 仅改 iter，不动 nodeId
- agent 切换时 `AgentDetailView` 读 `selectedIterByNode[nodeId] ?? latestIter`

**兼容**：所有读 `selectedKey` 的地方改为 `selectedNodeId`。grep 范围：
- `AgentOutline.tsx` / `OutlineItemRow.tsx` → `OutlineGroupRow.tsx`
- `OutlineMode.tsx`（用 selectedKey 找 item → 改用 selectedNodeId 找 group）
- `useAutoFollowSelection.ts` / `useWaitingAgentToast.ts`（follow 目标从 item 改为 group）
- 测试：`outlineStore.test.ts` 等

**工作量**：1 天（含全部 callsite 迁移 + 测试更新）

---

### Phase 4 — 集成：`AgentDetailView` 顶部插 dropdown

**改动 `AgentDetailView.tsx`**：

```diff
  export function AgentDetailView({ nodeId }: Props) {       // iteration prop 删掉
+   const selectedIter = useOutlineStore(
+     (s) => s.selectedIterByNode[nodeId] ?? latestIterFromSnapshot(nodeId),
+   );
+   const iterCount = useWorkflowStore((s) => s.iterIndex?.[nodeId]?.length ?? 1);

    // ...
    const filtered = useMemo(
-     () => allMessages.filter((m) => m.nodeId === nodeId && (m.iteration ?? 1) === iteration),
+     () => allMessages.filter((m) => m.nodeId === nodeId && (m.iteration ?? 1) === selectedIter),
      [allMessages, nodeId, selectedIter],
    );

    return (
      <div ref={scrollRef} className="h-full overflow-y-auto">
+       <div className="sticky top-0 z-10 border-b bg-app-bg-primary px-6 py-2">
+         <NodeIterSelector nodeId={nodeId} iterCount={iterCount} latestIter={...} />
+       </div>
        <div className="px-6 py-3">
          {/* 既有 NodeBlockCard */}
        </div>
      </div>
    );
  }
```

- `iteration` prop 从 `OutlineMode` 注入 → 改为内部从 store 读
- `NodeBlockCard` 的 `iteration` prop 跟着改

**工作量**：0.5 天

---

### Phase 5 — `useAgentOutline` 返回 group + autoFollow 适配

**改动**：

```diff
  export function useAgentOutline(): OutlineGroup[] {       // 返回类型改
    // ...
-   return useMemo(() => {
-     if (sidecarItems !== null) return sidecarItems;
-     return deriveOutlineItems(nodes, messages, todos);
-   }, [sidecarItems, nodes, messages, todos]);
+   return useMemo(() => {
+     const items = sidecarItems !== null
+       ? sidecarItems
+       : deriveOutlineItems(nodes, messages, todos);
+     return groupOutlineByNode(items);
+   }, [sidecarItems, nodes, messages, todos]);
  }
```

`useAutoFollowSelection.ts`：当前 follow `items.find(i => i.isLatestIter && i.status === 'running')`。折叠后改 follow `groups.find(g => g.latest.status === 'running')`，逻辑等价。

`useWaitingAgentToast.ts`：同上，基于 `group.latest.activity` 判断。

`AgentOutline.tsx` 的 j-k 导航：在 `OutlineGroup[]` 上跳，行为符合直觉。

**工作量**：0.5 天

---

## 关键决策

### 决策 1：折叠在 view 层做，不动数据层

sidecar outline item 已经按 iter 拆分（每个 iter 一行写入 `{run_id}+outline.json`）。**不动 sidecar schema**，只在 `useAgentOutline` 末端加 `groupOutlineByNode` 派生。

**理由**：
- sidecar 按行追加效率高（cycle 跑一轮写一行）；改 schema 要么破坏追加模式，要么冗余存储
- view 层 group 是 O(N) 一次 memo，性能可接受（N=agent×iter，200×4=800 items 是上限）
- live 模式 `deriveOutlineItems` 也无需改

### 决策 2：`selectedIterByNode` 是 Record，不是单值

用户切到 planner 看了 iter 2，又切到 trainer 看了 iter 5，再切回 planner 应该还是 iter 2（保留用户选择）。

**否决**：单值 `selectedIter`（每次切 agent 重置）—— 用户体验差，需要反复点 dropdown。

### 决策 3：默认 latest，不是 "auto"

`selectedIterByNode[nodeId]` 缺省时回退到 `latestIter`。**不做** "auto-follow latest" 模式（即跑新 iter 时自动切到新 iter）。

**理由**：
- 跑新 iter 时用户大概率在看别的 agent，自动切换打断节奏
- 跑完后用户主动切 latest 是显式动作，心智清晰
- autoFollow（agent 级别）已经覆盖了"跟随当前活跃 agent"，iter 级别不再叠加

### 决策 4：单 iter agent 不显示 dropdown trigger

`iterCount === 1` 时 detail panel 顶部直接显示 "Iter 1"（静态文本），不渲染 dropdown。避免无意义的可点击 UI。

### 决策 5：iter dropdown 数据来自 snapshot mirror，不调 API

`iter_index` 已经在 Phase 2 mirror 进 snapshot（`incremental_save.py:129-158`），前端 hydrate 时已在 `workflowStore.iterIndex`。**不调** `GET /nodes/{node}/iters`，避免首次打开 dropdown 时延迟。

只有用户切到某个具体 iter 时，conversation filter 是从已 hydrate 的 messages 按 iter 字段过滤，**也不调 API**。`GET /nodes/{node}/iters/{n}`（详细 tool calls 等）按需调，**Phase 3 主体以外的需求**（例如展示 input_prompt / system_prompt 全文），不在本 plan 范围。

---

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| autoFollow 逻辑跟着 group 改，可能漏掉边角 case（retry 时 follow 错 iter） | 测试覆盖：retry / waiting-for-user / 新 iter 启动 三种 trigger |
| `selectedIterByNode` 在 agent 消失后不清理 → 内存泄漏 | 单 run 内 agent 数固定（DAG 决定），上限可预期；run switch 时整个 store reset |
| 旧 run 无 snapshot（pre-Phase-1）→ 没有 `iter_index` | 兼容：`iterCount ?? 1`，dropdown 不显示，行为退化为现状（每个 iter 一行） |
| sidecar 写入顺序：iter 还没写完 sidecar 但 outline sidecar 已有该 iter 条目 | outline sidecar 由 `deriveOutlineItems` 从 messages 派生，messages 与 iter sidecar 同源（事件流），时序一致 |
| iter dropdown 切换时 conversation filter 闪烁 | `useMemo` 依赖 `selectedIter`，filter 是 O(messages) 同步计算，<1ms 无闪烁 |
| j-k 导航行为变化（item → group），用户肌肉记忆失效 | 行为符合直觉（"少跳"），文档里写一行 changelog |

---

## 测试计划

### 单元测试

- `groupOutlineByNode.test.ts`（新）：单 iter / 多 iter / 顺序保持 / 空数组 / 同 nodeId 不同 status
- `outlineStore.test.ts`（改）：`select` / `selectIter` / `selectedIterByNode` 缺省回退 latestIter
- `NodeIterSelector.test.tsx`（新）：单 iter 不渲染 trigger / 多 iter 渲染 / 点击选项触发 selectIter

### 集成测试

- `AgentOutline.test.tsx`：sidebar 渲染折叠后的行，⇡N badge 仅在 iterCount>1 显示
- `AgentDetailView.test.tsx`：顶部 dropdown / 切 iter 后 messages filter 切换
- `useAutoFollowSelection.test.ts`：follow group.latest 而非 item

### 端到端验证（手工）

- 跑 NAS workflow 3 iter，确认 sidebar 显示 4 行（selector / planner / trainer / judger）
- 点击 selector → detail 默认显示 iter 3
- dropdown 切到 iter 1 → conversation 切换
- 切到 planner → 显示 planner iter 3（不继承 selector 的 iter 1）
- 切回 selector → 仍是 iter 1（保留用户选择）
- 刷新页面 → 状态正确恢复

---

## 工作量与排期

| Phase | 内容 | 工作量 |
|---|---|---|
| 1 | `groupOutlineByNode` 派生 + 测试 | 0.5 天 |
| 2a | `OutlineGroupRow` 组件 | 0.5 天 |
| 2b | `NodeIterSelector` dropdown | 0.5 天 |
| 3 | store 重构 + callsite 迁移 | 1 天 |
| 4 | `AgentDetailView` 集成 | 0.5 天 |
| 5 | `useAgentOutline` + autoFollow 适配 + 测试 | 0.5 天 |
| **总计** | | **3.5 天** |

可拆为 2 个 PR：
- PR1：Phase 1+2+3（数据 + 组件 + store，可独立 review）
- PR2：Phase 4+5（集成 + 适配，依赖 PR1）

---

## 关联文档

- 起源：[`2026-06-16-long-run-replay-architecture.md`](./2026-06-16-long-run-replay-architecture.md)（Phase 3 主体）
- Phase 2 后端实现：commit `7062d51` + `9f2e61b`
- 现有 outline 数据模型：[`2026-06-12-outline-iter-isolation.md`](./2026-06-12-outline-iter-isolation.md)
- AppView 重构（hydration 基础）：[`2026-06-12-appview-hydration-refactor.md`](./2026-06-12-appview-hydration-refactor.md)
