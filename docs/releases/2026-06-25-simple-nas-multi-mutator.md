# simple-nas 多方向专属 mutator 改造（路径 C）

- **日期**: 2026-06-25
- **类型**: 功能扩展 + 重构
- **关联**: [plan](../plans/2026-06-25-simple-nas-multi-mutator.md) · ask_user bug 修复前置依赖（commit `9288dc6`）
- **Commits**: `e5aaab0 → f8ba01e`（9 个，含 plan + baseline + 7 改造 + review fix）

## 背景

用户跑 simple-nas（MNIST）发现两个核心问题：

1. **ask_user 死循环**：setup agent 反复问同一问题 3 次。根因不是内存里记录的"刷新再问 / 60s 超时"老缺陷，而是新 bug —— `assemble_answer` 在 `valid_values` 集合查不到前端发回的 label，直接丢弃，返回空字符串，agent 以为没回答又调 ask_user。已在 commit `9288dc6` 单独修复（label↔value 双向映射）。

2. **单 mutator 串行 → 多方向并行**：原 simple-nas 一个 mutator 节点跑一个 variant。用户要求：
   - 每个变异方向一个专属 mutator（structural / hyperparam / lr / compute）
   - setup 阶段用户 multi_select 选方向
   - 未选方向的 mutator 不参与运行
   - 每个 mutator 内部仍可 sub_agent 并发验证（同方向多 strategy）

## 设计决策

**路径 C（mutator 自跳过）** —— 三条路径对比后的选择：

| | A 双阶段编译 | B 扩展 routing multi-target | **C mutator 自跳过** ✓ |
|---|---|---|---|
| DAG 形态 | setup 单跑→裁剪→编译剩余 | conditional 多目标路由 | 静态 4 mutator，guard 自跳过 |
| 核心 harness 改动 | 大（拆 workflow_runtime） | 中（routing.py/builder.py） | **零** |
| 影响面 | 全局执行模型 | 全局 routing | 仅 simple-nas |
| 工作量 | 3-5 天 | 1.5-2 天 | **0.5-1 天** |

路径 C 用 LangGraph 原生 fan-out / fan-in：selector 静态 fan-out 到 4 个 mutator，4 个 mutator 静态 fan-in 到 analyzer。每个 mutator 头部 guard 检查 `active_directions` 是否含自身方向，未选则立即返回 `skipped: true`，不创建 variant 目录。

**为什么不用 GraphMutator 动态 DAG**：GraphMutator 是 compile-time（`workflow.py:130` 在 compile() 里跑一次），不是 runtime。无法在 setup 跑完后改 DAG。强行做要拆 workflow_runtime 两段编译，违背 surgical。

## 做了什么

### Task 1 — workflow.json DAG 重构
- 删除单 mutator 节点
- 新增 4 个方向 mutator：`mutator_structural` / `mutator_hyperparam` / `mutator_lr` / `mutator_compute`，均 `after: [selector]`
- analyzer 改 `after: [4 mutator]`（LangGraph 静态 fan-in + barrier join）
- 每个 mutator schema 加 `skipped: bool` required；nullable 字段（vid/status_path/variant_dir）在 skipped 时为 null
- analyzer schema 加 `evaluated_directions: array[str]` required

### Task 2 — selector MD 改造
- 废弃"分配单方向"逻辑
- 新职责：选 parent（贪心 best promising）+ **透传** setup.json 的 `active_directions`（不做策略判断）
- SelectorResult schema：删 `direction`，加 `active_directions: array[str]`

### Task 3 — 4 个方向专属 mutator MD
- 每个 MD 含 Step 0 Guard：读 selection.json 的 `active_directions`，自身方向不在 → 立即返回 skipped result（无副作用）
- 方向职责互斥：structural（替换核心算子）/ hyperparam（不动 model.py，改 batch/optimizer）/ lr（专注 lr 家族）/ compute（loss/数据增强）
- 每个 MD 允许 sub_agent 并发验证（同方向多 strategy，K ≤ 3）
- 删除原 `mutator.md`

### Task 4 — analyzer MD 改造（fan-in + 过滤 skipped）
- 输入从单 mutator 改为 4 个 `mutator_<direction>` outputs
- Step 0 过滤 skipped=true 的结果（不进 tree/experience/评估）
- tree.json 更新策略：fan-in 后 analyzer 是唯一写者，一次原子写回 K 个节点（**无 flock 需要**）
- 决策：任一 target_met → pass / 全 over_budget → pass / 否则 fail（→ selector cycle）

