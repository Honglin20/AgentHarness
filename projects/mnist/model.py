"""Configurable MLP for MNIST-like (sklearn digits) classification.

NAS workflow will modify this file to explore different architectures
(layer count / hidden dim / activation / normalization).
"""
import torch
import torch.nn as nn


class ResidualBlock(nn.Module):
    """Wrap a block with a residual (skip) connection: output = block(x) + x."""

    def __init__(self, block: nn.Module, dim: int):
        super().__init__()
        self.block = block
        self.dim = dim

    def forward(self, x):
        return self.block(x) + x


class ConfigurableMLP(nn.Module):
    """Simple MLP with configurable depth / width / activation."""

    def __init__(
        self,
        in_dim: int = 64,
        num_classes: int = 10,
        hidden_dim: int = 64,
        num_layers: int = 2,
        activation: str = "gelu",
        use_batchnorm: bool = True,
    ):
        super().__init__()
        act_fn = {
            "relu": nn.ReLU,
            "tanh": nn.Tanh,
            "gelu": nn.GELU,
            "silu": nn.SiLU,
        }[activation]

        layers = []
        prev = in_dim
        for _ in range(num_layers):
            block = []
            block.append(nn.Linear(prev, hidden_dim))
            if use_batchnorm:
                block.append(nn.BatchNorm1d(hidden_dim))
            block.append(act_fn())
            block.append(nn.Dropout(p=0.2))
            # Wrap in residual connection when input dim matches output dim
            if prev == hidden_dim:
                layers.append(ResidualBlock(nn.Sequential(*block), hidden_dim))
            else:
                layers.extend(block)
            prev = hidden_dim
        layers.append(nn.Linear(prev, num_classes))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def dummy_inputs(batch_size: int = 1):
    """Construct dummy inputs for ONNX export / latency benchmarking.

    Returns a single tensor of shape (batch_size, 64).
    """
    return torch.randn(batch_size, 64)
