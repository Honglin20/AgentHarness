"""Patch for the norm layer — replaces torch.sqrt(z*z) with torch.norm for ONNX compat."""
import sys
sys.path.insert(0, '/Users/mozzie/Desktop/Projects/AgentHarness/projects/Deep-JSCC-PyTorch/runs/simple-nas-20260628_233602/variants/structural_1')
from model import _Encoder
import torch

# Monkey-patch the norm layer to avoid 'square' op
def _norm_fixed(z_hat, P=1):
    if z_hat.dim() == 4:
        batch_size = z_hat.size()[0]
        k = torch.prod(torch.tensor(z_hat.size()[1:]))
    elif z_hat.dim() == 3:
        batch_size = 1
        k = torch.prod(torch.tensor(z_hat.size()))
    else:
        raise Exception("Unknown size of input")
    z_flat = z_hat.reshape(batch_size, -1).float()
    # Use torch.linalg.norm instead of sqrt(sum(x*x)) to avoid 'square' ONNX issue
    z_norm = torch.norm(z_flat, dim=1, keepdim=True)
    tensor = torch.sqrt(P * k.float()) * z_hat / z_norm.view(batch_size, 1, 1, 1)
    if batch_size == 1:
        return tensor.squeeze(0)
    return tensor

_Encoder._normlizationLayer = staticmethod(lambda P=1: (lambda z_hat: _norm_fixed(z_hat, P)))
_Encoder._normlizationLayer.__name__ = '_normlizationLayer'

print("Norm layer patched for ONNX export")
