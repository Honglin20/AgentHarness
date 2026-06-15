# baseline_runner (scout sub_agent task spec)

> scout 的 Wave 2 sub_agent，isolation="worktree"。
> 在 adapter 通过 smoke 三件套后被 issue。通过 `run_strategy.py` 跑 baseline 1 epoch + evaluate + export onnx + measure latency，写 baseline.json。

## 输入（scout 在 task 字符串里传入）

- `working_dir`（用户项目绝对路径）
- `session_dir`（写 baseline.json 的位置）
- `helpers_dir`（`run_strategy.py` / `export_onnx.py` / `measure_onnx_latency.py` / `profile_model.py` 所在）
- adapter 已就绪：`<working_dir>/_nas_adapter.py` 通过 smoke 三件套
- project_analysis 已就绪：`<session_dir>/project_analysis.json`

## 步骤

### 1. 跑 baseline（1 epoch + evaluate + export + latency via run_strategy.py）

```bash
python <helpers_dir>/run_strategy.py \
  --worktree <working_dir> \
  --diff baseline \
  --adapter-path <working_dir>/_nas_adapter.py \
  --tier '{"epochs": 1}' \
  --out <session_dir>/baseline_eval.json \
  --helpers-dir <helpers_dir> \
  --strategy-id baseline
```

run_strategy.py 内部完成（单一入口，避免双套调用代码）：
- cd worktree（git apply diff="baseline" 时跳过 patch）
- `_nas_adapter.get_model()` 实例化
- `_nas_adapter.train(epochs=1)` 跑训练
- `_nas_adapter.evaluate()` 跑评估
- `helpers/export_onnx.py` 导出 ONNX
- `helpers/measure_onnx_latency.py` 测 ONNX latency
- 写 `<session_dir>/baseline_eval.json`

读 `baseline_eval.json` 拿：`metrics` / `latency_ms` / `onnx_latency_ms` / `onnx_path` / `params` / `loss_curve` / `duration_sec` / `tier_applied`。

**失败处理**：run_strategy.py exit code 非 0 → 读 stderr 中的 `error_trace`，结构化返回 scout（scout 决定 ask_user 还是 abort）。

### 2. 推断 `total_epochs`

读 `<session_dir>/project_analysis.json` 的 `epochs_default`：
- 不是 null → 用此值
- null → 默认 10，stderr 写 warning

### 3. Profile baseline 模型（per-layer latency / params）

```bash
python <helpers_dir>/profile_model.py \
  --onnx <session_dir>/model.onnx \
  --out <session_dir>/baseline_profile.json
```

**失败处理**：profile 失败不阻塞 baseline.json 写入（`profile_path` 留 null，stderr warning）。reporter 读 profile 给架构建议时跳过。

### 4. 写 `<session_dir>/baseline.json`（严格按 BaselineFile schema 重组）

**关键**：不要直接复制 `baseline_eval.json` 内容！必须按以下 schema **重组**字段。

```json
{
  "metrics": <dict, e.g. {"acc": 0.86, "loss": 0.45} — from baseline_eval.json["metrics"]>,
  "latency_ms": <float, from baseline_eval.json["latency_ms"]>,
  "onnx_latency_ms": <float or null, from baseline_eval.json["onnx_latency_ms"]>,
  "onnx_path": <str or null, from baseline_eval.json["onnx_path"]>,
  "params": <int, from baseline_eval.json["params"]>,
  "one_epoch_sec": <float, from baseline_eval.json["duration_sec"]>,
  "total_epochs": <int, step 2 推断 from project_analysis.json["epochs_default"]>,
  "full_training_duration_sec": <float, one_epoch_sec * total_epochs>,
  "profile_path": "<session_dir>/baseline_profile.json or null"
}
```

**严禁字段**（不要写入 baseline.json）：
- ❌ 顶级 `accuracy` / `acc`（必须放进 `metrics` dict）
- ❌ `config` / `train_duration_sec` / `loss_curve`（不是 BaselineFile schema）
- ❌ `status` / `strategy_id` / `tier_applied`（这些是 baseline_eval.json 的字段，不是 baseline.json）

ONNX 导出/测量失败不阻塞 baseline.json 写入，但 `onnx_latency_ms` / `onnx_path` 留 null。

**示例（mnist 项目正确输出）**：
```json
{
  "metrics": {"acc": 0.8611, "loss": 0.4523},
  "latency_ms": 0.0261,
  "onnx_latency_ms": 0.0679,
  "onnx_path": "/path/to/baseline.onnx",
  "params": 9226,
  "one_epoch_sec": 31.72,
  "total_epochs": 5,
  "full_training_duration_sec": 158.59,
  "profile_path": "/path/to/baseline_profile.json"
}
```

## 返回 scout 的 summary

```json
{
  "status": "ok" | "failed",
  "baseline_path": "<session_dir>/baseline.json",
  "one_epoch_sec": <float>,
  "total_epochs": <int>,
  "summary": "baseline done: acc=<X>, latency=<Y>ms, T_full=<Z>s"
}
```

## 严禁

- ❌ 直接调 `train.py` / `evaluate.py` / `benchmark_command` / `training_command`（必须走 `_nas_adapter.py`）
- ❌ 跑 > 1 epoch（baseline 只测 1 epoch 估时；`--tier '{"epochs": 1}'` 是硬约束）
- ❌ 修改用户任何代码
- ❌ 把 baseline.json 写到 working_dir（必须 session_dir）
- ❌ 跳过 run_strategy.py（不要直接调 `_nas_adapter.train`，单一路径避免双套调用代码）
- ❌ 跳过 profile_model.py（即使失败也要尝试，reporter 需要 per-layer latency）
