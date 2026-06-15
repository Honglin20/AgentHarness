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

5. 写 `<session_dir>/budget.json`（**必须用 helper，禁止手写 JSON**）：

   **关键**：不要手写 budget.json（容易 schema 不一致 + 用旧 3-tier 矩阵）！必须调 helper：

   ```bash
   python <helpers_dir>/make_budget.py \
     --baseline <session_dir>/baseline.json \
     --project-analysis <session_dir>/project_analysis.json \
     --target-latency <from workflow inputs> \
     --acc-tolerance <from workflow inputs> \
     --strategies-per-iter <from workflow inputs> \
     --out <session_dir>/budget.json
   ```

   Helper deterministic 决定 tier 系统（基于 T + epochs_controllable）：
   - T < 300s → 1 tier（max_tier=0）
   - T ≥ 300s + epochs_controllable=true → 2 tier（max_tier=1）
   - T ≥ 300s + epochs_controllable=false → 1 tier forced

   Helper 强制 BudgetFile schema（无 `_meta` / `budget_allocation` / `description` 等额外字段，无 `data_ratio`）。

   Helper 失败会 exit 1。看到错误 → 检查 baseline.json 是否有 `full_training_duration_sec` 字段、project_analysis.json 是否有 `epochs_controllable` 字段，修复后重跑。**不要绕过 helper 手写 JSON**。

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
