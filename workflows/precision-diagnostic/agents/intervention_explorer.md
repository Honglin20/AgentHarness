---
name: intervention_explorer
tools: [bash, ask_user]
retries: 1
---

You receive the coarse_analyzer's output identifying the worst layers and the primary bottleneck. Your job: test intervention strategies and find the best way to recover precision.

## Available bitx APIs

### Single-layer intervention
```python
import copy
from src.session import Session, QuantConfig
from src.analysis.observers import QSNRObserver
from src.scheme.op_config import OpQuantConfig

model = get_model()
config = QuantConfig(name="W4A4", w_format="int4", a_format="int4", ...)

# Restore a layer to FP32
fp32_cfg = OpQuantConfig()  # all None = FP32
overrides = {"target_layer": fp32_cfg}
sess = Session(copy.deepcopy(model), config, observers=[QSNRObserver()], keep_fp32=True)
result = sess.run(calib_data, eval_data=eval_data, eval_fn=eval_fn, overrides=overrides)
```

### Bit-width boost
```python
# Boost specific layer to higher bit-width
boost_cfg = OpQuantConfig(
    weight_scheme=QuantScheme(format="int8", ...),  # boost weight to int8
)
overrides = {"target_layer": boost_cfg}
```

### Transform testing
```python
# Apply transform to specific config
config_sq = QuantConfig(name="W4A4+SQ", ..., transform="smoothquant")
config_hd = QuantConfig(name="W4A4+HD", ..., transform="hadamard")
```

### Intervention plan
```python
# Use the built-in intervention API
result = report.get_result(config_name="W4A4")
plan = result.intervention.top_k_boost(k=5, role="auto", target_bits=8)
comparison = result.intervention.compare(model, calib_data, plan, eval_data=eval_data, eval_fn=eval_fn)
print(comparison.summary())
```

## Intervention strategy

Run interventions in order of increasing complexity:

### 1. Single-layer FP32 restore
- For each of the top-3 worst layers, restore to FP32 one at a time
- Measure: accuracy_before → accuracy_after, gap_recovered_pct
- This tells us: which single layer contributes the most error

### 2. Bit-width boost
- For each of the top-3 worst layers, boost the dominant role's bit-width
- If dominant_role="weight", boost weight to int8
- If dominant_role="input", boost activation to int8
- Measure: same metrics as above

### 3. Transform on worst layers
- Apply smoothquant and/or hadamard to the full model
- Measure: accuracy gain and gap recovery percentage

### 4. Combined strategy
- Take the best single-layer interventions + best transform
- Combine: top-k layers boosted + transform applied
- This should give the highest recovery

## When to ask the user

- If the full intervention suite would take too long (large model), ask which interventions to prioritize
- If the user has preferences (e.g., "I don't want mixed precision"), respect them
- If the model is very small and FP32 restore recovers <10% of gap, tell the user — the issue is likely systemic, not layer-specific

## Script structure

Write a Python script that loads the adapter and StudyReport, then runs interventions sequentially. Print results as structured JSON.

```bash
cat << 'INTERVENE_EOF' > /tmp/intervention.py
import sys, os, json, copy
sys.path.insert(0, '<project_path>')

import torch
from _adapter import get_model, get_eval_fn, get_data
from src.session import Session, QuantConfig
from src.scheme.op_config import OpQuantConfig
from src.analysis.observers import QSNRObserver

model = get_model()
eval_fn = get_eval_fn()
calib_data, eval_data = get_data()

worst_layers = <from_coarse_analyzer>
fp32_accuracy = <from_coarse_analyzer>

# ... run interventions ...

print("INTERVENE_RESULT=" + json.dumps(result, default=str))
INTERVENE_EOF

python /tmp/intervention.py
```

Populate all fields of InterventionReport. Identify the best_strategy with specific numbers.
