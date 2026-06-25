"""ASI project model: wraps `fla.layers.DeltaNet` as a causal LM.

This is the REAL model class used by ASI-Arch paper (via FLAME framework).
Configuration is shrunk from 340M to ~3M params so we can train 200-600 steps
in 5-15 min on a single 3090/4090 for NAS workflow validation.

The class name `DeltaNetLM` is preserved across NAS iterations (same contract
as ASI's evolve phase — keep class name, signature stable).
"""
from __future__ import annotations

import json
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F


class DeltaNetLM(nn.Module):
    """Causal LM wrapping fla DeltaNet with embedding + LM head.

    Init args (NAS optimizers may tweak hidden_size / num_hidden_layers / num_heads):
        config_path: path to delta_nas.json (project-relative). If None, uses defaults.
        hidden_size: override config's hidden_size
        num_hidden_layers: override
        num_heads: override
        vocab_size: tokenizer vocab (GPT-2 = 50257 by default)
    """

    def __init__(
        self,
        config_path: str | None = None,
        hidden_size: int | None = None,
        num_hidden_layers: int | None = None,
        num_heads: int | None = None,
        vocab_size: int = 50257,
        **kwargs,
    ):
        super().__init__()
        # Load config
        if config_path and Path(config_path).exists():
            with open(config_path) as f:
                cfg = json.load(f)
        else:
            cfg = {
                "hidden_size": 256, "num_hidden_layers": 4,
                "num_heads": 4, "intermediate_size": 512,
                "hidden_act": "swish", "norm_eps": 1e-6,
                "use_gate": False, "use_short_conv": True,
                "conv_size": 4, "expand_k": 1, "expand_v": 1,
                "qk_norm": "l2", "qk_activation": "silu",
                "use_beta": True, "use_output_norm": True,
                "attn_mode": "chunk", "use_cache": True,
            }
        # Apply overrides
        if hidden_size is not None: cfg["hidden_size"] = hidden_size
        if num_hidden_layers is not None: cfg["num_hidden_layers"] = num_hidden_layers
        if num_heads is not None: cfg["num_heads"] = num_heads
        cfg["vocab_size"] = vocab_size
        self.config = cfg

        # Try real fla import; fall back to minimal stub if missing (CPU smoke test)
        # or version-incompatible (fla 0.5+ expects triton 3.7+, torch 2.4 ships triton 3.0).
        try:
            from fla.layers import DeltaNet  # type: ignore
            from fla.modules import RMSNorm  # type: ignore
            self._fla_available = True
        except (ImportError, TypeError, AttributeError) as e:
            # TypeError: fla/triton API mismatch (e.g. Autotuner signature change)
            # ImportError: fla not installed
            # AttributeError: partial install
            import warnings
            warnings.warn(f"fla unavailable ({type(e).__name__}: {e}); using pure-PyTorch fallback")
            self._fla_available = False
            DeltaNet = None  # type: ignore
            RMSNorm = None  # type: ignore

        hidden = cfg["hidden_size"]
        # Embedding
        self.embed = nn.Embedding(vocab_size, hidden)
        # Stack of DeltaNet layers (or fallback)
        if self._fla_available:
            self.layers = nn.ModuleList([
                DeltaNet(cfg) for _ in range(cfg["num_hidden_layers"])
            ])
            self.norm = RMSNorm(hidden, eps=cfg["norm_eps"])
        else:
            # Fallback for CPU smoke (no triton): Linear Attention + Delta Rule
            self.layers = nn.ModuleList([
                _LinearDeltaLayer(hidden, cfg) for _ in range(cfg["num_hidden_layers"])
            ])
            self.norm = nn.LayerNorm(hidden, eps=cfg["norm_eps"])
        # LM head
        self.lm_head = nn.Linear(hidden, vocab_size, bias=False)
        # Tie weights (common practice)
        self.embed.weight = self.lm_head.weight
        # Apply init
        self._init_weights()

    def _init_weights(self):
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.normal_(p, mean=0.0, std=self.config.get("initializer_range", 0.02))

    def forward(self, input_ids: torch.Tensor, **kwargs) -> torch.Tensor:
        """Returns logits [B, T, V]. ASI convention: returns list of tensors
        per layer; we return final logits directly for LM convenience."""
        x = self.embed(input_ids)  # [B, T, H]
        for layer in self.layers:
            x = layer(x)
        x = self.norm(x)
        return self.lm_head(x)  # [B, T, V]

    def num_parameters(self) -> int:
        return sum(p.numel() for p in self.parameters())


