---
workflow: nas
title: NAS 端到端流程总览
badge: Overview
---

# NAS 端到端流程总览

本教程对应 `workflows/nas/` 这个真实可跑的工作流。它会读取你已有的训练项目（任意框架，只要能 `import` 出 `nn.Module`），自动跑完「探测 → adapter 生成 → 基线 → 迭代搜索 → tier 升级复跑 → 最终报告」整个流程，最终给出一个带 fitness 排序、改造路径、架构瓶颈分析的 `FINAL_REPORT.md`。

工作流由 10 个 agent 组成，分四个阶段：**Setup（一次性）→ Cycle（迭代搜索）→ Refine（tier 升级复跑）→ Report**。下面按执行顺序逐个讲解。

---

## 阶段 0：项目探测 @project_analyzer

第一个 agent，**只读不改**。它扫描你的项目目录，识别出后续 agent 需要的关键入口：

| 字段 | 说明 |
|------|------|
| `model_class` / `model_module` | `nn.Module` 子类名与 dotted import path（如 `model.Net`） |
| `train_entry` / `eval_entry` | 训练/评估函数签名（`train:train_model`） |
| `weights_path` / `weights_exist` | 已有权重路径，决定是否跳过训练 |
| `epochs_controllable` + `mechanism` | epochs 是否可由外部控制（`cli_flag` / `function_arg` / `config_file` / `hardcoded`） |

`epochs_controllable` 是整个 tier 系统的前提：true 时 trainer/refiner 可以按 tier 跑不同 epochs；false 时所有训练退化成「跑用户默认 epochs」，single-tier 强制模式。探测失败时 `summary` 字段会标 `"partial: missing <fields>"`，由 scout 决定是否 `ask_user` 兜底。**不直接调用户任何训练代码**。

---

## 阶段 1：Setup 三波 @scout

NAS workflow 的核心编排节点，**只执行一次**，按三个 wave 顺序推进——wave 内并发、wave 间串行：

```
Wave 1: adapter_generator + domain_analyzer   (并发)
   ↓ 生成 _nas_adapter.py（用户提供给框架的统一训练接口）
Wave 2: baseline_runner                         (单独)
   ↓ 跑基线：1 epoch train + eval + export onnx + measure latency
Wave 3: tier_planner + metrics_identifier      (并发)
   ↓ 输出 budget.json（tier 推荐 + target）+ metrics.json（指标方向）
```

为什么是三个 wave：**adapter 必须先就位**才能跑 baseline（adapter_generator 通过 smoke 三件套 `train_ok` / `export_ok` / `latency_ok` 验证 adapter 接口完整，否则不进 Wave 2）；**baseline 必须先就位**才能定 budget（target_latency 来自 baseline 实际延迟，acc_tolerance 来自 baseline 精度）；**tier 和 metrics 互不依赖**，所以并发。

scout 的关键产物落在 `$session_dir` 下：

| 文件 | 来源 | 用途 |
|------|------|------|
| `<working_dir>/_nas_adapter.py` | adapter_generator | 统一训练接口，所有后续训练/评估都走它，**绝不直接调用户 train.py** |
| `<session_dir>/baseline.json` | baseline_runner → `make_baseline.py` | 基线指标 + 延迟 + 参数量 |
| `<session_dir>/baseline_profile.json` | `profile_model.py` | per-layer latency 分解，planner 据此挑选 high-impact layer 改造 |
| `<session_dir>/budget.json` | tier_planner → `make_budget.py` | target_latency / acc_tolerance / tier 推荐 |
| `<session_dir>/metrics.json` | metrics_identifier | `primary_metric` + 每个 metric 的方向（higher/lower，**不允许 unknown**） |
| `<session_dir>/domain_insights.md` | domain_analyzer | 领域推荐改造方向（供 planner cite） |

Step 4 强制 helper 重生成 `baseline.json` / `budget.json`（覆盖 sub_agent 写的版本），绕过 LLM 自由发挥导致的 schema 漂移。这是 NAS workflow 的设计原则之一：**deterministic 逻辑用代码，不用 LLM 心算**。

---

## 阶段 2：选父代 + 决定方向 @selector

每轮 cycle 的入口，**纯决策**，不跑训练。读 `candidates.json`（elite pool，首轮为空）+ `tier_state.json` + `direction.md`，决定本轮的 iter_num / parent / tier / K / 方向：

