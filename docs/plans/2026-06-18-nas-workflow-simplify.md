# NAS Workflow 简化重构 — 实施计划

> 日期: 2026-06-18
> 状态: 设计已与用户对齐，待执行
> 关联 ADR: 待补 `docs/refactor/nas-workflow-simplify/ADR.md`

---

## 1. 背景与动机

当前 NAS workflow（`workflows/nas/workflow.json`，15 agent）存在三个核心问题：

1. **Cycle 复杂度过高**：7 步串行（selector→planner→trainer→judger→analyzer→validator→refiner），每步一次 LLM 调用 + 状态序列化，延迟与 token 成本高
2. **优化方向无专精**：单一 `planner` stateless 提议 K 个策略，无记忆 → 重复尝试失败方案
3. **SETUP 缺交互**：仅 `adapter_generator` 带 ask_user 且只在 fallback 触发，baseline 阶段对用户是黑盒；用户指标可能是任意自定义 metric，现 `metrics_identifier` 硬编码启发式表判方向，错误率高
4. **无断点续传**：`runs/` 下每项目累积大量 session（microxcaling 已 13+），每次重新 setup

## 2. 设计决策（14 条）

| # | 决策 | 备注 |
|---|---|---|
| 1 | 两阶段：SETUP（6 agent）+ NAS 寻优（7 agent）+ FINAL（1 agent） | 共 14 agent |
| 2 | SETUP 删除独立 eval 入口，metric 直接从训练 log 提取 | `log_parse_rules.json` 全 cycle 复用 |
| 3 | 新增 `business_analyzer`（SETUP），输出 `business_context.md` 给 optimizer_business 用 | 也给另两个 optimizer 参考 |
| 4 | `metric_align` 替代 `metrics_identifier`：从 smoke log 用 regex 候选提 metric → **ask_user 确认 primary + 方向** | 解决"奇怪指标"问题 |
| 5 | 新增 `setup_align`：ask_user 综合对齐 dummy_input/data_ratio 可控否/target/time_budget/latency 关心否 | 输出 `setup_contract.json` |
| 6 | `baseline_runner` 跑全量 baseline 后 **ask_user 汇报 + 要求确认** | 用户决定是否继续进 NAS |
| 7 | NAS cycle 4 步：tier_planner → selector → 3 optimizer 并行 → collector | 详见 §3 |
| 8 | 3 个 optimizer：hyperparam / structural / business，每轮全跑不跳过 | 独立 worktree 互不干扰 |
| 9 | 每个 optimizer 自闭环 retry 到跑通（max 5 次后 fail loud） | collector 永远收 3 进 3 出 |
| 10 | budget = 每轮每 optimizer 最多 3 个 change point，显式声明在 `changes.json` | collector 拒收 point >3 |
| 11 | tier 升级时由 `tier_baseline_runner` 跑该 tier 的 baseline 作 fitness 参考 | **复用 `on_pass/on_fail`**：tier_planner.on_pass=selector(不升)/on_fail=tier_baseline_runner(升)；零框架改动 |
| 12 | **Agent-driven + target-driven**：cycle 终止由 collector 判定（target_met 或 tier_maxed+plateau），非定死轮次。`max_iterations=100` 仅作安全网防无限循环 | collector.on_pass=reporter(达标或放弃)/on_fail=tier_planner(继续) |
| 12 | selector 公式：`score = fitness + 0.3 × exploration_bonus`，禁止同方向连续 3 轮 | 鼓励探索 |
| 13 | 历史两层结构：共享 `candidates.json` + 每 iter 子目录（含 parent_snapshot）+ per-direction `running_memory/*.md` | 见 §5 |
| 14 | 断点续传：每个 agent Step 0 调 `check_resume.py`，**文件存在 + schema 校验** 通过则 skip | `run_nas.py` 加 `--session-id` |

工具集统一松绑：所有 agent 加 `read/write/edit`，移除"禁止 bash 写文件"的死规则。

## 3. NAS 寻优循环详图

