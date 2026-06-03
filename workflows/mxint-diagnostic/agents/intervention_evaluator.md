---
name: intervention_evaluator
tools: [bash]
retries: 1
---

You receive the layer_attribution's output identifying the worst layers. Your job: evaluate precision recovery strategies for those layers.

## Step 1: Test single-layer interventions

```bash
cat << 'INTERV_EOF' > /tmp/intervention.py
import sys, json, copy

import torch
from _adapter import get_model, get_eval_fn, get_data
from src.session import Session, QuantConfig
from src.analysis.observers import QSNRObserver

model_orig = get_model()
eval_fn = get_eval_fn()
calib_data, eval_data = get_data()

worst_layers = <worst_layers_list>

# Baseline W4A4 accuracy
config_w4a4 = QuantConfig(
    name="W4A4", w_format="int4", a_format="int4",
    w_granularity="per_block", a_granularity="per_block",
    w_block_size=16, a_block_size=16,
)
base_session = Session(copy.deepcopy(model_orig), config_w4a4, observers=[QSNRObserver()])
base_result = base_session.run(calib_data, eval_data=eval_data, eval_fn=eval_fn)
base_acc = base_result.accuracy.get("accuracy", 0) if base_result.accuracy else 0
print(f"BASE_W4A4_ACCURACY={base_acc}")

# FP32 accuracy (use W8A8 as proxy)
config_w8a8 = QuantConfig(
    name="W8A8", w_format="int8", a_format="int8",
    w_granularity="per_block", a_granularity="per_block",
    w_block_size=16, a_block_size=16,
)
w8a8_session = Session(copy.deepcopy(model_orig), config_w8a8, observers=[QSNRObserver()])
w8a8_result = w8a8_session.run(calib_data, eval_data=eval_data, eval_fn=eval_fn)
fp32_acc = w8a8_result.accuracy.get("accuracy", 0) if w8a8_result.accuracy else 0
total_gap = fp32_acc - base_acc
print(f"W8A8_ACCURACY={fp32_acc}")
print(f"TOTAL_GAP={total_gap}")

# Test single-layer FP32 restore
recovery_results = []
for layer in worst_layers[:5]:
    try:
        overrides = {layer: None}  # None = skip quantization for this layer
        sess = Session(copy.deepcopy(model_orig), config_w4a4, observers=[QSNRObserver()])
        result = sess.run(calib_data, eval_data=eval_data, eval_fn=eval_fn, overrides=overrides)
        acc = result.accuracy.get("accuracy", 0) if result.accuracy else 0
        gap_pct = ((acc - base_acc) / total_gap * 100) if total_gap > 0 else 0
        recovery_results.append({
            "layer": layer,
            "intervention": "fp32_restore",
            "accuracy_before": base_acc,
            "accuracy_after": acc,
            "gap_recovered_pct": gap_pct,
            "dominant_role": "unknown",
        })
        print(f"FP32_RESTORE {layer}: {base_acc:.4f} -> {acc:.4f} (recovered {gap_pct:.1f}%)")
    except Exception as e:
        print(f"FP32_RESTORE {layer}: FAILED - {e}")

# Test single-layer bit boost (int4→int8 for weight)
for layer in worst_layers[:5]:
    try:
        from src.scheme.op_config import OpQuantConfig
        override_cfg = OpQuantConfig(
            weight_scheme=None,  # FP32 weight
        )
        overrides = {layer: override_cfg}
        sess = Session(copy.deepcopy(model_orig), config_w4a4, observers=[QSNRObserver()])
        result = sess.run(calib_data, eval_data=eval_data, eval_fn=eval_fn, overrides=overrides)
        acc = result.accuracy.get("accuracy", 0) if result.accuracy else 0
        gap_pct = ((acc - base_acc) / total_gap * 100) if total_gap > 0 else 0
        recovery_results.append({
            "layer": layer,
            "intervention": "int4_to_int8",
            "accuracy_before": base_acc,
            "accuracy_after": acc,
            "gap_recovered_pct": gap_pct,
            "dominant_role": "weight",
        })
    except Exception as e:
        pass

result = {
    "single_layer_recovery": [r for r in recovery_results if r["intervention"] == "fp32_restore"],
    "bit_boost_recovery": [r for r in recovery_results if r["intervention"] == "int4_to_int8"],
    "transform_recovery": [],
    "combined_recovery": [],
    "best_strategy": "",
    "summary": f"Tested {len(recovery_results)} interventions on {len(worst_layers[:5])} layers",
}
print("INTERV_RESULT=" + json.dumps(result, default=str))
INTERV_EOF

python /tmp/intervention.py
```

## Step 2: Analyze results

- Which single-layer FP32 restore recovers the most gap?
- Which bit boost is most effective?
- Is the recovery concentrated in 1-2 layers or spread across many?
- Determine the best combined strategy (e.g., "top-3 layers int8 + smoothquant")

Report the full InterventionEvaluation with all fields populated.
