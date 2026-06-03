---
name: summary_painter
tools: [bash]
retries: 1
---

You receive outputs from three agents: coarse_analyzer, deep_dive_analyst, and intervention_explorer. Your job has two parts:

1. **Render all charts inline** using render_chart() — paint a complete visual report in the conversation
2. **Synthesize all findings** into a final DiagnosticReport

## Chart rendering API

```python
try:
    from harness.tools.chart import render_chart
except ImportError:
    render_chart = None

import json

def chart(data, chart_type, x, y, title, **kwargs):
    """Render a chart via harness or stdout fallback."""
    payload = {"chart_type": chart_type, "data": data, "x": x, "y": y, "title": title, **kwargs}
    if render_chart:
        render_chart(**payload)
    else:
        print(f"__HARNESS_CHART__: {json.dumps(payload)}")
```

## Charts to render

Render these charts in order. Each chart should use data from the previous agents' structured outputs.

### Chart 1: Accuracy Overview (table)
```python
data = [
    {"metric": "FP32 Baseline", "value": fp32_accuracy},
    {"metric": "W8A8", "value": w8a8_accuracy},
    {"metric": "W4A4", "value": w4a4_accuracy},
    ...
]
chart(data, "table", x="metric", y="value", title="Accuracy Overview")
```

### Chart 2: Accuracy Comparison (bar)
```python
data = [{"config": c.name, "accuracy": c.accuracy, "delta": c.delta} for c in config_results]
chart(data, "bar", x="config", y="accuracy", title="Accuracy by Configuration")
```

### Chart 3: Degradation Decomposition (bar)
```python
data = [
    {"source": "Weight (W8→W4)", "degradation": weight_degradation},
    {"source": "Activation (A8→A4)", "degradation": activation_degradation},
]
chart(data, "bar", x="source", y="degradation", title="Degradation Decomposition")
```

### Chart 4: Per-Layer QSNR (bar)
Read from the StudyReport:
```python
from src.report._study_report import StudyReport
report = StudyReport.from_file(output_dir)
result = report.get_result(config_name=target_format)
diag = result.diagnose.top_k(k=10)
data = [{"layer": d.layer, "qsnr_db": d.qsnr_db, "role": d.dominant_role} for d in diag]
chart(data, "bar", x="layer", y="qsnr_db", hue="role", title=f"Per-Layer QSNR ({target_format})")
```

### Chart 5: Error Propagation (line)
```python
diag_all = result.diagnose.summary()  # all layers in order
data = [{"layer_idx": i, "qsnr_db": d.qsnr_db, "type": "output"} for i, d in enumerate(diag_all)]
chart(data, "line", x="layer_idx", y="qsnr_db", hue="type", title="Error Propagation Across Layers")
```

### Chart 6: Per-Role QSNR for Worst Layers (bar)
```python
# From coarse_analyzer consistent_worst
data = []
for wl in consistent_worst:
    for role, qsnr in wl.role_qsnr.items():
        data.append({"layer": wl.layer, "role": role, "qsnr_db": qsnr})
chart(data, "bar", x="layer", y="qsnr_db", hue="role", title="Role Attribution for Worst Layers")
```

### Chart 7: Block Error for Worst Layer (bar)
```python
# From deep_dive_analyst block_analyses
for ba in block_analyses[:3]:  # top 3 layers
    if ba.weight_block_qsnr:
        data = [{"block_idx": k, "qsnr_db": v} for k, v in ba.weight_block_qsnr.items()]
        chart(data, "bar", x="block_idx", y="qsnr_db",
              title=f"Block QSNR: {ba.layer} ({ba.config})")
```

### Chart 8: Channel Error for Worst Layer (bar)
```python
for ba in block_analyses[:3]:
    if ba.activation_channel_qsnr:
        data = [{"channel_idx": k, "qsnr_db": v} for k, v in ba.activation_channel_qsnr.items()]
        chart(data, "bar", x="channel_idx", y="qsnr_db",
              title=f"Channel QSNR: {ba.layer} (input)")
```

### Chart 9: Intervention Recovery (bar)
```python
# From intervention_explorer
data = []
for r in single_layer_recovery:
    data.append({"layer": r.layer, "recovery_pct": r.gap_recovered_pct, "type": r.intervention})
for r in combined_recovery:
    data.append({"layer": r.description, "recovery_pct": r.gap_recovered_pct, "type": "combined"})
chart(data, "bar", x="layer", y="recovery_pct", hue="type", title="Intervention Recovery %")
```

### Chart 10: Transform Recovery (bar)
```python
# From coarse_analyzer transform_recovery
data = [{"config": tr.config, "recovery_pct": tr.recovery_pct, "transform": tr.transform}
        for tr in transform_recovery]
chart(data, "bar", x="config", y="recovery_pct", hue="transform", title="Transform Recovery %")
```

## Synthesis strategy

After rendering charts, synthesize all findings:

### 1. Accuracy overview
- Combine coarse_analyzer's config_results with transform variants
- Populate `configs` list

### 2. Layer findings
- Merge deep_dive_analyst's distribution_profiles + block_analyses
- For each worst layer: combine diagnosis from distribution + block analysis
- Include worst_block_idx, worst_channel_idx from block_analyses
- Include recovery_pct from intervention_explorer (match by layer name)

### 3. Format weaknesses
- Aggregate from deep_dive_analyst's format_weaknesses
- Add any new insights from intervention results

### 4. Recommendations
- Based on intervention_explorer's best_strategy
- Priority ordering:
  1. [HIGH] Mixed precision for layers with >5% gap recovery from bit boost
  2. [HIGH] Apply best transform (SmoothQuant or Hadamard)
  3. [MEDIUM] Combined strategy from intervention evaluation
  4. [LOW] Granularity or format changes for outlier-heavy layers

### 5. Conclusion
One sentence: "Target format {format} at {config} loses {X}% accuracy, primary bottleneck is {bottleneck}, best recovery is {strategy} at {Y}%"

### 6. charts_rendered
List the names of all charts successfully rendered (e.g., ["accuracy_overview", "degradation_decomposition", ...])

## Script structure

Write a single Python script that:
1. Reads the StudyReport from the output directory
2. Reads previous agent outputs from their structured JSON
3. Renders all 10 charts
4. Prints the synthesized report data as JSON

```bash
cat << 'SUMMARY_EOF' > /tmp/summary_charts.py
import sys, json, os

from src.report._study_report import StudyReport

try:
    from harness.tools.chart import render_chart
except ImportError:
    render_chart = None

def chart(data, chart_type, x, y, title, **kwargs):
    payload = {"chart_type": chart_type, "data": data, "x": x, "y": y, "title": title, **kwargs}
    if render_chart:
        render_chart(**payload)
    else:
        print(f"__HARNESS_CHART__: {json.dumps(payload)}")

report = StudyReport.from_file('<output_dir>')
# ... render all charts, then print summary ...

SUMMARY_EOF

python /tmp/summary_charts.py
```
