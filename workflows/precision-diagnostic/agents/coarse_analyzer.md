---
name: coarse_analyzer
tools: [bash]
retries: 1
---

You receive the quant_study output with the directory containing the StudyReport. Your job: perform the first-pass coarse analysis — accuracy gaps, bottleneck decomposition, layer ranking, and role attribution — all in one pass.

## Available bitx APIs

```python
from src.report._study_report import StudyReport
from src.analysis.cross_config_ranking import CrossConfigLayerRanking
from src.analysis.transform_effect import TransformEffectReport

# Load study results
report = StudyReport.from_file(output_dir)

# Cross-config layer ranking
ranking = CrossConfigLayerRanking.from_study(report)
worst = ranking.consistent_worst(k=5)           # Layers bad in ALL configs
specific = ranking.config_specific_worst(config="W4A4", k=3)  # Bad only in one config
delta = ranking.layer_qsnr_delta("fc2", from_config="W4A4", to_config="W8A8")
role_dom = ranking.role_dominance_cross_config(k=5)

# Transform effect
transform_report = TransformEffectReport.from_study(report)
print(transform_report.summary())
per_config = transform_report.per_config_recovery()

# Per-session diagnostics
result = report.get_result(config_name="W4A4")
print(result.diagnose.summary())
print(result.diagnose.per_role_table())
print(result.diagnose.top_k(k=5))
print(result.diagnose.error_source())
```

## Analysis strategy

### 1. Accuracy gap overview
- Load accuracy per config from the StudyReport
- Compute deltas from FP32 baseline
- Determine the primary bottleneck:
  - **Weight degradation**: accuracy drop from weight bit reduction (e.g., W8A8→W4A8)
  - **Activation degradation**: accuracy drop from activation bit reduction (e.g., W4A8→W4A4)
  - If both are similar → "both"

### 2. Layer attribution
- Use `CrossConfigLayerRanking` to find:
  - `consistent_worst(k=5)`: layers that are worst across ALL configs (structurally problematic)
  - `config_specific_worst`: layers that degrade only at lower bit-widths (format sensitivity)
- For each worst layer, determine `dominant_role` using `role_dominance_cross_config`
- Collect `role_qsnr` per layer (input, weight, output QSNR values)

### 3. Transform effect
- Use `TransformEffectReport` to quantify how much each transform recovers
- Record per-config recovery percentages

### 4. Build worst_layer_names
- Collect the layer names from `consistent_worst` (top 5)
- This list is consumed by downstream agents (deep_dive_analyst, intervention_explorer)

## Script structure

```bash
cat << 'COARSE_EOF' > /tmp/coarse_analysis.py
import sys, json

from src.report._study_report import StudyReport
from src.analysis.cross_config_ranking import CrossConfigLayerRanking
from src.analysis.transform_effect import TransformEffectReport

report = StudyReport.from_file('<output_dir>')

# Accuracy per config
configs = {}
for part_results in report._results.values():
    for sr in part_results:
        if sr.quant_metrics:
            acc = sr.quant_metrics.get("accuracy") or sr.quant_metrics.get("acc")
            if acc is not None:
                configs[sr.name] = acc

# ... rest of analysis ...

print("COARSE_RESULT=" + json.dumps(result, default=str))
COARSE_EOF

python /tmp/coarse_analysis.py
```

Parse the output and populate all fields of CoarseAnalysis. The `worst_layer_names` field should contain 3–5 layer names for downstream agents to focus on.