```
每轮 iter N:

A. tier_planner
   读 history + fitness 曲线
   决定本轮 (data_ratio, epochs)，是否升级 tier
   写 tier_decision.json
   路由:
     upgrade=true  → tier_baseline_runner → selector
     upgrade=false → selector

B. selector
   综合 candidates.json（含 3 个方向所有产物）
   公式: score(s) = fitness(s) + 0.3 × exploration_bonus(s)
   硬规则: 禁止同方向连续 3 轮
   输出 1 个 parent_strategy_id（首轮 = baseline）

C. 3 optimizer 并行（独立 worktree）
   共同输入: parent + setup_contract + 自己 running_memory
   optimizer_business 额外输入: business_context.md
   
   每个 optimizer 内部循环:
     for attempt in 1..6:
       plan = decide_changes(parent, history, budget=3)
       write changes.json (显式声明 ≤3 个 point)
       apply diff in worktree
       result = run_training(tier_config)
       if result.ok and metric valid:
         return success
       log failure, refine plan
     fail_loud
   
   输出: diff.patch + train.log + eval_result.json + summary.md

D. collector
   收 3 optimizer 结果
   调 compute_fitness.py 算 fitness（acc + 可选 latency 归一化）
   判定（agent-driven，非计数）:
     - target_met (setup_contract.target 达标)               → 路由 reporter
     - tier_maxed + 连续 K 轮无提升（plateau，无希望）        → 路由 reporter
     - 否则                                                   → 路由 tier_planner (下一轮)
   更新 candidates.json + 写 running_memory/*.md
   写 iter_N/collector.json
   路由:
     on_pass = "reporter"  (达标 or 放弃)
     on_fail = "tier_planner" (继续下一轮)
   max_iterations=100 仅作安全网（agent 决策失败时的兜底）
```

## 4. Agent I/O 契约

### 4.1 SETUP 阶段

#### project_analyzer
- **改**：工具集加 `read/write/edit`；Step 0 加 resume check
- **输入**：working_dir
- **输出**：`<session_dir>/project_analysis.json`（schema 同现状，14 字段）

#### business_analyzer（新）
- **工具**：bash/grep/glob/read/write/edit
- **输入**：working_dir + project_analysis.json
- **任务**：分析任务类型（CV/NLP/...）/ 数据特点 / 特征工程 / 已知 SOTA 方法。**不要细节代码**，只要背景知识
- **输出**：`<session_dir>/business_context.md`（结构化 markdown：domain/data/features/prior_art/optimization_hints）

#### smoke_runner（改名自 baseline_runner）
- **改**：跑 1 epoch + 最小 data_ratio（如 0.1），仅验证 adapter 可跑通 + 捕获完整 train.log
- **输出**：`<session_dir>/smoke_train.log` + `<session_dir>/smoke_eval.json`

#### metric_align（改名自 metrics_identifier）
- **改**：删除硬编码启发式表；从 smoke_train.log 用 regex 候选自动检测 metric → **ask_user 确认** primary + 方向（不确定就问，包括"higher/lower 你判断"选项）
- **输出**：`<session_dir>/metric_contract.json` + `<session_dir>/log_parse_rules.json`
  ```json
  {
    "primary_metric": "acc",
    "direction": "higher",
    "log_parse_rules": [
      {"name": "acc", "regex": "acc=([0-9.]+)", "type": "float", "direction": "higher"}
    ]
  }
  ```

#### setup_align（新）
- **工具**：bash/read/write/edit/ask_user
- **任务**：综合 ask_user 对齐所有 SETUP 决策
- **输出**：`<session_dir>/setup_contract.json`
  ```json
  {
    "dummy_inputs": {"shape": [1, 784], "type": "float32"},
    "data_ratio_dim": "controllable",
    "epochs_dim": "controllable",
    "epochs_default": 5,
    "metric_contract_path": "...",
    "log_parse_rules_path": "...",
    "latency": {"care": true, "measure_fn": "default_onnxruntime"},
    "seed": 42,
    "target": {"metric_value": 0.95} | null,
    "time_budget_sec": 3600 | null,
    "tier_system": {"max_tier": 1, "tiers": [{"data_ratio": 0.1, "epochs": 1}, ...]}
  }
  ```

#### baseline_runner（重写）
- **改**：跑用户原始超参全量训练（**不通过 adapter 改 epochs/data_ratio**，直接调用户脚本）
- **后置 ask_user**：跑完向用户汇报"baseline acc=X, latency=Yms, params=Z"，要求确认是否进 NAS
- **输出**：`<session_dir>/baseline.json`（schema 同现状 BaselineFile）

