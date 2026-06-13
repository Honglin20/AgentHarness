# NAS Workflow 改进计划

> 日期：2026-06-13
> 状态：讨论中（adapter + profile 设计待确认；agent 合并后续讨论）
> 上次 commit：`2585619` / branch `main`

## 背景

mnist run 跑通后梳理 NAS workflow 的设计，发现以下问题。本计划记录已确认的改进项；agent 合并（selector+judger+analyzer+validator → synthesizer）暂缓，后续单独讨论。

---

## P0 — 修 trainer sub_agent cwd bug

**问题**：sub_agent 的 `git apply` 可能写到用户 working_dir 而不是 worktree，污染用户代码。
**位置**：CURRENT.md 已记录为独立架构问题。
**做法**：先 verify sub_agent 拿到的 worktree 路径，再确认 `git apply` 的 cwd；必要时在 sub_agent task 模板里强制 `cd <worktree>` 后才跑 `git apply`。
**验收**：跑一遍 mnist，结束后 `git status` 在 working_dir 应该 clean。

---

## P1 — 抽 `run_strategy.py` helper（消除 sub_agent 模板重复）

**问题**：scout / trainer / refiner 三个 agent 的 sub_agent task 模板有 80% 重复内容（cd worktree → apply diff → train → benchmark → export ONNX → measure latency → 失败处理）。
**做法**：抽一个 helper，**通过 `.nas_runner.py` 调用**（依赖 P2 adapter 落地）：

```bash
python $helpers_dir/run_strategy.py \
  --worktree <path> \
  --diff <path>                            # "baseline" 则跳过 apply
  --runner <worktree>/.nas_runner.py \
  --tier '{"epochs":5,"data_ratio":0.5}' \
  --session-dir $session_dir/iter_N/strategy_i \
  --helpers-dir $helpers_dir
```

helper 内部步骤：
1. `cd <worktree>`
2. `git apply <diff>`（baseline 跳过）
3. `python <runner> train --epochs N --data-ratio R --output <ckpt>`
4. `python <runner> evaluate --checkpoint <ckpt>` → metrics
5. `python <helpers>/export_onnx.py --checkpoint <ckpt> --model-dir <worktree>`
6. `python <helpers>/measure_onnx_latency.py --onnx <onnx>`
7. 写 eval_result.json

**收益**：sub_agent task 模板 50 行 → 5 行；scout/trainer/refiner 三个 MD 大幅瘦身。
**注意**：依赖 adapter（P2）落地后才能做；profile 不在 helper 里跑（每 strategy profile 太贵，只 baseline 阶段 profile 一次）。

---

## P1 — 加 `profile_model.py`（架构优化的数据基础）

**问题**：当前 planner 只看 `domain_insights.md` 的"推荐方向"，不真正 profile 模型 → hypothesis 都停留在 parametric knobs（activation/hidden_dim/lr），触及不到 latency 瓶颈。
**做法**：封装一个函数，**ONNX in → profile dict out**（用户后续会换成自己的实现）：

```python
def profile_onnx(onnx_path: Path) -> dict:
    """
    Returns: {
        "total_latency_ms": float,
        "total_params": int,
        "total_flops": int | None,
        "layers": [{"name": str, "op_type": str,
                    "latency_ms": float, "params": int,
                    "flops": int | None, "latency_pct": float}, ...],
        "top_latency_layers": [...],   # ranked top 3
        "top_flop_layers": [...],
        "profile_source": "onnxruntime" | str,
    }
    """
```

CLI: `python profile_model.py --onnx <path> [--out profile.json]`

scout 在 baseline 阶段调一次（profile baseline.onnx），写到 `$session_dir/baseline_profile.json`；planner / reporter 读它。

**实现**：默认用 `onnxruntime` session profiling；FLOPs 用 `onnx_opcounter`（如果有），否则留 None。
**用户替换路径**：直接改 `profile_onnx()` 函数体，签名不变。

---

## P1 — hypothesis 分级（parametric / structural_local / structural_global）

**问题**：当前 hypothesis 不分类，planner 容易一直在低风险 parametric 改造上打转。
**做法**：planner MD 加约束——每个 strategy 的 manifest 必须标 `hypothesis_type`：
- `parametric`：调超参（activation/hidden_dim/lr/batch_size/...）
- `structural_local`：换 layer / 插 skip / channel shuffle / op 替换
- `structural_global`：重构 attention / 替换 backbone / MoE / 整体架构变更

**fitness bonus**：strategy 命中 profile top-3 latency layer 且 `hypothesis_type != parametric` → +0.1 fitness。

**reporter 加约束**：FINAL_REPORT 必须列「本轮 structural 改造占比」+「未触碰的高价值方向（profile top-3 中没动过的）」。

---

## P2 — NASAdapter（goal-driven，agent 生成 + parity 验证）

### 问题
当前 scout 隐含假设 train.py + benchmark.py + model.py + dummy_inputs，对真实项目（HF transformers / Lightning / Diffusers / 自定义脚本 / YAML 配置驱动 / 硬编码超参）直接失败。