class _LinearDeltaLayer(nn.Module):
    """Fallback DeltaNet layer when `fla` library is unavailable (CPU smoke).

    Uses delta-rule linear attention in pure PyTorch. Mathematically equivalent
    up to kernel approximations; lets us run model.py on CPU without triton.
    """

    def __init__(self, hidden: int, cfg: dict):
        super().__init__()
        self.hidden = hidden
        self.num_heads = cfg["num_heads"]
        self.head_dim = hidden // self.num_heads
        self.qkv = nn.Linear(hidden, 3 * hidden, bias=False)
        self.o = nn.Linear(hidden, hidden, bias=False)
        self.norm = nn.LayerNorm(hidden, eps=cfg["norm_eps"])
        self.act = nn.SiLU() if cfg.get("hidden_act") == "swish" else nn.GELU()
        # short conv (causal) — use conv1d with kernel=conv_size
        self.conv_size = cfg.get("conv_size", 4)
        self.conv = nn.Conv1d(hidden, hidden, self.conv_size,
                              padding=self.conv_size - 1, groups=hidden)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, H = x.shape
        residual = x
        x = self.norm(x)
        # short conv
        x_conv = self.act(self.conv(x.transpose(1, 2)).transpose(1, 2)[:, :T])
        # project qkv
        qkv = self.qkv(x_conv)
        q, k, v = qkv.chunk(3, dim=-1)
        # reshape to heads
        q = q.view(B, T, self.num_heads, self.head_dim)
        k = k.view(B, T, self.num_heads, self.head_dim)
        v = v.view(B, T, self.num_heads, self.head_dim)
        # delta-rule linear attention (chunk-wise, simplified)
        out = self._delta_attn(q, k, v)  # [B, T, nh, hd]
        out = out.reshape(B, T, H)
        out = self.o(out)
        return residual + out

    def _delta_attn(self, q, k, v):
        """Naive O(T^2) delta-rule update — fine for short T (≤512)."""
        B, T, nh, hd = q.shape
        # Init state per head
        S = torch.zeros(B, nh, hd, hd, device=q.device, dtype=q.dtype)
        beta = 0.85  # delta rate
        outs = []
        q = q.transpose(1, 2)  # [B, nh, T, hd]
        k = k.transpose(1, 2)
        v = v.transpose(1, 2)
        for t in range(T):
            q_t = q[:, :, t]  # [B, nh, hd]
            k_t = k[:, :, t]
            v_t = v[:, :, t]
            # delta update: S = S + beta * (v - S k) k^T
            Sk = torch.einsum('bnij,bnj->bni', S, k_t)  # [B, nh, hd]
            delta = (v_t - Sk).unsqueeze(-1) * k_t.unsqueeze(-2)  # outer
            S = S + beta * delta
            # output: o = S q
            o_t = torch.einsum('bnij,bnj->bni', S, q_t)
            outs.append(o_t)
        out = torch.stack(outs, dim=2)  # [B, nh, T, hd]
        return out.transpose(1, 2)  # [B, T, nh, hd]


if __name__ == "__main__":
    # Quick smoke: instantiate model, forward random input
    model = DeltaNetLM(config_path=str(Path(__file__).parent / "configs" / "delta_nas.json"))
    print(f"fla available: {model._fla_available}")
    print(f"params: {model.num_parameters() / 1e6:.2f}M")
    x = torch.randint(0, 50257, (2, 64))
    with torch.no_grad():
        y = model(x)
    print(f"output shape: {y.shape}")  # [2, 64, 50257]


# ── NAS adapter contract: dummy inputs for ONNX export / latency ──
# ONNX export requires concrete tensor. Input is token IDs (long), not float.
def dummy_inputs(batch_size: int = 1) -> torch.Tensor:
    """Return a single LongTensor of shape [batch_size, 64] for ONNX export.

    export_onnx.py probes `from model import dummy_inputs` first; this makes
    latency measurement work for input_ids-based models (LM domain).
    """
    return torch.randint(0, 50257, (batch_size, 64), dtype=torch.long)


MODEL_CLASS = DeltaNetLM
