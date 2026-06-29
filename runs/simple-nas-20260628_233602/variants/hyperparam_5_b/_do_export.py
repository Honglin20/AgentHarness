import sys, os, json, importlib.util
sys.path.insert(0, os.path.dirname(__file__))

import torch
import torch.nn as nn

ckpt_path = os.path.join(os.path.dirname(__file__), 'ckpt.pt')
model_path = os.path.join(os.path.dirname(__file__), 'model.py')

spec = importlib.util.spec_from_file_location('model', model_path)
model_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model_mod)

ckpt = torch.load(ckpt_path, map_location='cpu')
model = model_mod.DeepJSCC(**ckpt['config'])
model.load_state_dict(ckpt['model_state'])
model.eval()

dummy = torch.randn(1, 3, 32, 32)
out_path = os.path.join(os.path.dirname(__file__), 'model.onnx')

# Register a custom symbolic for square to use Mul(x, x) instead
from torch.onnx.symbolic_registry import register_op

def square_symbolic(g, self):
    return g.op('Mul', self, self)

try:
    register_op('square', square_symbolic, '', 11)
except:
    pass

torch.onnx.export(
    model, dummy, out_path,
    input_names=['input'], output_names=['output'],
    opset_version=11,
    dynamic_axes={'input': {0: 'batch'}, 'output': {0: 'batch'}}
)

params = sum(p.numel() for p in model.parameters())
meta = {'onnx_path': out_path, 'params': params, 'opset_version': 11}
print(json.dumps(meta))