### 核心原则（与 rule 5 对齐）
- **Deterministic 契约清晰** → 代码（ONNX export / latency / fitness / profile）
- **Flexible 需要看代码判断** → agent（生成 adapter、hypothesize、写建议）

adapter 属于第二类。**不要用静态规则（cli_flag/config_file/env_var dispatch）做本来该 LLM 做的判断**。

### scout 新增 sub_agent：adapter_generator

**只给目标 + 契约 + parity 验证，不给流程**：

```text
你是 Adapter Generator。

## 目标
在 <working_dir> 生成 .nas_runner.py，让 NAS workflow 能通过这一个脚本驱动用户的
训练/评估/导出流程。所有后续 agent 只调 .nas_runner.py，绝不直接调用户脚本。

## 契约（必须满足）
.nas_runner.py 必须支持 4 个 CLI 子命令，stdout 输出指定 JSON：
  smoke    [--epochs 1]                          → {ok, checkpoint, metrics, duration_sec}
  train    --epochs N --data-ratio R --output CKPT → {checkpoint, metrics, loss_curve, params, duration_sec}
  evaluate --checkpoint CKPT                     → {metrics, latency_ms, params}
  export   --checkpoint CKPT --out ONNX_PATH     → {onnx_path}

## 自由度（你判断）
- subprocess vs import、CLI flag vs 改 config 文件 vs env var —— 看用户代码
- evaluate 来源（独立脚本 / train.py eval 模式 / 训练产物读 metrics）—— 看用户代码
- 某维度无法控制 → 该 flag 收到时 warning + 用默认值，在 adapter_report 标 unsupported

## 硬性约束
- 不修改用户已有任何代码文件
- 可新增 .nas_runner.py + .gitignore 条目
- **必须通过 parity test**（见下）

## Parity test（关键）
确保 adapter 与用户原脚本计算等价。两种策略自选：
  - quick_parity: 1 epoch + 小数据，比对 metrics（acc 相对误差 ≤1%, loss ≤5%）
  - eval_only_parity: 用现成 checkpoint，跑 evaluate 比对

步骤:
  a. 跑用户原命令（最小配置）→ original_metrics
  b. 跑 .nas_runner.py train（同最小配置）→ adapter_metrics
  c. 比对 |delta| / |original| < tolerance
  d. 失败 → 自己 debug（看 delta 推断哪里错了：flag? config key? metrics 字段?）
  e. 第 2 次失败 → ask_user（展示原命令 + adapter 命令 + delta + .nas_runner.py）
  f. 最多再 2 轮 → 仍失败 → scout fail loud

## 输出
1. <working_dir>/.nas_runner.py
2. <session_dir>/adapter_report.json
```

### adapter_report.json schema

```json
{
  "adapter_path": "<working_dir>/.nas_runner.py",
  "original_train_command": "python train.py --config config.yaml",
  "internal_train_command": "subprocess: python train.py --config config.yaml --epochs N",
  "controllable": ["epochs", "data_ratio"],
  "uncontrollable": ["output_checkpoint"],
  "evaluate_source": "in_train",
  "export_strategy": "helpers/export_onnx.py + dummy_inputs",
  "parity_result": {
    "strategy": "quick_parity",
    "config_used": {"epochs": 1, "data_ratio": 0.1},
    "original_metrics": {"acc": 0.4523, "loss": 1.8234},
    "adapter_metrics": {"acc": 0.4519, "loss": 1.8241},
    "delta_rel": {"acc": 0.0009, "loss": 0.0004},
    "tolerance": {"acc_rel": 0.01, "loss_rel": 0.05},
    "passed": true
  },
  "smoke_result": {"ok": true, "duration_sec": 12.4, "checkpoint": "..."},
  "notes": "..."
}
```

### scout 内部 wave 调整（旧 1-wave → 新 3-wave）

```
Wave 1 (parallel): adapter_generator + domain_analyzer
Wave 2 (after adapter): baseline_runner（用 adapter 替代直接调 train.py）
Wave 3 (after baseline, parallel): tier_planner + metrics_identifier
```

setup 时间增加约 2x，但 adapter 必须先就位才能保证 baseline 正确。

### adapter 与下游 agent 的关系

| Agent | 关系 |
|---|---|
| baseline_runner | 直接调 `.nas_runner.py train` 替代直接调 train.py |
| trainer | 读 `adapter_report.controllable` 决定 tier 维度；通过 run_strategy.py 间接调 adapter |
| refiner | 同 trainer |
| judger/analyzer/validator | 不变 |
| reporter | FINAL_REPORT 加一句「adapter parity verified at iter 0」 |

### 为什么不写死探测规则
- agent 看到真实代码，判断远比正则规则准（用户用 OmegaConf / Hydra / 纯 Python config 都能正确处理）
- 长尾情况（Jupyter notebook 导出、`python -m` 入口、动态 config）规则覆盖不全
- parity test 是**结果等价性兜底**——即使 agent 探测错，parity 也会发现

