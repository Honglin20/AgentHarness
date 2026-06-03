---
name: block_analyst
tools: [bash]
retries: 1
---

You receive the layer_attribution's output identifying the worst layers. Your job: perform block-level and channel-level error analysis with visualizations.

## Step 1: Run block error analysis + render charts

```bash
cat << 'BLOCK_EOF' > /tmp/block_analysis.py
import sys, json, os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from src.report._study_report import StudyReport
from src.api.block_error_analysis import block_error_analysis
from src.viz.block_error_heatmap import (
    block_error_heatmap, channel_error_bar, multi_config_block_comparison,
)

report = StudyReport.from_file('<output_dir>')
worst_layers = <worst_layers_list>

output_dir = '<output_dir>'
charts_dir = os.path.join(output_dir, "charts")
os.makedirs(charts_dir, exist_ok=True)

analyses = []
for config_name, results in report._results.items():
    for r in results:
        for layer in worst_layers:
            if layer not in (r.observers_data or {}):
                continue

            # Weight block analysis
            try:
                blk_report = block_error_analysis(r, layer=layer, role="weight", top_k=5)
                weight_qsnr = {str(k): v for k, v in blk_report.per_unit_qsnr.items()}
                worst_blocks = [
                    {"block_idx": idx, "qsnr_db": qsnr, "stats": {}}
                    for idx, qsnr in blk_report.worst_units
                ]
            except Exception as e:
                weight_qsnr = None
                worst_blocks = []

            # Activation channel analysis
            try:
                ch_report = block_error_analysis(r, layer=layer, role="input", top_k=5)
                act_qsnr = {str(k): v for k, v in ch_report.per_unit_qsnr.items()}
                worst_chs = [
                    {"channel_idx": idx, "qsnr_db": qsnr, "stats": {}}
                    for idx, qsnr in ch_report.worst_units
                ]
            except Exception as e:
                act_qsnr = None
                worst_chs = []

            # Render heatmap
            heatmap_ok = False
            try:
                fig = block_error_heatmap(r, layer=layer, role="weight", top_k_blocks=5)
                fig.savefig(os.path.join(charts_dir, f"heatmap_{config_name}_{layer}.png"), dpi=100)
                plt.close(fig)
                heatmap_ok = True
            except Exception:
                pass

            # Render channel bar
            bar_ok = False
            try:
                fig = channel_error_bar(r, layer=layer, role="input", top_k=10)
                fig.savefig(os.path.join(charts_dir, f"channel_bar_{config_name}_{layer}.png"), dpi=100)
                plt.close(fig)
                bar_ok = True
            except Exception:
                pass

            # Render multi-config comparison
            comp_ok = False
            try:
                fig = multi_config_block_comparison(report, layer=layer, role="weight", top_k=10)
                fig.savefig(os.path.join(charts_dir, f"comparison_{layer}.png"), dpi=100)
                plt.close(fig)
                comp_ok = True
            except Exception:
                pass

            analyses.append({
                "layer": layer,
                "config": config_name,
                "weight_block_qsnr": weight_qsnr,
                "worst_weight_blocks": worst_blocks,
                "weight_error_pattern": "",
                "activation_channel_qsnr": act_qsnr,
                "worst_activation_channels": worst_chs,
                "activation_error_pattern": "",
                "heatmap_rendered": heatmap_ok,
                "bar_chart_rendered": bar_ok,
                "comparison_rendered": comp_ok,
                "finding": "",
            })

            # Only analyze the first config result per config_name to avoid duplicates
            break

result = {"layer_analyses": analyses, "summary": f"Analyzed {len(analyses)} layer-config combinations"}
print("BLOCK_RESULT=" + json.dumps(result, default=str))
BLOCK_EOF

python /tmp/block_analysis.py
```

## Step 2: Classify error patterns

For each layer analysis:
- **Weight error pattern**: If worst blocks' QSNR is <50% of median → "concentrated". If all similar → "uniform". If blocks at channel boundaries are worse → "channel-boundary".
- **Activation error pattern**: If 1-2 channels have much lower QSNR → "outlier_channel". If uniform → "uniform".
- **Finding**: Write a one-sentence key finding (e.g., "Block 47 has 2.1 dB QSNR — 5% of blocks contain 80% of error").

## Step 3: Emit charts via render_chart

If the harness render_chart tool is available, emit the heatmap and bar chart data:

```python
# In the script, after generating charts:
import json
data = [{"block_idx": str(k), "qsnr_db": v} for k, v in weight_qsnr.items()]
print(f"__HARNESS_CHART__: {json.dumps({'chart_type': 'bar', 'data': data, 'x': 'block_idx', 'y': 'qsnr_db', 'title': f'Block Error: {layer} ({config_name})'})}")
```

Report the full BlockAnalysis with all fields populated.