### Task 5 — setup MD 加 ask_user multi_select 问方向
- Step 3 用 ask_user multi_select 问用户选哪些方向
- 4 options（structural/hyperparam/lr/compute），`allow_custom_input=false`
- setup.json 加 `active_directions` 字段（用户选的子集），保留 `directions` 全集做兼容

### Task 6 — helpers 静态检查 + vid 命名修复（**plan 外发现**）
- 静态检查通过：mutator MD 无 tree.json 写操作 / analyzer 串行写 / helpers 不依赖 vid 格式 / running.jsonl 单行 ≤ 232 字节 << PIPE_BUF 4096（POSIX 保证 O_APPEND 原子）
- **发现并修复 plan 外的并发风险**：原 mutator MD 用"从 tree.json 数节点推 vid"（v1, v2, v3...），4 个 mutator 并发读会算出**相同 vid**，互相覆盖 variant 目录
- 修复：vid = `<direction>_<iter>`（如 `structural_3`），全局唯一无需 lock

### Review 修复 — 5 项问题
按 review 报告修复：

| 严重度 | 问题 | 修复 |
|---|---|---|
| CRITICAL | `direction_to_agent` 是 dead code（to_dict 不保留 + agent MD 都不查） | 删除字段；setup.md 顶部加 V1 固定方向说明 |
| HIGH | mutator guard 路径 `<N>` 字面量 python open() 必失败 | 改 `${N}` bash 替换，明示 N 来源 |
| M1 | mutator schema `direction` 字段 anyOf:[string,null] 与描述矛盾 | 改 `type:string`（not nullable） |
| M2 | setup ask_user 用 Python 函数语法风格 | 改自然语言 + JSON/markdown 块 |
| M3 | selector 首轮 experience.md 缺失未明示处理 | 加 `[ -f experience.md ] \|\| FIRST_ITER` 检测 |

## 偏离 plan 处

1. **vid 命名修复（Task 6 内）**：plan 没考虑 4 mutator 并发算 vid 冲突，Task 6 静态检查时发现并修复。vid 从递增整数改为 `<direction>_<iter>`，无 lock，helpers 无需改动（vid 是字符串，无格式约束）。

2. **5 项 review 修复**：plan 写完后做了一次完整 review，发现设计与实现不一致 / 鲁棒性不足的 5 个问题，全部修复。详见上表。

3. **Task 7 端到端验证部分延后**：完整 e2e 需要 DeepSeek API key + UI + MNIST 训练资源。worktree 里只完成了 compile + LangGraph 拓扑验证，真实 e2e 留给用户合并后跑（环境 API key 缺失，见下）。

## 验证结果

### 已完成（worktree 内）
- ✅ `Workflow.compile()` 成功编译为 `CompiledStateGraph`
- ✅ LangGraph 拓扑：11 节点 15 边，selector 静态 fan-out 4 mutator，4 mutator 静态 fan-in analyzer，analyzer conditional pass/fail/terminate 三分支正确
- ✅ Task 1-6 每步静态验收通过（schema 字段、严禁条款、guard shape、并发安全 grep）
- ✅ 5 项 review 修复后再次全套验收，无回归（compile + 拓扑 + schema 关键字段）

### 待用户跑（需 API + UI + 训练资源）
- ⏳ 端到端跑 simple-nas（MNIST），用户 multi_select 选 2 方向
- ⏳ 验证：ask_user 只问 1 次 / 未选 mutator skipped<5s / 选的方向有 variant 产物 / tree 正确累积 / reporter 输出
- ⏳ `make lint-runs`

## Commit SHAs

```
f8ba01e refactor: 5 项 review 问题修复
639a3fb fix: vid 命名 <direction>_<iter> 避免并发冲突
8e4f7c2 Task 5: setup ask_user 问方向
412ce65 Task 4: analyzer fan-in
6621a5c Task 3: 4 mutator MD
374ebec Task 2: selector 透传 active_directions
9b45758 Task 1: workflow.json DAG 重构
956884f baseline import
e5aaab0 plan
```

## 关联

- Plan: [`docs/plans/2026-06-25-simple-nas-multi-mutator.md`](../plans/2026-06-25-simple-nas-multi-mutator.md)
- ask_user bug 前置修复: commit `9288dc6`（fix(tools): label-as-value 回归）
- 已合并到 `fix/pre-post-tooluse-framework-issues` 分支（fast-forward，2026-06-25）
