---
name: distribution_profiler
tools: [bash]
retries: 1
---

You receive the layer_attribution's output identifying the worst layers. Your job: profile the distribution characteristics of those layers and identify format weaknesses.

## Step 1: Run distribution profiling

```bash
cat << 'DIST_EOF' > /tmp/dist_profile.py
import sys, json

from src.report._study_report import StudyReport

report = StudyReport.from_file('<output_dir>')

# Get worst layers from layer_attribution (passed as input)
worst_layers = <worst_layers_list>  # e.g. ["layer1", "layer2", ...]

profiles = []
for config_name, results in report._results.items():
    for r in results:
        if r.name not in ["W4A4", "W4A8"]:
            continue
        for layer in worst_layers:
            if layer not in (r.observers_data or {}):
                continue
            for role in ["weight", "input"]:
                layer_data = r.observers_data[layer].get(role, {})
                # Extract distribution info from observers
                # Look for distribution metrics in the observer data
                for stage, slices in layer_data.items():
                    for key, metrics in slices.items():
                        if isinstance(metrics, dict):
                            qsnr = metrics.get("qsnr_db", None)
                            # Extract distribution features
                            outlier_ratio = metrics.get("outlier_ratio", None)
                            dynamic_range = metrics.get("dynamic_range_bits", None)
                            kurtosis = metrics.get("kurtosis", None)
                            if qsnr is not None:
                                profile = {
                                    "layer": layer,
                                    "role": role,
                                    "config": r.name,
                                    "qsnr_db": qsnr,
                                    "distribution_type": "unknown",
                                    "key_features": {
                                        k: v for k, v in [
                                            ("outlier_ratio", outlier_ratio),
                                            ("dynamic_range_bits", dynamic_range),
                                            ("kurtosis", kurtosis),
                                        ] if v is not None
                                    },
                                }
                                profiles.append(profile)

result = {
    "layer_profiles": profiles,
    "causal_summary": "",
    "format_weaknesses": [],
    "summary": f"Profiled {len(profiles)} layer-role-config combinations",
}
print("DIST_RESULT=" + json.dumps(result, default=str))
DIST_EOF

python /tmp/dist_profile.py
```

## Step 2: Analyze distribution patterns

For each profiled layer:
- Classify the distribution type: "zero-centered-gaussian", "outlier-heavy", "bimodal", "heavy-tailed"
- Use key_features (outlier_ratio, dynamic_range_bits, kurtosis) to diagnose:
  - outlier_ratio > 5% → outlier-heavy
  - kurtosis > 5 → heavy-tailed
  - dynamic_range_bits > 8 → exceeds int4 representable range
- Identify format weaknesses:
  - int4 with dynamic_range > 8 bits: "int4 cannot represent the dynamic range"
  - High outlier ratio with per_block granularity: "outliers dominate single-scale blocks"

## Step 3: Provide diagnosis and suggestions

For each layer:
- Write a human-readable diagnosis explaining WHY quantization fails
- Suggest concrete actions (SmoothQuant, per-channel scaling, mixed precision, etc.)

Report the full DistributionProfile with all fields populated.
