---
name: deep_dive_analyst
tools: [bash]
retries: 1
---

You receive the coarse_analyzer's output identifying the worst layers. Your job: perform fine-grained analysis — distribution profiling + block-level error localization — for each worst layer, and render charts inline.

## Available bitx APIs

### Distribution profiling
```python
from src.report._study_report import StudyReport

report = StudyReport.from_file(output_dir)
result = report.get_result(config_name="W4A4")

# Distribution features
print(result.characterize.profile("layer_name", role="weight"))
# Returns: distribution_type, key_features (outlier_ratio, dynamic_range_bits, kurtosis, ...)

# Causal analysis (which layers cause downstream degradation)
print(result.characterize.causal_analysis())

# Classification
label = result.characterize.classify("layer_name", role="input")
# Returns: 'zero-centered-gaussian', 'bimodal', 'outlier-heavy', etc.
```

### Block-level error analysis
```python
from src.api.block_error_analysis import block_error_analysis

# Per-block QSNR for a specific layer+role
blk = block_error_analysis(result, layer="fc2", role="weight", top_k=10)
print(blk.worst_units)     # [(unit_idx, qsnr_db)] sorted worst-first
print(blk.stats)            # mean, std, min, max, p10, p90
print(blk.per_unit_qsnr)   # {unit_idx: qsnr_db}
```

### Chart rendering
```python
try:
    from harness.tools.chart import render_chart
except ImportError:
    render_chart = None

# If render_chart is available, use it. Otherwise emit via stdout:
import json
chart_data = {
    "chart_type": "bar",
    "data": [{"block_idx": str(k), "qsnr_db": v} for k, v in qsnr.items()],
    "x": "block_idx", "y": "qsnr_db",
    "title": f"Block Error: {layer} ({config})"
}
if render_chart:
    render_chart(**chart_data)
else:
    print(f"__HARNESS_CHART__: {json.dumps(chart_data)}")
```

## Analysis strategy

### For each worst layer:

1. **Distribution profile** (both weight and input roles)
   - Get `characterize.profile()` for weight and input
   - Classify: outlier-heavy? bimodal? high dynamic range?
   - Record key_features: outlier_ratio, dynamic_range_bits, kurtosis

2. **Block-level error** (both weight and input)
   - Call `block_error_analysis()` for weight (per-block) and input (per-channel)
   - Identify worst blocks/channels
   - Classify error pattern:
     - "concentrated" → few blocks have most of the error
     - "uniform" → error spread evenly
     - "channel-boundary" → blocks at channel edges are worse
     - "outlier_channel" → 1-2 channels dominate the error

3. **Render charts**
   - Bar chart: per-block QSNR for weight (worst blocks highlighted)
   - Bar chart: per-channel QSNR for activation (outlier channels highlighted)
   - Use render_chart or __HARNESS_CHART__ mechanism

### Format weakness identification

After analyzing all worst layers, identify format-level weaknesses:
- If outlier_ratio > 20% in multiple layers at low bit-width → "format cannot represent outlier-heavy distributions"
- If per_block QSNR varies >20dB → "block granularity too coarse for this distribution"
- If bimodal distributions appear → "single scale cannot serve two clusters"

## Script structure

Write a single Python script that iterates over `worst_layer_names`, performs all analysis, and prints structured results. Use the `__HARNESS_CHART__` stdout mechanism for chart rendering (works in both harness and standalone environments).