1. **iter_num**：从 candidates 推断 `max(iter_num) + 1`，不依赖 framework 计数器
2. **parent**：iter 1 用 `"baseline"`；iter N>1 按 fitness 取 top-1（tie 时优先小 iter_num）
3. **current_tier**：首次 = 0；refiner.on_fail 回来时读 refiner 写入的新 tier
4. **plateau 检测**：调 `direction.py detect-plateau`，最近 3 轮 cv<0.08 或未比历史 best 提升 >1% → plateau
5. **动态 K**：plateau 时 `K = budget.strategies_per_iter * 2`（加倍探索），否则用 budget 默认值
6. **方向变化**：调 `direction.py suggest-direction`，若最近 K 个 strategy 签名相似度 >0.7 或 plateau 持续 2+ 轮 → `direction_change=true`，从 `domain_insights.md` 里挑未尝试方向

selector 是 cycle 的**汇点**：`validator.on_fail` 和 `refiner.on_fail` 都会回到这里。

---

## 阶段 3：开放式 hypothesis 生成 @planner

基于 parent + 领域 insights + 方向策略，**开放式**生成 K 个候选改造方案。一次性并发 issue K 个 Coder sub_agent（每个 `isolation="worktree"`）。

**Lineage 拆分**（K≥3 时强制，防 parent 选错时 K 个 strategy 一起错）：`⌈K/2⌉` 个 from top-1 parent（深化当前最优方向）；`1` 个 from top-2 parent（探索次优分支）；`1` 个 **wild card**（id 加 `_wc` 后缀），restart from baseline，方向必须不同于已探索的 `direction_tag`。

每个 hypothesis 必须打 type 标签，决定风险/收益：

| 类型 | 范围 | 风险/收益 |
|------|------|----------|
| `[parametric]` | 调超参（lr / batch_size / hidden_dim） | 便宜、低风险、天花板低 |
| `[structural_local]` | 换 layer / 插 skip / op 替换 | 中风险 |
| `[structural_global]` | 重构 attention / 换 backbone / MoE | 高风险、高收益 |

K≥3 时**至少 1 个非 parametric**（避免原地打转），wild card 鼓励 `structural_global`。

**小步迭代约束**（强制，违反即丢弃 strategy）：每个 strategy 的 diff **只能改动 ≤3 个位置**，位置 = 单个 layer 替换 / 单个 hyperparam / 单个 op 插删 / 单个 nn.Module 类替换。典型例子：`nn.ReLU()` → `nn.GELU()` 是 1 位置；`hidden_dim=64→128` + 加 `BatchNorm1d` 是 2 位置；同时改 lr + batch + epochs + optimizer + model 是 4+ 位置会被拒。理由：让 fitness 变化**可归因**——哪个改动有效，哪个无效，analyzer 才能分析、reporter 才能推荐。

**Failure-aware avoidance**（必做）：读 `failure_patterns.md`（analyzer 累加维护），已标记的危险 layer / 危险超参组合不再生成，除非明确解释如何规避。

---

## 阶段 4：并发训练 + tier 自判 @trainer

**自判 tier** + **并发**训练 K 个 strategy。所有训练/评估走 `_nas_adapter.py`，绝不直接调用户的 train.py。

trainer 不死板按 budget 推荐，读 `budget.tier_recommendation.proposed_tiers` 后根据实际情况调整：上轮 OOM 频次高 → 降一档（减 epochs）；上轮 fitness 区分度低 → 升一档（增 epochs，提高分辨力）；上轮训练耗时 >1.5x baseline 估算 → 降一档；当前已是 max_tier → 不再升。**Adapter 退化检查**：`project_analysis.epochs_controllable=false` 时设 `effective_tier.epochs=null`（跑用户默认 epochs），并在 `tier_adjustment_rationale` 写清退化原因。

选定 tier 后，同一 response 内 issue 全部 K 个 sub_agent，每个跑 helper：

```bash
python <helpers_dir>/run_strategy.py \
  --worktree . \
  --diff <diff_path or "baseline"> \
  --adapter-path <adapter_path> \
  --tier '{"epochs": <X or null>}' \
  --out <session_dir>/iter_<N>/strategy_<i>/eval_result.json \
  --helpers-dir <helpers_dir> \
  --strategy-id <strategy_id> \
  [--gpu-id <id>]
```

helper 内部一条龙：`cd worktree → git apply → adapter.get_model() → adapter.train() → adapter.evaluate() → export_onnx → measure_onnx_latency → 写 eval_result.json`。`--worktree .` 用 sub_agent 当前 cwd（framework 自动设置的 worktree path），**不要用主项目目录绝对路径**——会污染主目录。

