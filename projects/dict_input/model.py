"""Dict-input model: forward(inputs: dict) — two-tower recommendation-style model.
STRUCTURAL VARIANT v1: 3 tower layers + residual connections + BatchNorm.

Changes from v0:
- Increased tower depth from 2 to 3 layers (num_layers=3 default)
- Added residual connections within each tower (skip connections)
- Changed default activation from relu to gelu for smoother gradients
- Kept BatchNorm enabled (use_batchnorm=True default)
"""
import torch
import torch.nn as nn


FUSION_MODES = ("concat", "sum", "mul", "hadamard_dot")


class ResidualBlock(nn.Module):
    """A Linear -> BN -> Activation -> Dropout block with residual skip connection.
    
    If input dim != hidden dim, we project the input with a learned linear.
    """
    def __init__(self, in_dim: int, hidden_dim: int, use_batchnorm: bool = True,
                 activation: str = "gelu", dropout: float = 0.2):
        super().__init__()
        act_fn = {
            "relu": nn.ReLU,
            "tanh": nn.Tanh,
            "gelu": nn.GELU,
            "silu": nn.SiLU,
        }[activation]
        
        layers = []
        layers.append(("linear", nn.Linear(in_dim, hidden_dim)))
        if use_batchnorm:
            layers.append(("bn", nn.BatchNorm1d(hidden_dim)))
        layers.append(("act", act_fn()))
        layers.append(("drop", nn.Dropout(p=dropout)))
        
        self.net = nn.Sequential()
        for name, mod in layers:
            self.net.add_module(name, mod)
        
        # Projection shortcut if dimensions differ
        if in_dim != hidden_dim:
            self.shortcut = nn.Linear(in_dim, hidden_dim)
        else:
            self.shortcut = nn.Identity()
    
    def forward(self, x):
        return self.net(x) + self.shortcut(x)


class DictInputMLP(nn.Module):
    """Takes a dict {"user": ..., "item": ...}, two-tower encoders, fuses, classifies.
    
    Structural variant v1: 3 layers per tower with residual connections and GELU.
    """
    def __init__(
        self,
        user_dim: int = 8,
        item_dim: int = 8,
        num_classes: int = 3,
        hidden_dim: int = 64,
        num_layers: int = 3,
        activation: str = "gelu",
        fusion: str = "concat",
        use_batchnorm: bool = True,
        dropout: float = 0.2,
    ):
        super().__init__()
        if fusion not in FUSION_MODES:
            raise ValueError(f"fusion must be one of {FUSION_MODES}, got {fusion!r}")

        def make_tower(in_dim):
            layers = nn.Sequential()
            prev = in_dim
            for i in range(num_layers):
                block = ResidualBlock(prev, hidden_dim, use_batchnorm, activation, dropout)
                layers.add_module(f"block_{i}", block)
                prev = hidden_dim
            return layers

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
        else:  # hadamard_dot
            h = u * i
        return self.head(h)


def count_parameters(model: nn.Module) -> int:
    return sum(p.numel() for p in model.parameters())


def dummy_inputs(batch_size: int = 1):
    """Construct dummy inputs for ONNX export / latency benchmarking."""
    return {
        "user": torch.randn(batch_size, 8),
        "item": torch.randn(batch_size, 8),
    }


def make_synthetic_batch(batch_size: int, user_dim: int = 8, item_dim: int = 8,
                         num_classes: int = 3, noise_scale: float = 0.3,
                         device: str = "cpu", _protos=None):
    """Generate one batch: dict of {'user', 'item'} tensors + labels."""
    if _protos is not None:
        user_protos = _protos["user"].to(device)
        item_protos = _protos["item"].to(device)
    else:
        if not hasattr(make_synthetic_batch, "_cache"):
            torch.manual_seed(0)
            make_synthetic_batch._cache = {
                "user": torch.randn(num_classes, user_dim),
                "item": torch.randn(num_classes, item_dim),
            }
            torch.manual_seed(torch.randint(0, 2**31, (1,)).item())
        user_protos = make_synthetic_batch._cache["user"].to(device)
        item_protos = make_synthetic_batch._cache["item"].to(device)

    y = torch.randint(0, num_classes, (batch_size,), device=device)
    user = user_protos[y] + torch.randn(batch_size, user_dim, device=device) * noise_scale
    item = item_protos[y] + torch.randn(batch_size, item_dim, device=device) * noise_scale
    return {"user": user, "item": item}, y
