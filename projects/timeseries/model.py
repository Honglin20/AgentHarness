"""LSTM-based multivariate time series forecaster."""
import torch
import torch.nn as nn

import config as C


class LSTMForecaster(nn.Module):
    """LSTM encoder + linear decoder. Predicts next-step feature vector."""

    def __init__(self, n_features=C.N_FEATURES, hidden_dim=C.HIDDEN_DIM, n_layers=C.N_LAYERS):
        super().__init__()
        self.n_features = n_features
        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_dim,
            num_layers=n_layers,
            batch_first=True,
        )
        self.fc = nn.Linear(hidden_dim, n_features)

    def forward(self, x):
        # x: (B, T=SEQ_LEN, F=n_features)
        out, _ = self.lstm(x)
        last = out[:, -1, :]  # (B, hidden)
        return self.fc(last)   # (B, F)

    def dummy_inputs(self):
        return torch.zeros(1, C.SEQ_LEN, self.n_features)