失败处理：helper `status="failed"` → 读 `error_trace` 定位（OOM → 降 batch；NaN → gradient clipping；shape mismatch → 检查 diff；ImportError → 修路径）。最多重试 2 次，仍失败保留 `status="failed"` + 完整 stack。ONNX 导出失败**不阻塞**（helper 自动 `status="ok"` + `onnx_latency_ms=null`）。

---

## 阶段 5：多维 fitness 计算 @judger

**只算 fitness + 排序，不做达标判断**（达标是 validator 的事，防幻觉）。委托 `fitness.py compute`（deterministic，避免 LLM 心算误差）。公式：

```
primary_normalized = (val - baseline) / baseline     if direction=="higher"
                   = (baseline - val) / baseline     if direction=="lower"
acc_drop       = max(0, -primary_normalized)
latency_ratio  = target_latency_ms / strategy_latency
param_ratio    = strategy_params / baseline_params
stability      = 1 - normalize(std(loss_curve_tail))

fitness = 0.4 * max(0, 1 - acc_drop / acc_tolerance)   # 精度约束（占 40%）
       + 0.3 * min(1.5, latency_ratio)                  # 延迟改善（占 30%）
       + 0.2 * (1 - param_ratio)                        # 参数压缩（占 20%）
       + 0.1 * stability                                # 训练稳定性（占 10%）
```

**Bonus**：strategy 的 `hypothesis_type != parametric` 且 `profile_target` 命中 baseline_profile 的 `top_latency_layers` → fitness +0.1（鼓励针对瓶颈 layer 的结构性改造）。latency 优先用 `onnx_latency_ms`（更稳、跨设备可比），fallback 到 pytorch `latency_ms`。judger 把 fitness 写回每个 strategy 的 `eval_result.json`（让后续 agent 不用重算），输出 ranking（按 fitness 降序）。

---

## 阶段 6：事实整理 + 历史记录 @analyzer

**不做决策**，只做事实整理。analyzer 更新 elite pool + 历史索引 + 签名去重 + 方向记录 + 失败模式：

| 文件 | 操作 |
|------|------|
| `candidates.json` | `candidate_pool.py push` —— push 本轮 ok strategy，按 fitness 排序保留 top-K（默认 K=10） |
| `iter_<N>/SUMMARY.md` | `history.py write-summary` —— L2 简述 |
| `HISTORY.md` | `history.py append-history` —— L1 索引（顶部追加） |
| `signatures.idx` | `signature.py append-batch` —— diff 哈希索引，供 planner 去重 |
| `direction.md` | `direction.py mark-explored` —— 标记本轮已探索方向 |
| `plateau_signal.json` | `direction.py detect-plateau --write` —— 给下轮 selector |
| `failure_patterns.md` | LLM 语义分类本轮失败（shape mismatch / OOM / NaN / ImportError / adapter 失败），累加计数 + 标记危险区 |

**渲染图表**（`render_charts.py --node-id analyzer`，每 iter 都画）：每 tier scatter (acc vs latency)、Pareto 前沿、fitness-progression line、top_strategies table、baseline-comparison bar。`failure_patterns.md` 是 planner 的关键输入——已标记的危险 layer / 危险组合不再生成。

---

## 阶段 7：纯脚本达标决策 @validator

**纯事实决策**：调 `check_target.py` 做达标对比，**不靠 LLM 推理**。validator 存在的意义就是消除 analyzer/judger 可能的幻觉——把决策移到 deterministic 脚本上，LLM 只负责「调脚本 + 转格式」：

```bash
python $helpers_dir/check_target.py \
  --candidates $session_dir/candidates.json \
  --budget $session_dir/budget.json \
  --metrics $session_dir/metrics.json \
  --baseline $session_dir/baseline.json
```

返回 `target_met` + `abort_recommended` + `checks.{acc_constraint_met, latency_constraint_met}` 等事实字段，决策规则也由这些事实直接决定：

| 情况 | decision | 路由 |
|------|---------|------|
| `target_met=true` | `pass` | → refiner（达标了，进 refine 确认） |
| `abort_recommended=true`（连续 ≥3 轮 candidates 不增长 OR 最近 5 轮 fitness 无提升） | `pass` | → refiner（refiner 读 `outcome=abort` 自动 skip → reporter） |
| 其他 | `fail` | → selector（回 cycle 找新方向） |

---

## 阶段 8：tier 升级 + full-mode 复跑 @refiner

validator.pass 后进入。**tier 自判升级** + top-K strategy 用更高 tier（更多 epochs）复跑确认。tier 升级规则严格只升一级：`current_tier < max_tier` → 升级，用 `proposed_tiers[new_tier]` 配置；`current_tier == max_tier` → 不升级但仍 refine；同 trainer 的 adapter 退化检查（`epochs_controllable=false` → `epochs=null`）。

