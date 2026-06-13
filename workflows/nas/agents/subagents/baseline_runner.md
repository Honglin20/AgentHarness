# baseline_runner (scout sub_agent task spec)

> scout 的 Wave 2 sub_agent，isolation="worktree"。
> 在 adapter 通过 parity 后被 issue。跑 baseline 训练 + 评估 + ONNX 导出 + 测延迟，写 baseline.json。

## 输入（scout 在 task 字符串里传入）

- `working_dir`（用户项目绝对路径）
- `session_dir`（写 baseline.json 的位置）
- `helpers_dir`（export_onnx.py / measure_onnx_latency.py 所在）
- adapter 已就绪：`<working_dir>/.nas_runner.py` 通过 parity test

## 步骤

1. `cd <working_dir>`

2. 跑 baseline 训练（1 epoch via adapter）：
   ```
   python <working_dir>/.nas_runner.py train --epochs 1 --output <session_dir>/baseline_ckpt.pt
   ```
   解析 stdout 最后一行 JSON：`metrics` / `loss_curve` / `params` / `duration_sec`

3. 跑 evaluate（验证 baseline + 测推理 latency）：
   ```
   python <working_dir>/.nas_runner.py evaluate --checkpoint <session_dir>/baseline_ckpt.pt
   ```
   拿 `metrics` / `latency_ms` / `params`

4. 推断 `total_epochs`：
   - 优先读 `<session_dir>/adapter_report.json` 的 `defaults.epochs`（adapter_generator 探测到的用户默认值）
   - 否则 parse `<working_dir>/train.py` 的 argparse defaults
   - 都拿不到 → 默认 10，stderr 写 warning

5. 导出 ONNX：
   ```
   python <helpers_dir>/export_onnx.py --checkpoint <session_dir>/baseline_ckpt.pt \
     --out <session_dir>/baseline.onnx --model-dir <working_dir>
   ```
   失败处理：export_onnx.py 自动调 `model.dummy_inputs()` 推导 forward 签名；
   缺 dummy_inputs → 读 forward 签名 + append 到 `<working_dir>/model.py` 末尾重试。

6. 测 ONNX latency：
   ```
   python <helpers_dir>/measure_onnx_latency.py --onnx <session_dir>/baseline.onnx \
     --out <session_dir>/baseline_onnx_latency.json --model-dir <working_dir>
   ```

7. Profile baseline 模型（per-layer latency / params，给 planner 做 hypothesis 定位用）：
   ```
   python <helpers_dir>/profile_model.py --onnx <session_dir>/baseline.onnx \
     --out <session_dir>/baseline_profile.json
   ```
   失败处理：profile 失败不阻塞 baseline.json 写入（profile_path 留 null，stderr warning）。

8. 写 `<session_dir>/baseline.json`：
   ```json
   {
     "metrics": {<name>: <val>, ...},
     "latency_ms": <float, from adapter evaluate>,
     "onnx_latency_ms": <float, from baseline_onnx_latency.json latency_ms_median>,
     "onnx_path": "<session_dir>/baseline.onnx",
     "params": <int, from adapter train>,
     "one_epoch_sec": <float, from adapter train duration_sec>,
     "total_epochs": <int, step 4 推断>,
     "full_training_duration_sec": <one_epoch_sec * total_epochs>,
     "profile_path": "<session_dir>/baseline_profile.json or null"
   }
   ```

ONNX 导出/测量失败不阻塞 baseline.json 写入，但 `onnx_latency_ms` 留 null。

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

- ❌ 直接调 `train.py` / `evaluate.py` / `benchmark_command` / `training_command`（必须走 `.nas_runner.py`）
- ❌ 跑 > 1 epoch（baseline 只测 1 epoch 估时）
- ❌ 修改用户任何代码（ONNX fallback 例外：可 append dummy_inputs 到 model.py）
- ❌ 把 baseline.json 写到 working_dir
