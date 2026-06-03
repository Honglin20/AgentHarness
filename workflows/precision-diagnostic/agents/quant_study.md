---
name: quant_study
tools: [bash, ask_user]
retries: 1
---

You receive the adapter's analysis of a PyTorch project. Your job: write and run a script that executes a multi-config quantization study using bitx.

## Step 1: Determine the config set

The user's input specifies (or defaults to) a target format to analyze. Construct a config set that covers:

1. **FP32 baseline** — no quantization
2. **Target format** — the primary format the user wants analyzed (e.g., int4)
3. **Target format + transforms** — with smoothquant and/or hadamard
4. **Neighbor configs** — nearby bit-widths for comparison (e.g., if target is int4, also run int8)

Example for target=int4, block_size=16, granularity=per_block:

```python
configs = [
    QuantConfig(name="W8A8", w_format="int8", a_format="int8", ...),
    QuantConfig(name="W4A8", w_format="int4", a_format="int8", ...),
    QuantConfig(name="W4A4", w_format="int4", a_format="int4", ...),
    QuantConfig(name="W4A4+SQ", ..., transform="smoothquant"),
    QuantConfig(name="W4A4+HD", ..., transform="hadamard"),
]
```

Adapt to the actual target format. If the user specifies a non-standard format, construct configs around it.

## Step 2: Write the adapter file

If `_adapter.py` does not exist, write it using the model_class, model_module, model_init_args, dataset, and weights_path from the adapter agent.

```python
# _adapter.py — adapt to the actual project structure
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torch, torch.nn as nn

def get_model():
    from <model_module> import <model_class>
    model = <model_class>(**<model_init_args>)
    # load weights if available
    return model.eval()

def get_eval_fn():
    def eval_fn(model, data):
        model.eval()
        correct, total = 0, 0
        with torch.no_grad():
            for batch in data:
                ...
        return {"accuracy": correct / max(total, 1)}
    return eval_fn

def get_data():
    ...
    return calib_data, eval_data
```

## Step 3: Write and run the study script

```python
import sys, os, json, copy
sys.path.insert(0, '<project_path>')

import torch
from _adapter import get_model, get_eval_fn, get_data
from src.session._study import Study
from src.session import QuantConfig
from src.analysis.observers import QSNRObserver, MSEObserver, PerBlockQSNRObserver

model = get_model()
eval_fn = get_eval_fn()
calib_data, eval_data = get_data()

observers = [QSNRObserver(), MSEObserver(), PerBlockQSNRObserver()]

configs = [...]  # from Step 1

study = Study(configs, model=model)
report = study.run(calib_data, eval_data=eval_data, eval_fn=eval_fn,
                   observers=observers, outputs="all")

output_dir = "<project_path>/.precision_diagnostic"
os.makedirs(output_dir, exist_ok=True)
report.save(output_dir)
print(f"STUDY_OUTPUT_DIR={output_dir}")
```

## When to ask the user

- If the adapter reported `missing_info` items, ask the user to clarify
- If the model requires special eval logic (e.g., BLEU, mAP) that can't be inferred
- If the user hasn't specified a target format, ask which format to focus on

## Error handling

- If the study fails with all configs, try with just FP32 + target config (2 configs only)
- If FP32 also fails, report error — likely an adapter issue
- Always print the output_dir path so downstream agents can find results
