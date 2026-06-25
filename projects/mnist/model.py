"""ConfigurableMLP for sklearn digits classification (8x8=64 features, 10 classes).

NAS baseline: simple 2-layer MLP with configurable hidden_dim / activation.
"""
import torch
import torch.nn as nn


class ConfigurableMLP(nn.Module):
    """Simple MLP configurable via kwargs.

    Architecture:
        Flatten -> Linear(in_dim, hidden_dim) -> <act>
                -> Linear(hidden_dim, hidden_dim//2) -> <act>
                -> Linear(hidden_dim//2, num_classes)
    """

    def __init__(self, in_dim: int = 64, num_classes: int = 10,
                 hidden_dim: int = 128, num_layers: int = 2,
                 activation: str = "relu", use_batchnorm: bool = False, **kwargs):
        super().__init__()
        act_map = {"relu": nn.ReLU, "gelu": nn.GELU, "tanh": nn.Tanh, "silu": nn.SiLU}
        Act = act_map.get(activation, nn.ReLU)

        layers = [nn.Flatten(), nn.Linear(in_dim, hidden_dim)]
        if use_batchnorm:
            layers.append(nn.BatchNorm1d(hidden_dim))
        layers.append(Act())

        cur = hidden_dim
        for _ in range(num_layers - 1):
            nxt = max(cur // 2, 32)
            layers.append(nn.Linear(cur, nxt))
            if use_batchnorm:
                layers.append(nn.BatchNorm1d(nxt))
            layers.append(Act())
            cur = nxt

        layers.append(nn.Linear(cur, num_classes))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def dummy_inputs(batch_size: int = 1):
    """Construct dummy inputs for ONNX export / latency benchmarking."""
    return torch.randn(batch_size, 64)
