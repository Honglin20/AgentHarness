---
name: layer_attribution
tools: [bash]
retries: 1
---

You receive the study_runner's output. Your job: find which layers are consistently worst across configs and attribute errors to weight vs activation roles.

## Step 1: Run layer attribution analysis

```bash
cat << 'LAYER_EOF' > /tmp/layer_attribution.py
import sys, json

from src.report._study_report import StudyReport
from src.analysis.cross_config_ranking import CrossConfigLayerRanking

report = StudyReport.from_file('<output_dir>')
ranking = CrossConfigLayerRanking.from_study(report)

# Consistent worst across all configs
consistent = ranking.consistent_worst(k=5)

# Per-config worst
config_specific = []
for config_name in ranking.config_names:
    worst = ranking.config_specific_worst(config=config_name, k=3)
    for layer, qsnr in worst:
        config_specific.append({
            "layer": layer,
            "config": config_name,
            "qsnr_db": qsnr,
        })

# Cross-config deltas — use get_layer_qsnr for raw values
deltas = []
for layer, _ in consistent:
    w8 = ranking.get_layer_qsnr(layer, "W8A8")
    w4a8 = ranking.get_layer_qsnr(layer, "W4A8")
    w4a4 = ranking.get_layer_qsnr(layer, "W4A4")
    w4a8_d = (w4a8 - w8) if (w4a8 is not None and w8 is not None) else None
    w4a4_d = (w4a4 - w4a8) if (w4a4 is not None and w4a8 is not None) else None
    deltas.append({
        "layer": layer,
        "w8a8_qsnr": w8,
        "w4a8_qsnr": w4a8,
        "w4a4_qsnr": w4a4,
        "w4a8_delta": w4a8_d,
        "w4a4_delta": w4a4_d,
    })

# Role dominance from role_dominance_cross_config
role_info = ranking.role_dominance_cross_config(k=5)

result = {
    "consistent_worst": [
        {
            "layer": layer,
            "avg_qsnr_db": avg_qsnr,
        }
        for layer, avg_qsnr in consistent
    ],
    "config_specific_worst": config_specific,
    "cross_config_delta": deltas,
    "role_dominance": role_info,
    "summary": ranking.summary(),
}
print("LAYER_RESULT=" + json.dumps(result, default=str))
LAYER_EOF

python /tmp/layer_attribution.py
```

## Step 2: Analyze and report

From the output:
- List layers that are consistently worst across all configs
- For each consistent worst layer, fill in:
  - `worst_config`: find which config gives the lowest QSNR from cross_config_delta
  - `worst_qsnr_db`: the QSNR in that worst config
  - `dominant_role`: infer from role_dominance data or from per-role QSNR (check which role — "input" or "weight" — has lower QSNR)
  - `role_qsnr`: from the SessionResult's qsnr_by_role if available
- List config_specific_worst layers
- Show QSNR degradation from W8A8 → W4A8 → W4A4 for each worst layer

If role data is not available from the serialized report, set dominant_role to "unknown".

Report the full LayerAttribution with all fields populated.
