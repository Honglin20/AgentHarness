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

### 4. 写 `<session_dir>/baseline.json`（**必须用 helper，禁止手写 JSON**）

**关键**：不要手写 baseline.json（容易 schema 不一致）！必须调 helper：

```bash
python <helpers_dir>/make_baseline.py \
  --eval-result <session_dir>/baseline_eval.json \
  --project-analysis <session_dir>/project_analysis.json \
  --profile-path <session_dir>/baseline_profile.json \
  --out <session_dir>/baseline.json
```

Helper 强制 BaselineFile schema：
- `metrics` 必须是 dict（如 `{"acc": 0.86}`）
- `latency_ms` 必须是 float（不是 dict）
- `total_epochs` 从 `project_analysis.epochs_default` 读
- `one_epoch_sec` 从 `baseline_eval.duration_sec` 读
- `full_training_duration_sec` = one_epoch_sec * total_epochs

Helper 失败（schema 不匹配）会 exit 1 + stderr 错误信息。看到错误 → 修复输入（baseline_eval.json 或 project_analysis.json）后重跑 helper。**不要绕过 helper 手写 JSON**。

ONNX 导出/测量失败不阻塞：`onnx_latency_ms` / `onnx_path` 留 null，helper 自动处理。

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
