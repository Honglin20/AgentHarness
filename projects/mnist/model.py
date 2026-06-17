"""MLP for MNIST digit classification with GELU activations.

NAS Strategy: Replace all ReLU activations with GELU to improve gradient
smoothness under MX quantization.
Parent: Flatten -> Linear(784,640) -> ReLU -> Linear(640,192) -> ReLU -> Linear(192,10)
GELU:   Flatten -> Linear(784,640) -> GELU -> Linear(640,192) -> GELU -> Linear(192,64) -> GELU -> Linear(64,10)

Hypothesis: GELU's smooth gradient profile reduces quantization noise amplification.
"""
import torch
import torch.nn as nn


class ConfigurableMLP(nn.Module):
    """MLP with GELU activations for improved gradient smoothness.

    Architecture (GELU activations):
        Flatten -> Linear(784,640) -> GELU -> Linear(640,192) -> GELU -> Linear(192,64) -> GELU -> Linear(64,10)
    """

    def __init__(self, **kwargs):
        """Ignore kwargs for backward compatibility; always build GELU architecture."""
        super().__init__()
        self.net = nn.Sequential(
            nn.Flatten(),
            nn.Linear(784, 640),
            nn.GELU(),
            nn.Linear(640, 192),
            nn.GELU(),
            nn.Linear(192, 64),
            nn.GELU(),
            nn.Linear(64, 10),
        )

    def forward(self, x):
        return self.net(x)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def dummy_inputs(batch_size: int = 1):
    """Construct dummy inputs for ONNX export / latency benchmarking.

    Returns a single tensor of shape (batch_size, 784).
    """
    return torch.randn(batch_size, 784)
