# Current Task

**删 Timeline 模式 + 重构 Outline 数据流（方案 H）** — Plan 已批准，小步实施中。

Plan：[`/Users/mozzie/.claude/plans/buzzing-bouncing-reef.md`](../../../.claude/plans/buzzing-bouncing-reef.md)

## 背景

REPLAY 模式下 outline detail 显示残缺数据。根因不在前端渲染，而在数据流架构：
- main record 的 `conversation` 字段从 Bus FIFO buffer 投影，长 run 残缺
- 前端 hydrate 用 cursor fetch（默认 limit=50）灌 store，覆盖不全
- `AgentDetailView` 的 `hasLiveMessages` 误判 → 跳过 sidecar fetch
- 多 sink 重复存储（buffer / events sidecar / iter sidecar / main record）

之前方案 G（server 端 rebuild conversation）已落地但**无效** —— 前端 detail endpoint 把 conversation strip 掉，cursor 还截断 50 条。

## 用户 4 条验收标准

1. 每个 agent 当前 iter 下显示完全
2. 每个 agent 不同 iter 都可以正常访问，显示完全
3. 执行效率高，多轮 iter 下不卡顿（量化）
4. 重复 iter 后对话折叠，可通过 tab 下拉栏选取特定 iter

## 小步实施（按顺序，每步独立 commit + 验收）

- [ ] **Step 0**：Baseline 测量（cursor payload / hydrate 耗时 / 切 agent 耗时 / WS catch-up）
- [ ] **Step 1**：`decideStrategy` 不依赖 conversation（改用 `result.trace`）
- [ ] **Step 2**：`pendingQuestionId` 从 events sidecar 反推（替代 conversation reverse-fill）
- [ ] **Step 3**：`outputStore.texts` 不再构建（无消费者）
- [ ] **Step 4**：`toolCallStore` 改 lazy + 新 endpoint `/runs/{id}/tool_calls`
- [ ] **Step 5**：删 hydrate cursor fetch
- [ ] **Step 6**：`AgentDetailView` hasLiveMessages 判定收紧
- [ ] **Step 7**：删 `ScopedConversationTab` + viewMode toggle + cursor 分页字段
- [ ] **Step 8**：End-to-end 量化验证（simple-nas / NAS multi-iter / 性能对比）

## 已完成（前置）

- [x] 方案 G：`harness/persistence/conversation_rebuild.py` + `server/runner.py` final save 调用 + orphan 脚本（保留作为 backend data hygiene，前端读路径绕过但 server 数据完整）
- [x] 8 单测全过 + collectors 28 / phase3 e2e 10 回归全过
- [x] 历史残缺 run 修复（847ab064: 9→126 tool_calls，669c9f86: 4→112）

## 必读文件

- `/Users/mozzie/.claude/plans/buzzing-bouncing-reef.md` — 完整 plan + 8 步细节
- `frontend/src/stores/hydration/hydrateReplay.ts` — Step 1/2/3/5 改造目标
- `frontend/src/contexts/workflow-context/replayEvents.ts` — Step 2/3 改造目标
- `frontend/src/components/outline/AgentDetailView.tsx` — Step 6 改造目标
- `frontend/src/components/conversation/ScopedConversationTab.tsx` — Step 7 删除目标
- `harness/persistence/conversation_rebuild.py` — 方案 G 已落地（backend hygiene）

## 不变量

- iter sidecar (`+iters+<node>+<iter>.json`) 是中间过程的**唯一真相源**
- outline sidecar (`+outline.json`) 是 sidebar 的真相源（replay 模式）
- conversationStore 只在 **live 模式** 由 WS 填，replay 模式启动为空
- Step 1-4 必须在 Step 5 之前完成（过渡态兼容性）

---

## 待办（非 Timeline 任务）

### P3 CliProfile 补完 — 遗留死代码字段

commit `d854db2` 已切换主线（executor → run_cli / shlex 多 token / setting-sources 条件化 / 删 _claude_subprocess.py），但 2 个 CliProfile 字段仍死代码：

- **`profile.translator`** — `harness/engine/claude_code_executor.py:_handle_stdout_line` 仍调全局 `translate()`（L749）而非 `self._profile.translator`。补完后 opencode 等新 profile 才能接自己的 stream translator。
- **`profile.prompt_paradigm`** — `harness/prompts/assembler.py:executor_to_paradigm` 仍硬编码 `{"claude-code": "minimal", ...}` 映射，不读 profile。补完后新 backend 自动选 prompt 范式无需改 assembler。

不动理由：两处都涉及 prompt 核心路径，本次聚焦切换主线 + 修复 ccr code 后端 + .env 缺失 fallback 诉求。下一 PR 候选。
