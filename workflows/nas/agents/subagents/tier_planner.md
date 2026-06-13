# tier_planner (scout sub_agent task spec)

> scout 的 Wave 3 sub_agent，isolation="none"。baseline.json 写完后并发 issue（与 metrics_identifier 同时）。

## 输入（scout 在 task 字符串里传入）

- `session_dir`
- workflow inputs（`target_latency_ms` / `acc_tolerance` / `strategies_per_iter`）由 scout 在 task 里传入

## 步骤

1. 读 `<session_dir>/baseline.json`：
   - `full_training_duration_sec` (T)
   - `one_epoch_sec`
   - `total_epochs`

2. 读 `<session_dir>/adapter_report.json`：
   - `controllable`：adapter 能控制的维度（如 `["epochs", "data_ratio"]`）
   - `uncontrollable`：不能控制的维度（如 `["output_checkpoint"]`）

3. 决定 tier 系统按 T 分档：

   | T | tier 数 | 配置 | max_tier |
   |---|---|---|---|
   | T < 300s | 1 tier | search=full | 0 |
   | 300s ≤ T < 1800s | 2 tier | search=partial_epoch, refine=full | 1 |
   | T ≥ 1800s | 3 tier | search=subset_data, refine_1=partial, refine_2=full | 2 |

4. **Tier 退化**（基于 `uncontrollable`）：
   - 含 `"epochs"` → 不能用 epochs 区分 tier（partial_epoch 不可达）→ 退化到只用 data_ratio
   - 含 `"data_ratio"` → 不能用 data_ratio 区分（subset_data 不可达）
   - 两者都含 → 单 tier，所有 strategy 跑完整训练
   - 在 rationale 写清退化原因

5. 写 `<session_dir>/budget.json`：
   ```json
   {
     "baseline_duration_sec": <float>,
     "one_epoch_sec": <float>,
     "total_epochs": <int>,
     "tier_recommendation": {
       "rationale": "<基于 T + adapter controllable 给出推荐理由，含退化说明>",
       "proposed_tiers": [{"name": "search", "data_ratio": <X>, "epochs": <Y>}, ...],
       "max_tier": <N>,
       "degraded_dimensions": ["epochs" | "data_ratio" | 空]
     },
     "target_latency_ms": <from inputs>,
     "acc_tolerance": <from inputs>,
     "strategies_per_iter": <from inputs>
   }
   ```

## 返回 scout 的 summary

```json
{
  "status": "ok",
  "max_tier": <N>,
  "degraded_dimensions": [...],
  "summary": "tier: max=<N>, T=<sec>, degraded=<...>"
}
```

## 严禁

- ❌ 自创 tier 系统（必须按 T 分档表）
- ❌ 忽略 uncontrollable（必须做退化处理）
- ❌ 把 budget.json 写到 working_dir
