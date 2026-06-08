# NAS Workflow 整体架构

> 状态：待实现

## 目标

用户给一个深度学习项目路径，workflow 全自动完成模型结构优化（不改蒸馏/量化），迭代直到延迟达标且精度保持。

## Orchestrator Pattern

参考 Claude Code 的单 agent REPL 循环。不做动态 DAG fan-out——由一个 orchestrator agent 在 tool-calling 循环中完成所有工作：

```
NAS Orchestrator Agent (单节点循环体)
│
├── Phase 1: 分析项目 → todo(op="create") 规划步骤
├── Phase 2: 制定策略 → todo(op="update") 推进
├── Phase 3: 并行执行策略 → task(op="spawn") × N → task(op="output") 收集结果
├── Phase 4: 评测并判断收敛 → 写 MD 历史 → 决定是否 loop back
└── 达标 → 生成报告
```

### 为什么不选动态 DAG

| 动态 DAG fan-out | Orchestrator Pattern |
|------------------|---------------------|
| LangGraph 编译时确定拓扑 | agent 运行时决定策略数量 |
| 前端 DAG 可视化和动态拓扑冲突 | 前端只看 TODO + Task 列表 |
| Debug 困难（节点数在变） | 所有状态在 agent context 里 |
| 需要重新 compile | 一次 compile 无限 loop |

### DAG 只有 1 个节点

```json
{
  "name": "nas-iterative",
  "agents": [{"name": "nas_orchestrator", "after": []}]
}
```

## 工具链

| 工具 | 角色 | 状态 |
|------|------|------|
| `todo` | 步骤规划 + 进度追踪 | ✅ 已实现 |
| `task` | 后台任务管理（训练/评测） | ⬜ 待实现 |
| `parallel_tasks` | 并发执行 + worktree 隔离 | ⬜ 待实现（组合 todo + task） |
| `write_history` | 3 层 MD 历史记录 | ⬜ 待实现 |
| bash | 已有，执行训练脚本 | ✅ |
| sub_agent | 已有，委托子任务 | ✅ |

## 3 层 MD 历史

```
<HISTORY.md>                    ← L1 索引：每轮一句话 + 链接
├── iter_0/
│   ├── SUMMARY.md              ← L2 简述：改了什么、结果如何
│   ├── strategy_prune/
│   │   ├── model.py            ← L3 事实：真实代码
│   │   ├── diff.patch          ← L3 事实：与基线的 diff
│   │   └── eval_result.json    ← L3 事实：评测数据
│   └── strategy_distill/
│       └── ...
├── iter_1/
│   └── ...
```

由 orchestrator 在每轮结束时调用 bash 工具写入。不需要特殊框架支持。

## 循环终止

不依赖 LLM 判断"达标了"，用代码逻辑：

```python
# orchestrator MD 中定义
## 收敛判断
执行评测后，比较以下指标：
- 精度下降 ≤ 1%（vs 基线）
- 推理延迟降低 ≥ 20%（vs 基线）
如果两项都满足 → 调用 todo 标记所有步骤完成，输出最终报告
如果迭代超过 5 轮 → 停止并输出当前最优结果
```

orchestrator 按规则判断，不需要 `convergence_config`——它自己读评测 JSON 做数值比较。

## 实现优先级

1. ✅ TODO 工具 — 已完成
2. ⬜ Task 工具 — 后台任务管理
3. ⬜ 代码隔离方案 — git worktree + symlink
4. ⬜ NAS Orchestrator Agent MD — 编排 prompt
5. ⬜ 3 层 MD 历史写入 — bash 工具即可
