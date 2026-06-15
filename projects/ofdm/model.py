"""OFDM signal detector — MLP for per-subcarrier QPSK classification."""
import torch
import torch.nn as nn


class OFDMDetector(nn.Module):
    """MLP that takes (B, K, 2) received signal and outputs (B, K, 4) QPSK logits.

    K = n_subcarriers, 2 = real/imag, 4 = QPSK classes.
    """

    def __init__(self, n_subcarriers=64, hidden_dim=128, n_layers=2, activation="relu"):
        super().__init__()
        self.n_subcarriers = n_subcarriers
        in_dim = n_subcarriers * 2
        out_dim = n_subcarriers * 4

        act_cls = {"relu": nn.ReLU, "gelu": nn.GELU, "tanh": nn.Tanh}.get(activation, nn.ReLU)
        layers = []
        last = in_dim
        for _ in range(n_layers):
            layers.append(nn.Linear(last, hidden_dim))
            layers.append(act_cls())
            last = hidden_dim
        layers.append(nn.Linear(last, out_dim))
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        # x: (B, K, 2) → (B, 2K)
        B = x.shape[0]
        x = x.reshape(B, -1)
        out = self.net(x)
        # (B, 4K) → (B, K, 4)
        return out.reshape(B, self.n_subcarriers, 4)

    def dummy_inputs(self):
        """Required for ONNX export / latency measurement."""
        return torch.zeros(1, self.n_subcarriers, 2)