refiner 从 `candidates.json` 按 fitness 取 top-K（默认 K=3）进 refine：跳过 baseline；跳过「已在更精细 tier refine 过且 failed」的 strategy。复跑后用 `check_target.py` 判定达标，决策规则：

| 情况 | decision | 路由 |
|------|---------|------|
| 复跑达标 | `pass` | → reporter（达标成功） |
| 没达标 AND `current_tier < max_tier` | `fail` | → selector（tier 已升，下轮 trainer 读到新 tier） |
| 没达标 AND `current_tier == max_tier` | `fail` | → selector（强制换方向找新 strategy） |

refiner 写 `$session_dir/refiner_decision.json`，含 `outcome`（`refine_pass` / `tier_upgrade` / `max_tier_reached` / `abort`）。

---

## 阶段 9：最终报告 @reporter

最后一步。生成 `FINAL_REPORT.md` + 渲染完整结果图（含 refinement 数据）。outcome 由 validator + refiner 决策共同决定：validator + refiner 都 abort → **整体 abort**（未找到改进）；refiner.outcome=`refine_pass` → **达标成功**；其他 → **部分成功**（找到改进但未达标）。

推荐方案：达标成功 → refinement ok strategy 里挑 fitness 最高（多达标时挑 latency 最低）；abort → 推荐 = baseline（明确说"未找到改进"）；部分成功 → 推荐 fitness 最高 strategy，但标注"未达标"。

报告必含五块内容：**Baseline vs 推荐对比表**（每个 metric 的 Δ + 是否达标）、**Refinement Top-K 表**（rank / strategy / tier / fitness / metrics / status）、**改造路径 Lineage**（从 baseline 到推荐的每一步，cite parent strategy），以及**架构优化建议**（必填，不能空，严禁泛泛而谈），后者再细分为五条：

1. **Latency 瓶颈分析** —— baseline_profile 的 top-3 latency layer，本轮 structural 改造涉及哪些、未触碰的高 latency layer（给具体改造方向如"fused QKV" / "depthwise separable conv"）
2. **Accuracy 天花板分析** —— 所有 strategy 的 primary_metric 范围，是否有天花板，原因推断（over-parameterization / 数据不足 / 收敛鞍点 / tier 不足）
3. **Wild card 启示** —— direction.md 里 `_wc` 后缀 strategy 的收益 vs top-1 lineage，哪个非主流方向值得加大投入
4. **未充分探索方向** —— domain_insights 推荐方向 vs direction.md explored，列出未探索 + 预估收益
5. **Failure 启示** —— 反复失败的改造标记为后续避免；稳定可叠加的标记为安全方向

reporter 渲染的最终图比 analyzer 多了 refinement 数据：refine 阶段 strategy 进图（按 tier_index 分组），baseline-comparison bar 用 refinement 后的最佳 strategy。

---

## 总结

NAS workflow 把传统 NAS 的「搜索空间定义 + Supernet 训练 + 子结构采样」的静态模式，换成了「围绕用户已有项目的开放式 hypothesis + 多维 fitness + tier 渐进升级」的动态模式：

- **不假设搜索空间**：planner 基于领域 insights + baseline profile 开放式 hypothesize，每次只生成 K 个小步迭代（≤3 改动）的 strategy
- **多维 fitness**：精度约束（40%）+ 延迟改善（30%）+ 参数压缩（20%）+ 稳定性（10%），鼓励针对 latency 瓶颈的 structural 改造
- **tier 渐进升级**：cycle 阶段跑低 tier 省时间，validator.pass 后 refiner 升级复跑确认，避免低 tier 误判
- **deterministic 优先**：fitness / 达标判断 / 路径决策全走 helper 脚本，LLM 只负责开放式 hypothesize + 语义分类失败模式
- **失败记忆**：analyzer 维护 `failure_patterns.md`，planner 后续避免已标记的危险 layer / 危险组合

10 个 agent 的 DAG：

```
project_analyzer → scout → selector ⇄ planner → trainer → judger → analyzer
                                       ↑                                      ↓
                                       │                                   validator
                                       │                                  ╱       ╲
                                       │                            fail ╱         ╲ pass
                                       ↓                                ╱             ╲
                                    selector←─────fail──────refiner                  reporter
                                                       ╱        ╲
                                                pass ╱          ╲ pass (abort)
                                                   ╱              ╲
                                                reporter ←───────(refiner skip)
```

点击左下角**「试一试」**加载 `nas` workflow。建议先用一个小项目（如 MNIST MLP）跑通整个流程，再迁移到生产项目。