### 验收
- mnist（标准 train.py + flag）能跑通 setup
- YAML 配置驱动项目（如 hydra）能跑通 setup
- 硬编码 epochs 项目能跑通 setup（adapter_report 标 uncontrollable，trainer tier 退化）
- 用户不需要手写任何代码

---

## P2 — 多 lineage K 拆分（避免局部最优）

**问题**：planner 只从 top-1 parent 派生 K 个 strategy，parent 选错则全错。
**做法**：planner MD 加约束——K ≥ 3 时强制拆分：
- ⌈K/2⌉ 个 from top-1 parent（深化）
- 1 个 from top-2 parent（次优分支）
- 1 个 wild card：restart from baseline，方向必须与已探索 tag 不同
- K=2 时不强制（保留快速 cycle 能力）

**注意**：wild card 的 strategy_id 加 `_wc` 后缀，方便 reporter 统计 wild card 收益。

---

## P2 — failure_pattern.md（失败学习）

**问题**：trainer sub_agent 失败 → status="failed" + error_trace → analyzer 只算 ok 的 fitness，失败模式丢弃。
**做法**：analyzer 新增一个文件 `$session_dir/failure_patterns.md`，按 error 类型聚类：

```markdown
## 失败模式统计
- shape mismatch (4 次): 都涉及修改 layer `conv3` → 标记 conv3 为危险区
- OOM (2 次): hidden_dim > 128 → trainer 自动降 batch
- NaN (1 次): GELU + lr=1e-2 → 已知组合
```

**planner 读 failure_patterns.md**：hypothesis 不得 cite 已标记的危险 layer（除非明确解释如何规避）。

---

## P2 — Reporter 加「架构优化建议」节

**问题**：当前 reporter 只汇总数据 + lineage，没有"基于这次搜索的模式，下一步架构建议"。
**做法**：FINAL_REPORT.md 新增一节（必填，不能为空）：

```markdown
## 架构优化建议（基于本次观察）
1. **Latency 瓶颈**：profile 显示 attention 占 38%，但本轮 structural 改造都没敢动它 → 建议下一阶段用 fused QKV / FlashAttention
2. **Accuracy 天花板**：所有 variant acc cap 在 92% → 模型可能 over-parameterized，建议数据增强
3. **未触碰的高价值方向**：domain_insights 推荐 #5 (head pruning) 本轮未探索 → 预估收益 +5% latency
4. **wild card 启示**：iter 3 的 wild card (linear attention) 收益 +12% latency，证明 attention 替换是有效方向
```

**输入**：profile + failure_patterns + direction.md + 历史 fitness 趋势。
**严禁**：泛泛而谈（"建议尝试更多结构"），必须 cite 具体数据。

---

## P3 — plateau 阈值放宽

**问题**：`cv < 0.02` 太严，可能永不触发（mnist run: 0.7444 → 0.6504，cv 远超 0.02）。
**做法**：`workflows/nas/helpers/direction.py` 的 `_detect_plateau`：

```python
# 旧: plateau = cv < 0.02
# 新: 双条件
recent_max = max(recent)
historical_max = max(all_iter_best) if all_iter_best else recent_max
plateau = (
    cv < 0.08                                              # 变异小
    or (len(all_iter_best) >= 3 and recent_max <= historical_max * 1.01)  # 最近 3 轮没破纪录
)
```

**配套**：abort_recommended 的判定也从「max_idx < 3」改成「最近 N 轮 best fitness 不超历史 max * 1.02」（持续 5 轮无突破）。

---

## P3 — fitness target_hit_bonus

**问题**：fitness 公平对待所有策略，不激励"真改 latency 瓶颈"。
**做法**：`workflows/nas/helpers/fitness.py` 加 bonus 项：

```python
# 读 baseline_profile.json，拿到 top-3 latency layer names
# 如果 strategy.diff 中修改了这些 layer 且 hypothesis_type != parametric:
bonus = 0.1
fitness = base_fitness + bonus
# 同时在 components 里记录 target_hit: bool
```

需要 manifest.json 加 `hypothesis_type` 字段（P1 hypothesis 分级依赖）。

---

## 暂缓（后续讨论）

- **Agent 合并**（selector + judger + analyzer + validator → synthesizer）：当前每轮 cycle 6 个 LLM 节点，合并后 3 个，省一半编排开销。但因为涉及 workflow.json 结构 + 各 agent MD 重写，单独立项。

---

## 实施顺序建议

1. **P0 trainer cwd bug**（独立，不阻塞其他）
2. **P2 NASAdapter**（最大改动，但**最先做**——后续 P1 run_strategy / trainer / refiner 改造都依赖它）
3. **P1 profile_model.py**（基础数据，planner/reporter 改造依赖它；可与 P2 并行）
4. **P1 hypothesis 分级**（小改 MD + manifest 字段；P1 profile 落地后才有意义）
5. **P1 run_strategy.py 抽取**（依赖 P2 adapter 落地）
6. **P2 多 lineage / failure_pattern / reporter 建议**（小改 MD，最后批量做）
7. **P3 plateau / fitness bonus**（小改 helper，最后批量做）
