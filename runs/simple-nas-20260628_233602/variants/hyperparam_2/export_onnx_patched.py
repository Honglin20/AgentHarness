#!/usr/bin/env python3
"""Register missing ops then run export_onnx main."""
import sys
import os

sys.path.insert(0, "/Users/mozzie/Desktop/Projects/AgentHarness/workflows/simple-nas/helpers")
sys.path.insert(0, "/Users/mozzie/Desktop/Projects/AgentHarness/projects/Deep-JSCC-PyTorch/runs/simple-nas-20260628_233602/variants/hyperparam_2")

import torch
from torch.onnx.symbolic_registry import register_op

def square_symbolic(g, self):
    return g.op('Mul', self, self)

# Register square for all supported opsets
for opset in [9, 10, 11, 12]:
    try:
        register_op('square', square_symbolic, '', opset)
    except Exception:
        pass

# Now call export_onnx main with args
sys.argv = [
    'export_onnx.py',
    '--checkpoint', "/Users/mozzie/Desktop/Projects/AgentHarness/projects/Deep-JSCC-PyTorch/runs/simple-nas-20260628_233602/variants/hyperparam_2/ckpt.pt",
    '--out', "/Users/mozzie/Desktop/Projects/AgentHarness/projects/Deep-JSCC-PyTorch/runs/simple-nas-20260628_233602/variants/hyperparam_2/model_new.onnx",
    '--model-dir', "/Users/mozzie/Desktop/Projects/AgentHarness/projects/Deep-JSCC-PyTorch/runs/simple-nas-20260628_233602/variants/hyperparam_2",
    '--opset', '11'
]

from export_onnx import main
main()
