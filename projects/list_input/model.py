"""List-input model: forward(x_list) — list of N tensors, fused after shared encoder.

NAS workflow explores encoder depth / width / aggregation mode.
Synthetic 3-channel time series classification.
"""
import torch
import torch.nn as nn


AGG_MODES = ("mean", "max", "sum", "concat")


class ListInputMLP(nn.Module):
    """Takes a Python list of N tensors (each shape (B, in_dim)), shares one encoder
    across all elements, aggregates, classifies."""

    def __init__(
        self,
        num_inputs: int = 3,
        in_dim: int = 16,
        num_classes: int = 3,
        hidden_dim: int = 64,
        num_layers: int = 2,
        activation: str = "relu",
        aggregation: str = "mean",
        use_batchnorm: bool = True,
        dropout: float = 0.2,
    ):
        super().__init__()
        if aggregation not in AGG_MODES:
            raise ValueError(f"aggregation must be one of {AGG_MODES}, got {aggregation!r}")

        act_fn = {
            "relu": nn.ReLU,
            "tanh": nn.Tanh,
            "gelu": nn.GELU,
            "silu": nn.SiLU,
        }[activation]

        layers = []
        prev = in_dim
        for _ in range(num_layers):
            layers.append(nn.Linear(prev, hidden_dim))
            if use_batchnorm:
                layers.append(nn.BatchNorm1d(hidden_dim))
            layers.append(act_fn())
            layers.append(nn.Dropout(p=dropout))
            prev = hidden_dim
        self.encoder = nn.Sequential(*layers)

        head_in = hidden_dim * num_inputs if aggregation == "concat" else hidden_dim
        self.head = nn.Linear(head_in, num_classes)
        self.aggregation = aggregation

    def forward(self, x_list):
        # x_list: List[Tensor] each (B, in_dim)
        # Encode each, then aggregate.
        encoded = [self.encoder(x) for x in x_list]
        stacked = torch.stack(encoded, dim=1)  # (B, N, hidden)
        if self.aggregation == "mean":
            agg = stacked.mean(dim=1)
        elif self.aggregation == "max":
            agg = stacked.max(dim=1).values
        elif self.aggregation == "sum":
            agg = stacked.sum(dim=1)
        else:
            agg = stacked.flatten(1)  # concat
        return self.head(agg)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def make_synthetic_batch(batch_size: int, num_inputs: int = 3, in_dim: int = 16,
                         signal_scale: float = 3.0, device: str = "cpu"):
    """Generate one batch: list of N tensors + labels.

    Label = which input carries the signal (0..N-1).
    Returns (x_list: List[Tensor], y: Tensor).
    """
    x_list = [torch.randn(batch_size, in_dim, device=device) for _ in range(num_inputs)]
    y = torch.randint(0, num_inputs, (batch_size,), device=device)
    # Inject signal into the chosen input.
    for b in range(batch_size):
        x_list[y[b]][b] += signal_scale
    return x_list, y
