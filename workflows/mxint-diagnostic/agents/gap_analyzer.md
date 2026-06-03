---
name: gap_analyzer
tools: [bash]
retries: 1
---

You receive the study_runner's output with the directory containing the StudyReport. Your job: analyze accuracy gaps across configs and decompose weight vs activation degradation.

## Step 1: Read the study results

Load the StudyReport from the saved directory and compute gap analysis:

```bash
cat << 'GAP_EOF' > /tmp/gap_analysis.py
import sys, json

from src.report._study_report import StudyReport
from src.analysis.transform_effect import TransformEffectReport

report = StudyReport.from_file('<output_dir>')

# Collect accuracy per config
configs = {}
for part_results in report._results.values():
    for sr in part_results:
        # quant_metrics is a dict like {"accuracy": 0.91, "loss": 0.12}
        if sr.quant_metrics:
            acc = sr.quant_metrics.get("accuracy") or sr.quant_metrics.get("acc")
            if acc is not None:
                configs[sr.name] = acc

# Use W8A8 as FP32 proxy (best quantized result)
fp32_acc = configs.get("W8A8", max(configs.values()) if configs else 0.0)

# Decompose degradation
w8a8 = configs.get("W8A8")
w4a8 = configs.get("W4A8")
w4a4 = configs.get("W4A4")

weight_deg = (w4a8 - w8a8) if (w4a8 is not None and w8a8 is not None) else 0.0
act_deg = (w4a4 - w4a8) if (w4a4 is not None and w4a8 is not None) else 0.0
primary = "weight" if abs(weight_deg) > abs(act_deg) else "activation"
if abs(weight_deg - act_deg) < 0.005:
    primary = "both"

# Transform effects
transform_report = TransformEffectReport.from_study(report)
print(transform_report.summary())

# Output structured results
result = {
    "fp32_accuracy": fp32_acc,
    "config_results": [
        {"name": name, "accuracy": acc, "delta_from_fp32": acc - fp32_acc}
        for name, acc in sorted(configs.items())
    ],
    "weight_degradation": weight_deg,
    "activation_degradation": act_deg,
    "primary_bottleneck": primary,
    "transform_recovery": transform_report.per_config_recovery(),
    "summary": f"W8A8→W4A8: {weight_deg:.4f}, W4A8→W4A4: {act_deg:.4f}, bottleneck: {primary}"
}
print("GAP_RESULT=" + json.dumps(result, default=str))
GAP_EOF

python /tmp/gap_analysis.py
```

## Step 2: Analyze and report

From the output:
- Identify which degradation step causes more loss (weight bit reduction vs activation bit reduction)
- Quantify transform recovery for each config
- Determine the primary bottleneck

Report the full GapAnalysis with all fields populated.