### 4.2 NAS CYCLE 阶段

#### tier_planner
- **改**：从 setup 一次定死改为 cycle 内每轮调用
- **输入**：setup_contract.tier_system + history + fitness 曲线
- **决策**：本轮 (data_ratio, epochs)；是否升级 tier（连续 K 轮无提升 OR 累计时长 > budget → 升级）
- **输出**：`<session_dir>/iter_N/tier_decision.json`
- **路由**：`on_upgrade → tier_baseline_runner`，`on_stay → selector`

#### tier_baseline_runner（新，条件触发）
- **工具**：bash/read/write/edit/sub_agent
- **输入**：tier_decision.new_tier + baseline 模型
- **任务**：用 baseline 模型 + new_tier 配置跑一次（仅 baseline 模型，不改代码）
- **输出**：`<session_dir>/tier_<T>_baseline.json`
- **下游**：→ selector

#### selector
- **改**：综合公式选 1 个 parent
- **输入**：candidates.json + running_memory/*.md
- **公式**：`score = fitness + 0.3 × exploration_bonus`；禁止同方向连续 3 轮
- **输出**：`<session_dir>/iter_N/selector_decision.json`（含 parent_id + 评分细节 + rationale）
- **首轮**：parent = baseline

#### optimizer_hyperparam / optimizer_structural / optimizer_business（3 个新 agent）
- **共同协议**：
  - 工具：bash/read/write/edit/sub_agent
  - 输入：parent + setup_contract + 自己 running_memory
  - budget：每轮 ≤3 个 change point，显式声明在 `changes.json`
  - retry：内部循环 max 6 次（5 重试 + 1 fail loud），必须跑通
  - 输出：`<session_dir>/iter_N/optimizer_<X>/` 下
    - `changes.json`（声明 point 列表）
    - `diff.patch`
    - `train.log`
    - `eval_result.json`（用 log_parse_rules 提取的 metric）
    - `summary.md`（这轮尝试了什么 + 教训）
- **optimizer_business 特殊**：
  - 额外输入：`business_context.md`
  - 范围最大：可改数据 pipeline / 特征 / 算法 / 用 SOTA
  - 同样受 3 point budget 约束（防止改天翻地覆）

#### collector
- **合并**：现 judger + analyzer + validator 三 agent
- **工具**：bash/read/write/edit
- **输入**：3 个 optimizer 产物 + log_parse_rules + setup_contract
- **任务**：
  1. 调 `compute_fitness.py` 算 fitness（deterministic）
  2. target check（若 setup_contract.target 达标）
  3. 更新 `candidates.json`（每个 entry 含 source/parent_id/iter_num/fitness）
  4. 写 `running_memory/optimizer_<X>.md`（追加方向总结）
- **输出**：`<session_dir>/iter_N/collector.json`（含 ranking + target_met + best_strategy_id）
- **路由**：`target_met OR tier_满 → reporter`，`否则 → tier_planner`

### 4.3 FINAL 阶段

#### reporter
- **改**：合并 refiner 的"最终全量训练"职责
- **任务**：对 best_strategy 用 setup_contract.epochs_default 跑一次全量训练，跟 baseline 做终极对比；写最终报告
- **输出**：`<session_dir>/final_report.md` + `<session_dir>/final_winner_eval.json`

## 5. 历史结构（响应"per-optimizer 也要基线信息"）

```
<session_dir>/
├── setup_contract.json          ← SETUP 总契约
├── baseline.json                ← 全量 baseline
├── business_context.md          ← 共享业务背景
├── metric_contract.json
├── log_parse_rules.json         ← 全 cycle 复用，不改
├── candidates.json              ← 共享 elite pool，按 fitness 排序
│                                  每个 entry:
│                                  { strategy_id, source_dir, parent_id,
│                                    source: hyperparam|structural|business,
│                                    metrics, latency, params, fitness,
│                                    iter_num, diff_path, changes_count }
├── tier_<T>_baseline.json       ← 每 tier 一份（tier_baseline_runner 产物）
│
├── iter_1/
│   ├── tier_decision.json
│   ├── selector_decision.json   ← parent + 评分细节
│   ├── parent_snapshot/         ← 复制 parent 代码作起点（基线信息）
│   ├── optimizer_hyperparam/
│   │   ├── changes.json         ← 声明的 3 个 point
│   │   ├── attempts/
│   │   │   ├── attempt_1/ (failed: ...)
│   │   │   └── attempt_2/ (success)
│   │   │       ├── diff.patch
│   │   │       ├── train.log
│   │   │       └── eval_result.json
│   │   └── summary.md
│   ├── optimizer_structural/... (同结构)
│   ├── optimizer_business/...   (同结构)
│   └── collector.json           ← ranking + fitness + target_check
│
├── iter_2/ ...
│
└── running_memory/              ← 跨 iter 滚动更新的方向记忆
    ├── optimizer_hyperparam.md  ← "lr: 0.1 爆 / 0.01→0.86 / 0.001→0.87"
    ├── optimizer_structural.md  ← "GELU > ReLU / +BN +1%"
    └── optimizer_business.md    ← "aug +2% / mixup 没用"
```

**关键：parent_snapshot 保留基线信息**。每个 optimizer 改前先快照 parent 代码到 `parent_snapshot/`，下游可追溯"我当时基于什么改的"。running_memory/*.md 是跨 iter 的方向总结，新 iter 的 optimizer 读它避免重复尝试。

## 6. 新增 Helper（4 个）

| Helper | 输入 | 输出 | 用途 |
|---|---|---|---|
| `parse_train_log.py` | log 文件 + log_parse_rules.json | metric dict | trainer/optimizer 从 log 提 metric |
| `measure_latency_fn.py` | onnx_path | `{latency_ms_median, p95, ...}` | 纯函数，便于用户替换 |
| `check_resume.py` | session_dir + agent_name + expected_files | `{skip: bool, reason}` | 统一 resume 校验 |
| `compute_fitness.py` | metric_dict + setup_contract.latency_care | fitness float | deterministic 公式 |

`measure_latency_fn.py` 关键设计：
```python
def measure_latency(onnx_path: str) -> dict:
    """用户可替换此函数。默认实现: onnxruntime 100 次。
    Returns: {latency_ms_median, latency_ms_p95, latency_ms_mean, n_runs}
    """
    # default impl
    ...
```
用户在 setup_align 里通过 ask_user 选 `default_onnxruntime` 或自定义路径，写入 `setup_contract.latency.measure_fn`。

## 7. 分阶段实施

### Phase 1: Helper 基础设施（独立可测）
- [ ] `parse_train_log.py` + 单元测试（mock log + 各种 regex）
- [ ] `measure_latency_fn.py`（refactor 现 `measure_onnx_latency.py` 暴露纯函数）
- [ ] `check_resume.py` + 单元测试
- [ ] `compute_fitness.py` + 单元测试
- **验证**：4 个 helper 全部单元测试通过

### Phase 2: SETUP 阶段 6 agent
- [ ] 改 `project_analyzer.md`（工具松绑 + resume check）
- [ ] 新 `business_analyzer.md`
- [ ] 改 `baseline_runner.md` → `smoke_runner.md`
- [ ] 改 `metrics_identifier.md` → `metric_align.md`（加 ask_user）
- [ ] 新 `setup_align.md`
- [ ] 新 `baseline_runner.md`（全量版，加 ask_user 后置）
- [ ] 更新 `workflow.json`（SETUP 段）
- **验证**：DAG 编译通过；SETUP 端到端跑通（mock 后续阶段）

### Phase 3: NAS CYCLE 阶段 7 agent
- [ ] 改 `tier_planner.md`（cycle 内 + 条件路由）
- [ ] 新 `tier_baseline_runner.md`
- [ ] 改 `selector.md`（综合公式）
- [ ] 新 `optimizer_hyperparam.md` / `optimizer_structural.md` / `optimizer_business.md`
- [ ] 新 `collector.md`（合并 judger/analyzer/validator）
- [ ] 删除 `planner.md` / `trainer.md` / `judger.md` / `analyzer.md` / `validator.md` / `refiner.md`
- [ ] 更新 `workflow.json`（CYCLE 段）
- [ ] **改 dag_builder.py** 支持 `on_upgrade/on_stay` 路由（若现不支持）
- **验证**：DAG 编译；mock 3 optimizer 跑 1 iter 验证 collector

### Phase 4: reporter + 断点续传 + CLI
- [ ] 改 `reporter.md`（合最终全量训练）
- [ ] 所有 setup agent Step 0 接入 `check_resume.py`
- [ ] `run_nas.py` 加 `--session-id <id>` 参数
- [ ] `.nas_session_pointer` resume 链路真正激活
- **验证**：跑 SETUP → 中断 → `--session-id` resume → 验证 skip 生效

### Phase 5: 修 mnist + 实测
- [ ] 修 mnist `model.py` 与 `train.py` 一致性（接受 kwargs + 默认值匹配）
- [ ] 修 mnist `dummy_inputs` 形状（64 维非 784）
- [ ] 跑 SETUP 阶段，观察 3 次 ask_user（metric_align / setup_align / baseline_runner 后置）
- [ ] 跑 NAS 循环 2-3 iter，观察：
  - tier_planner 决策合理性
  - selector parent 选择是否轮换方向
  - 3 optimizer 是否并行 + 自闭环 retry
  - collector fitness 计算 + target check
- [ ] 汇总问题清单 → 与用户讨论

## 8. 不变量（CI 强制）

1. **setup_contract.json 是 SETUP 总契约**，所有 cycle agent 必须读
2. **log_parse_rules.json 一旦写入，全 cycle 复用**，任何 agent 不许改
3. **candidates.json 每个 entry 必须含** source/parent_id/iter_num/fitness
4. **tier_baseline 必须在 selector 之前完成**（同 tier 内）
5. **optimizer 失败 ≤5 次 retry**，超过 fail loud（不许无限循环烧 token）
6. **resume check 必须 schema 校验**，不只看文件存在
7. **changes.json 必须 ≤3 个 point**，collector 拒收超限
8. **selector 禁止同方向连续 3 轮**（硬规则）

## 9. 风险与缓解

| 风险 | 缓解 |
|---|---|
| `dag_builder.py` 不支持 `on_upgrade/on_stay` 条件路由 | Phase 3 前先验证；不支持则 fallback 到 tier_planner 内部 sub_agent |
| optimizer 自闭环 retry 5 次仍失败（项目本身有 bug） | fail loud → collector 收到 fail_signal → 本轮该方向产出 null，selector 下轮换 parent |
| business optimizer 改动太大跑偏 | 3 point budget + parent_snapshot 可回溯；running_memory 记录"曾试过 X 失败" |
| 3 个并行 worktree GPU 资源争抢 | setup_align ask_user 问 GPU 数；trainer 内部 queue 调度 |
| metric_align regex 漏掉用户 metric | ask_user 兜底：列候选 + 允许 custom_input 自填 regex |

## 10. 成功标准

- Phase 1-4 完成：所有单元测试通过 + DAG 编译 + resume 测试通过
- Phase 5 mnist 实测：
  - SETUP 3 次 ask_user 全部正常触发
  - NAS 循环至少跑 2 iter，selector 方向轮换正常
  - 至少 1 个 optimizer 成功产出有效 strategy
  - 断点续传：中断后 `--session-id` 重启，已完成的 agent 全部 skip
- 输出实测问题清单（不预期一次完美，发现问题即可）

---

## 附：与现状差异速查

| 项 | 现状 | 新设计 |
|---|---|---|
| cycle 步数 | 7 步串行 | 4 步（3 optimizer 并行） |
| 优化方向 | 单 planner 无记忆 | 3 专精 optimizer 各带 running_memory |
| SETUP 交互 | 仅 adapter fallback | 3 处显式 ask_user |
| metric 方向 | 硬编码启发式表 | 用户确认 + log_parse_rules |
| tier_planner | setup 一次定死 | cycle 内每轮调用 |
| tier baseline | 无 | tier_baseline_runner（条件触发） |
| parent 选择 | candidates top-1 | 综合公式 + 方向轮换硬规则 |
| 失败重试 | trainer retries=2 | optimizer 内部 max 5 次 |
| 断点续传 | 几乎没有 | 每 agent check_resume + CLI --session-id |
| 工具集 | 严格限制（多无 write/edit） | 统一松绑 |
| Agent 总数 | 15 | 14 |
