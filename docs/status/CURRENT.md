# Current Task

**当前任务**: NAS workflow 污染根因修复 — 已落地并验证
**状态**: ✅ 跑通端到端，FINAL_REPORT.md 生成；待 commit
**日期**: 2026-06-13
**分支**: `main`

## 必读文件

- `~/.claude/projects/-Users-mozzie-Desktop-Projects-AgentHarness/memory/nas-workflow-requirements.md` — NAS 最终架构决策
- `workflows/nas/` — 9 agents + 7 helpers + workflow.json
- `projects/mnist/` — 测试项目（sklearn digits MLP）
- `CLAUDE.md` — 协作规则

## 已验证完成（本轮）

**实跑 NAS 端到端跑通**：scout → selector → planner → trainer (2 strategy 并发) → judger → analyzer → validator (pass) → refiner → reporter。FINAL_REPORT.md 推荐 GELU 改造（acc 78.89% → 96.39%, latency 0.00165ms ≤ 0.002 target）。

### 修复清单

- ✅ **TodoTool name bug**：`PydanticAITool` 没传 `name=self.name`，最终暴露给 LLM 的是 inner 函数名 `'todo'`（小写）。reminder 说"调 TodoTool" 但 toolset 里只有 `todo`，LLM 找不到。修：`todo.py:305` 加 `name=self.name`
- ✅ **`defaults.py` 无条件注册 TodoTool**：之前 `if event_bus:` 才注册，移除条件
- ✅ **step_gate / reminder 文案对齐**：4 处硬编码 `'todo(op=...'` → `'TodoTool(op=...'`（step_gate.py / todo_reminder.py / todo.py）
- ✅ **Fix A: root agent fail → terminate**：`node_factory.py` except 块检测 `after == []` 时 raise，避免 scout fail 后 cycle 卡死到 langgraph recursion limit
- ✅ **Fix B: `inputs.max_iters` → `wf.max_iterations`**：`run_nas.py` 启动时从 inputs 同步 cycle cap
- ✅ **9 个 NAS agent MD 头部加「工具与文件约束」段**：TodoTool 必须、业务文件写 session_dir、路径用 init_session.py 输出值

## 残留问题（不阻塞，后续处理）

- [ ] **trainer sub_agent 训练产物污染 cwd**：worktree 机制下 cwd 是真实路径，sub_agent 写 `baseline.pt` / `eval_result*.json` / `train_metrics*.json` 到 cwd 而非 session_dir
- [ ] **MCP cleanup bug**：workflow 完成后 MCP bridge disconnect 卡住，僵尸子进程需手动 kill。独立 harness bug
- [ ] **ONNX 时延测量需求**（暂搁置）

## 旁路任务（不阻塞）

- AppView 重构代码完成，等用户浏览器手测验收（5 场景）→ 见 `docs/releases/2026-06-12-appview-hydration-refactor.md`
