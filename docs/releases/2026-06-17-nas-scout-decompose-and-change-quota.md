# NAS Workflow: SCOUT 退化 + Planner 变化额度契约

**日期**: 2026-06-17
**Plan**: [`docs/plans/.../flickering-twirling-kay.md`](../../.claude/plans/flickering-twirl-kay.md)（位于 plans 目录，本仓库外）
**Commits**:
- `2cc1b18` — flatten scout subagents into top-level DAG nodes
- `19fdea3` — promote 5 setup subagents to top-level agents + scout → collector
- `6f04716` — change-quota contract 3-layer (schema + helper + judger)
- `2abd7d2` — wire structural_global new_model_path end-to-end

## 背景

NAS workflow 的 SCOUT 阶段把 5 个本应是 DAG 顶层节点的 sub_agent（adapter_generator / domain_analyzer / baseline_runner / tier_planner / metrics_identifier）塞进单个 agent，靠 prompt 协调 3 wave 并发。问题：

1. **中间过程不可见**：sub_agent 只返回字符串 summary，所有 grep/read/smoke/retry 不进 event bus，前端看不到 adapter 怎么生成的、smoke 为什么失败
2. **用 LLM 模拟 DAG**：5 个 sub_agent 的拓扑在编译期就知道（2+1+2 固定），却让 LLM 通过"同一 response issue"模拟并发，违反 rule 5
3. **结构性能力缺失**：smoke 失败只能 ask_user 兜底，没法走 conditional_edges；request_limit 暴涨到 500
4. **planner 范围与契约不匹配**：planner.md 已有"≤3 位置"约束，但全是 prompt 措辞。用户要求 planner 可提"新模型"，但需要**契约级**约束

## 改动

### DAG 拓扑：5 sub_agent → 5 顶层节点

```
project_analyzer (after=[])
   ├── adapter_generator (after=[project_analyzer])
   │       ↓
   │   baseline_runner (after=[adapter_generator])
   │       ↓
   │   ├── tier_planner (after=[baseline_runner])
   │   └── metrics_identifier (after=[baseline_runner])
   └── domain_analyzer (after=[project_analyzer])
   scout (after=[adapter_generator, domain_analyzer, baseline_runner, tier_planner, metrics_identifier])
   selector (after=[scout])
   ... cycle 不变
```

- **SCOUT 退化为 collector**：从 200 行降到 ~100 行，只做 init_session + ProjectAnalysis 转写 + 文件存在性校验 + ScoutResult 输出。删 Wave 1-3 协调 + Step 4.2 helper 重写
- **5 个 subagents/ MD 提升到 agents/ 顶层**：每个有独立 result_type（AdapterGenResult / DomainAnalysisResult / BaselineRunResult / TierPlanResult / MetricsIdentifyResult）
- **adapter_generator 保留 ask_user**（smoke 失败 / dummy_inputs 兜底）；**scout collector 砍掉 ask_user**（cycle 非交互原则从 setup collector 开始生效）
- **request_limit 500 → 200**（5 flat setup nodes × ~5 calls 替代 scout-nested sub_agent budget）

### 变化额度契约（三层）

`StrategyInfo` schema 扩展：
- `hypothesis_type: Literal["parametric", "structural_local", "structural_global"]`
- `change_count: int`（parametric/local: 1..3；structural_global: **强制 =1**）
- `new_model_path: str | None`（仅 structural_global 非 null）
- `new_model_class: str | None`（同 presence）
- `model_validator` 强制 type/count/path 一致性

三层兜底：
- **Layer 1 (schema)**: Pydantic 自动 retry LLM 输出
- **Layer 2 (helper)**: 新建 `validate_manifest.py`，Coder 写完 manifest 后必跑；exit 1 → strategy 丢弃
- **Layer 3 (judger)**: `fitness.py` 加 `_check_contract_violation`（违反 → fitness=0.0）+ `_type_diversity_penalty`（K≥3 且同 type 占比 ≥0.8 → 该 type −0.05）

### new_model_path 端到端

planner hypothesize 新模型 → Coder 写新 .py 文件到 worktree 根 → manifest.new_model_path 指向 → trainer 读 manifest 传 `--model-override-path` / `--model-override-class` 给 `run_strategy.py` → `adapter.get_model(model_override_path=...)` 通过 importlib 动态加载，跳过 `_construct_model`。

**关键设计**：Coder 不动 `_construct_model` body。adapter 是 NAS 团队维护的契约边界，新模型作为独立 .py 文件存在，adapter 通过 override 参数动态选 model class。

### candidate_pool 多样性

- `_push` entry 加 `hypothesis_type` 字段（缺失默认 "parametric" 兼容旧 candidates.json）
- 新增 `--top-k-per-type` 参数（默认 0=关闭；>0 时按 type 分组保留 top-N）
- push 返回值加 `type_distribution` 摘要

## 偏离 plan 处

无重大偏离。minor：
- `MAX_CHANGE_COUNT` 写在 schemas.py 模块常量（plan 推荐），fitness.py / validate_manifest.py 内部 hardcode 同步值 + 注释（保持 helper standalone，不依赖 schemas.py 路径）
- `Type_diversity_penalty` 阈值 0.8 / penalty 0.05 写在 fitness.py 顶部常量，可调

## 验证

- `register.py --check` 15 节点拓扑正确
- `StrategyInfo` model_validator 9 个边界 case 全过
- `fitness.py` 8 个 case（contract_violation + type_diversity）
- `validate_manifest.py` 10 个 case（type enum / change_count / structural_global presence / file existence / ops_length）
- `candidate_pool.py` 5 个 case（type filter / 向后兼容）
- `_adapter_template._load_override_model` + `get_model` override 行为 4 个 case
- `run_strategy.py` argparse 接受 `--model-override-path` / `--model-override-class`

端到端 MNIST demo 跑批待用户验证（涉及真实 PyTorch 训练，不在单测覆盖范围）。

## 影响

- **可见性**：5 个 setup 节点的 grep/read/smoke/retry 全部进入 event bus，前端能看到完整 trace
- **request_limit**：500 → 200（NAS workflow 的 token envelope 减半）
- **planner 探索空间**：可提新模型，但每个 candidate 改动量受 schema/helper/judger 三层约束
- **elite pool 多样性**：默认仍按 fitness 排序，但 `--top-k-per-type > 0` 时保证每 type 至少 N 槽位

## 待办

- 端到端 MNIST / cifar_cnn demo 实测（用户跑）
- 与旁路问题 #1（Latency 目标 HITL → LangGraph interrupt）协调：本次保留 adapter_generator 的 ask_user 作为 setup fallback；后续 interrupt 升级时平替
