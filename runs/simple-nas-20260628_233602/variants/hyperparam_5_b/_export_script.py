
import sys, os, json, importlib.util
sys.path.insert(0, os.path.dirname(__file__))

import torch
import torch.nn as nn

# Load checkpoint
ckpt_path = os.path.join(os.path.dirname(__file__), 'ckpt.pt')
model_path = os.path.join(os.path.dirname(__file__), 'model.py')

# Load model
spec = importlib.util.spec_from_file_location('model', model_path)
model_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model_mod)

ckpt = torch.load(ckpt_path, map_location='cpu')
model = model_mod.DeepJSCC(**ckpt['config'])
model.load_state_dict(ckpt['model_state'])
model.eval()

# Dummy input
dummy = torch.randn(1, 3, 32, 32)
out_path = os.path.join(os.path.dirname(__file__), 'model.onnx')

torch.onnx.export(
    model, dummy, out_path,
    input_names=['input'], output_names=['output'],
    opset_version=17,
    dynamic_axes={'input': {0: 'batch'}, 'output': {0: 'batch'}}
)

# Params
params = sum(p.numel() for p in model.parameters())
meta = {'onnx_path': out_path, 'params': params, 'opset_version': 17}
print(json.dumps(meta))
