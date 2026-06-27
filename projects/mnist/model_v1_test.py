"""ConfigurableMLP for sklearn digits classification — structural variant v1.

Structural changes from v0 (baseline):
  1. CONSTANT-WIDTH hidden layers: all hidden dims = hidden_dim (no shrinking).
     Baseline was cur//2 per layer (64→32). Now all layers hold constant width,
     preserving representational capacity through the full depth.
  2. GELU activation: smoother gradients than ReLU, better for MLP training.
  3. BatchNorm: stabilizes training, enables better gradient flow.

Architecture (hidden_dim=128, num_layers=2):
    Flatten → Linear(64, 128) → BN → GELU → Linear(128, 128) → BN → GELU → Linear(128, 10)
"""
import torch
import torch.nn as nn


class ConfigurableMLP(nn.Module):
    """MLP with constant-width hidden layers (structural variant).

    Key structural difference from baseline v0:
    - Instead of shrinking width per layer (cur // 2), ALL hidden layers
      maintain hidden_dim width. This preserves representational capacity
      throughout the network.
    - Uses GELU activation for smoother gradients.
    - BatchNorm with affine=True for training stability.

    Args:
        in_dim: Input feature dimension (64 for sklearn digits).
        num_classes: Output classes (10 for digits).
        hidden_dim: Width of ALL hidden layers (constant).
        num_layers: Number of hidden layers.
        activation: Activation function name.
        use_batchnorm: Whether to add BatchNorm1d after each Linear.
    """

    def __init__(self, in_dim: int = 64, num_classes: int = 10,
                 hidden_dim: int = 128, num_layers: int = 2,
                 activation: str = "gelu", use_batchnorm: bool = True, **kwargs):
        super().__init__()
        act_map = {"relu": nn.ReLU, "gelu": nn.GELU, "tanh": nn.Tanh, "silu": nn.SiLU}
        Act = act_map.get(activation, nn.GELU)

        layers = [nn.Flatten(), nn.Linear(in_dim, hidden_dim)]
        if use_batchnorm:
            layers.append(nn.BatchNorm1d(hidden_dim))
        layers.append(Act())

        # STRUCTURAL CHANGE: Constant-width layers instead of shrinking.
        # Every hidden layer has width = hidden_dim (no bottleneck).
        for _ in range(num_layers - 1):
            layers.append(nn.Linear(hidden_dim, hidden_dim))
            if use_batchnorm:
                layers.append(nn.BatchNorm1d(hidden_dim))
            layers.append(Act())

        layers.append(nn.Linear(hidden_dim, num_classes))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def dummy_inputs(batch_size: int = 1):
    """Construct dummy inputs for ONNX export / latency benchmarking."""
    return torch.randn(batch_size, 64)
