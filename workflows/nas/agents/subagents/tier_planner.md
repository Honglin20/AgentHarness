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

2. 读 `<session_dir>/project_analysis.json`：
   - `epochs_controllable`：bool（adapter 能否控制 epochs 维度）
   - 注意：data_ratio 维度已删除（silent correctness risk with Subset wrapping — 破坏 sampler / class balance / BN 统计）

3. 决定 tier 系统（仅 epochs 维度）：

   | T | epochs_controllable | tier 数 | 配置 | max_tier |
   |---|---|---|---|---|
   | T < 300s | * | 1 tier | search=full | 0 |
   | 300s ≤ T | true | 2 tier | search=partial_epoch, refine=full | 1 |
   | 300s ≤ T | false | 1 tier（强制） | search=full | 0 |

   说明：
   - 单 tier 时所有 strategy 跑完整训练（用户默认 epochs）
   - 2 tier 时 search 用少 epochs（如 1-3 epoch），refine 用 full epochs（用户默认）
   - data_ratio 已删除，不再有 3 tier 矩阵

4. **Tier 退化**：
   - epochs_controllable=false → 强制 1 tier（rationale 写"epochs hardcoded, cannot differentiate tier"）
   - 在 rationale 写清退化原因

5. 写 `<session_dir>/budget.json`：
   ```json
   {
     "baseline_duration_sec": <float>,
     "one_epoch_sec": <float>,
     "total_epochs": <int>,
     "tier_recommendation": {
       "rationale": "<基于 T + epochs_controllable 给出推荐理由，含退化说明>",
       "proposed_tiers": [{"name": "search", "epochs": <Y or null>}, ...],
       "max_tier": <N>,
       "degraded_dimensions": ["epochs" | 空]
     },
     "target_latency_ms": <from inputs>,
     "acc_tolerance": <from inputs>,
     "strategies_per_iter": <from inputs>
   }
   ```

   注意：`proposed_tiers` 的 `epochs` 字段为 null 时表示"用户默认 epochs"（run_strategy.py 会用 None 调 adapter.train）。

## 返回 scout 的 summary

```json
{
  "status": "ok",
  "max_tier": <N>,
  "degraded_dimensions": [...],
  "summary": "tier: max=<N>, T=<sec>, epochs_controllable=<bool>, degraded=<...>"
}
```

## 严禁

- ❌ 自创 tier 系统（必须按 T + epochs_controllable 分档表）
- ❌ 输出 data_ratio 字段（已删除，Pydantic 验证会拒绝）
- ❌ 忽略 epochs_controllable=false（必须强制 1 tier 退化）
- ❌ 把 budget.json 写到 working_dir
