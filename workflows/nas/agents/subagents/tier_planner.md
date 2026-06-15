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

3. 决定 tier 系统（**仅 epochs 维度，禁止 data_ratio**）：

   | T | epochs_controllable | tier 数 | 配置 | max_tier |
   |---|---|---|---|---|
   | T < 300s | * | 1 tier | search=full | 0 |
   | 300s ≤ T | true | 2 tier | search=partial_epoch, refine=full | 1 |
   | 300s ≤ T | false | 1 tier（强制） | search=full | 0 |

   **绝对禁止**：
   - ❌ 输出 3 tier（subset_data 这一档已删除，data_ratio 维度不存在）
   - ❌ 任何 tier 字段里写 `data_ratio`（schema 已删除，Pydantic 验证会拒绝）
   - ❌ 输出 `tier_index` / `description` / `search_space_params` / `tier_transition_rules` 等额外字段（不是 TierSpec schema）

   说明：
   - 单 tier 时所有 strategy 跑完整训练（用户默认 epochs）
   - 2 tier 时 search 用少 epochs（如 1-3 epoch），refine 用 full epochs（用户默认）

4. **Tier 退化**：
   - epochs_controllable=false → 强制 1 tier（rationale 写"epochs hardcoded, cannot differentiate tier"）
   - 在 rationale 写清退化原因

5. 写 `<session_dir>/budget.json`（严格按 BudgetFile schema）：

   ```json
   {
     "baseline_duration_sec": <float, T from baseline.json>,
     "one_epoch_sec": <float, from baseline.json>,
     "total_epochs": <int, from baseline.json>,
     "tier_recommendation": {
       "rationale": "<str, 简短说明，含退化说明>",
       "proposed_tiers": [
         {"name": "search", "epochs": <int or null>},
         {"name": "refine", "epochs": <int or null>}
       ],
       "max_tier": <int, 0 or 1>,
       "degraded_dimensions": ["epochs"]   // 或 [] 当 epochs_controllable=true
     },
     "target_latency_ms": <float, from workflow inputs>,
     "acc_tolerance": <float, from workflow inputs>,
     "strategies_per_iter": <int, from workflow inputs>
   }
   ```

   **关键约束**：
   - `proposed_tiers` 的每个 tier **只能有** `name` 和 `epochs` 字段（TierSpec schema）。**禁止** `data_ratio` / `tier_index` / `description`。
   - `degraded_dimensions` 只能是 `["epochs"]` 或 `[]`（不能是 data_ratio）。
   - max_tier 只能是 0 或 1（2 tier 矩阵已删除）。

   **mnist 示例（baseline T=158s, epochs_controllable=true）**：
   ```json
   {
     "baseline_duration_sec": 158.59,
     "one_epoch_sec": 31.72,
     "total_epochs": 5,
     "tier_recommendation": {
       "rationale": "T=158s ≥ 300s threshold? no (T<300s); 1 tier forced. Wait, 158<300 so single tier. epochs controllable via --epochs flag.",
       "proposed_tiers": [{"name": "search", "epochs": null}],
       "max_tier": 0,
       "degraded_dimensions": []
     },
     "target_latency_ms": 0.05,
     "acc_tolerance": 0.02,
     "strategies_per_iter": 3
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
