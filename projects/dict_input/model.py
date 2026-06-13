"""Dict-input model: forward(inputs: dict) — two-tower recommendation-style model.

NAS workflow explores tower depth / width / activation / fusion mode.
Synthetic user × item → 3-class engagement bucket classification.
"""
import torch
import torch.nn as nn


FUSION_MODES = ("concat", "sum", "mul", "hadamard_dot")


class DictInputMLP(nn.Module):
    """Takes a dict {"user": ..., "item": ...}, two-tower encoders, fuses, classifies."""

    def __init__(
        self,
        user_dim: int = 8,
        item_dim: int = 8,
        num_classes: int = 3,
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

        def make_tower(in_dim):
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

        self.user_tower = make_tower(user_dim)
        self.item_tower = make_tower(item_dim)

        if fusion == "concat":
            head_in = hidden_dim * 2
        elif fusion in ("sum", "mul"):
            head_in = hidden_dim
        else:  # hadamard_dot
            head_in = hidden_dim

        self.head = nn.Linear(head_in, num_classes)
        self.fusion = fusion

    def forward(self, inputs):
        if not isinstance(inputs, dict):
            raise TypeError(
                f"DictInputMLP.forward expects a dict, got {type(inputs).__name__}. "
                "Pass e.g. model({'user': u, 'item': i})."
            )
        u = self.user_tower(inputs["user"])
        i = self.item_tower(inputs["item"])
        if self.fusion == "concat":
            h = torch.cat([u, i], dim=-1)
        elif self.fusion == "sum":
            h = u + i
        elif self.fusion == "mul":
            h = u * i
        else:  # hadamard_dot — element-wise product (same as mul, but distinct name for NAS clarity)
            h = u * i
        return self.head(h)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def make_synthetic_batch(batch_size: int, user_dim: int = 8, item_dim: int = 8,
                         num_classes: int = 3, noise_scale: float = 0.3,
                         device: str = "cpu", _protos=None):
    """Generate one batch: dict of {'user', 'item'} tensors + labels.

    Each class has a fixed random prototype. user/item drawn from class prototype + Gaussian noise.
    Solvable by either tower alone (prototype matching); fusion helps.

    Args:
        noise_scale: stdev of noise added to prototypes. Lower = easier.
        _protos: optional dict {"user": (num_classes, user_dim), "item": (num_classes, item_dim)}
                 for deterministic prototypes across batches. Auto-generated if None.

    Returns (inputs_dict, y).
    """
    # Lazy-init prototypes (cached on function attribute so they stay fixed across calls).
    if _protos is not None:
        user_protos = _protos["user"].to(device)
        item_protos = _protos["item"].to(device)
    else:
        if not hasattr(make_synthetic_batch, "_cache"):
            torch.manual_seed(0)  # deterministic prototypes across the process
            make_synthetic_batch._cache = {
                "user": torch.randn(num_classes, user_dim),
                "item": torch.randn(num_classes, item_dim),
            }
            torch.manual_seed(torch.randint(0, 2**31, (1,)).item())  # restore random state
        user_protos = make_synthetic_batch._cache["user"].to(device)
        item_protos = make_synthetic_batch._cache["item"].to(device)

    y = torch.randint(0, num_classes, (batch_size,), device=device)
    user = user_protos[y] + torch.randn(batch_size, user_dim, device=device) * noise_scale
    item = item_protos[y] + torch.randn(batch_size, item_dim, device=device) * noise_scale
    return {"user": user, "item": item}, y
