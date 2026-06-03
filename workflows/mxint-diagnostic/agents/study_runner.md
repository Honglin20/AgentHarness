---
name: study_runner
tools: [bash]
retries: 1
---

You receive the adapter's analysis of a PyTorch project. Your job: write and run a script that executes a multi-config MXInt quantization study using bitx.

## Step 1: Write the adapter file

If `_adapter.py` does not already exist at the path from the adapter agent, write it. Use the model_class, model_module, model_init_args, dataset, and weights_path from the adapter's output.

```python
# _adapter.py
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torch, torch.nn as nn

def get_model():
    from <model_module> import <model_class>
    model = <model_class>(**<model_init_args>)
    # load weights if available
    ...
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

## Step 2: Write and run the study script

Write a Python script that runs 8 quantization configs with observers:

```bash
cat << 'STUDY_EOF' > /tmp/run_study.py
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

configs = []
for w, a in [(8,8), (4,8), (4,4)]:
    configs.append(QuantConfig(
        name=f"W{w}A{a}",
        w_format=f"int{w}", a_format=f"int{a}",
        w_granularity="per_block", a_granularity="per_block",
        w_block_size=16, a_block_size=16,
    ))
    configs.append(QuantConfig(
        name=f"W{w}A{a}+SQ",
        w_format=f"int{w}", a_format=f"int{a}",
        w_granularity="per_block", a_granularity="per_block",
        w_block_size=16, a_block_size=16,
        transform="smoothquant",
    ))
configs.append(QuantConfig(
    name="W8A8+HD", w_format="int8", a_format="int8",
    w_granularity="per_block", a_granularity="per_block",
    w_block_size=16, a_block_size=16,
    transform="hadamard",
))
configs.append(QuantConfig(
    name="W4A4+HD", w_format="int4", a_format="int4",
    w_granularity="per_block", a_granularity="per_block",
    w_block_size=16, a_block_size=16,
    transform="hadamard",
))

observers = [QSNRObserver(), MSEObserver(), PerBlockQSNRObserver()]

study = Study(configs, model=model)
report = study.run(calib_data, eval_data=eval_data, eval_fn=eval_fn, observers=observers, outputs="all")

output_dir = "<project_path>/.mxint_diagnostic"
report.save(output_dir)
print(f"STUDY_OUTPUT_DIR={output_dir}")

# Print accuracy summary for LLM parsing
for r in report._results.values():
    for sr in r:
        acc = sr.accuracy.get("accuracy") if sr.accuracy else None
        print(f"CONFIG {sr.name}: accuracy={acc}")
STUDY_EOF

python /tmp/run_study.py
```

## Important

- Use the actual project path from the working directory
- If the study fails, report the error and try with fewer configs (W8A8, W4A4 only)
- Print the output_dir path so downstream agents can find the results
