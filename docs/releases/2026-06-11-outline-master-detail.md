# Release Notes — 2026-06-11 Outline + Master-Detail Conversation View

**Branch:** `worktree-outline-master-detail`
**Plan:** `docs/plans/2026-06-11-outline-master-detail.md`
**Commits:** `f5b9e33` `5f5feba` `91bd792` `9dda70f` `d90e3b8` `4cb50ed` `67b65bd` `4b62044` `87923cb` `caaca61` `2a61339` `cc7f17d` `3a41179` `46b51ec` `9e7a09f` `f6f2a45` `fb8eb37` `08c7dc5` `0f5974f` `f4ad522`

### Problem 2 (Show thinking 双击→单击)
- **修改** `AgentMessage.tsx` `ThinkingBlock` — 加 `defaultOpen` prop
- **修改** `ScopedConversationTab.tsx` `AgentMsgItem` — 传 `defaultOpen={true}`，单击即展开

### Phase 1: Iteration tracking (loop disambiguation foundation)
- **新增** `ConversationMessage.iteration?: number` — 1-indexed 循环迭代编号
- **新增** `ConversationState.currentIterationByNode` + `setCurrentIteration` action
- **修改** `nodeHandlers.ts` — `node.started` 时递增迭代计数（在 `addAgentMessage` 之前）
- **修改** `conversation.ts` — 5 个 message-creating action 戳记 `iteration` 字段
- **修改** `conversationStore.ts` legacy `useConversationStore` — 同步加入 state + setter
- **测试** `conversationStore.iteration.test.ts` + `nodeHandlers.iteration.test.ts` + `conversationMessage.types.test.ts`

### Phase 2: Outline 派生层
- **新增** `outline/types.ts` — discriminated union `OutlineItem` / `AgentActivity` / `OutlineStatus` / `OutlineBadge`
- **新增** `outline/deriveOutlineItems.ts` — 纯派生函数（store snapshot → ordered OutlineItem[]）
- **新增** `outline/useAgentOutline.ts` — React hook + memoize
- **测试** 9 个 derivation 测试覆盖：empty/ordering/idle/loop/waiting-for-user/running+step/retry/tokens/legacy

### Phase 3: 选择状态
- **新增** `outline/outlineStore.ts` — `selectedKey` / `autoFollow` / `viewMode`
- **新增** `outline/useAutoFollowSelection.ts` — 优先级 waiting-for-user > running
- **测试** 6 个 store 测试

### Phase 4: UI 组件
- **新增** `outline/OutlineItemRow.tsx` — Linear-style 紧凑行 + 状态图标 + badge
- **新增** `outline/AgentOutline.tsx` — 列表容器 + header + autoFollow toggle
- **新增** `outline/AgentDetailView.tsx` — 单 agent 对话视图（复用 NodeBlockCard + virtualizer）
- **新增** `outline/OutlineMode.tsx` — split-pane 容器（outline 240px + detail flex-1）

### Phase 5: 集成
- **修改** `ScopedConversationTab.tsx` — 导出 `NodeBlockCard` 供 AgentDetailView 复用
- **修改** `ScopedCenterPanel.tsx` — 新增 `ConversationPanel` 包装，Outline/Timeline toggle
- **修改** `viewStore.ts` — `showReplay` / `showLive` 时 reset outlineStore（保留 viewMode 偏好）
- **新增** AgentOutline `j/k` 键盘导航（输入框聚焦时不拦截）
- **新增** useAutoFollowSelection ask_user 进入 waiting 时 toast 提示（transition-only）

### Code review 修复
- **修复** legacy `useConversationStore` 缺 `currentIterationByNode`/`setCurrentIteration` (TS2739)
- **修复** `addFollowupUserMessage` 缺 iteration 戳记（shape consistency）
- **修复** outline retry badge 与 toast/inline card 显示不一致（统一为 `attempt + 1`）
- **修复** outline idle 排序 docstring 与 impl 不符（localeCompare → DAG 插入顺序）
- **修复** nodeHandlers.iteration test 用例不可达（改用 `node.completed` 事件而非 `handleNodeCompleted`）

### 性能契约
- Outline 渲染成本 O(num_agents)，零 per-message 工作
- Detail 只渲染选中 agent 的消息（复用 groupNodes + virtualizer）
- 零新增网络请求 — 全部从现有 scoped stores 派生
- 138/138 测试通过，tsc 零错误

---
