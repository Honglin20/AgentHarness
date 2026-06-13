"""Multi-input model: forward(x1, x2) — two branches + fusion.

NAS workflow explores branch depth / width / activation / fusion mode.
Trained on sklearn digits split into two halves (32 + 32 features).
"""
import torch
import torch.nn as nn


FUSION_MODES = ("concat", "sum", "mul")


class MultiInputMLP(nn.Module):
    """Takes two tensors, processes each in its own branch, fuses, classifies."""

    def __init__(
        self,
        in_dim_a: int = 32,
        in_dim_b: int = 32,
        num_classes: int = 10,
        hidden_dim: int = 64,
        num_layers: int = 2,
        activation: str = "relu",
        fusion: str = "concat",
        use_batchnorm: bool = True,
        dropout: float = 0.2,
    ):
        super().__init__()
        if fusion not in FUSION_MODES:
            raise ValueError(f"fusion must be one of {FUSION_MODES}, got {fusion!r}")

        act_fn = {
            "relu": nn.ReLU,
            "tanh": nn.Tanh,
            "gelu": nn.GELU,
            "silu": nn.SiLU,
        }[activation]

        def make_branch(in_dim):
            layers = []
            prev = in_dim
            for _ in range(num_layers):
                layers.append(nn.Linear(prev, hidden_dim))
                if use_batchnorm:
                    layers.append(nn.BatchNorm1d(hidden_dim))
                layers.append(act_fn())
                layers.append(nn.Dropout(p=dropout))
                prev = hidden_dim
            return nn.Sequential(*layers)

        self.branch_a = make_branch(in_dim_a)
        self.branch_b = make_branch(in_dim_b)

        if fusion == "concat":
            fused_dim = hidden_dim * 2
        else:
            if hidden_dim * 2 != hidden_dim:
                # sum/mul require equal dims; since both branches emit hidden_dim, fine.
                pass
            fused_dim = hidden_dim

        self.head = nn.Linear(fused_dim, num_classes)
        self.fusion = fusion

    def forward(self, x_a, x_b):
        h_a = self.branch_a(x_a)
        h_b = self.branch_b(x_b)
        if self.fusion == "concat":
            h = torch.cat([h_a, h_b], dim=-1)
        elif self.fusion == "sum":
            h = h_a + h_b
        else:
            h = h_a * h_b
        return self.head(h)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())
