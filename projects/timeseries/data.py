"""Synthetic multivariate time series data generator.

Each feature = sine (per-feature freq) + slow trend + AWGN.
"""
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader

import config as C


def _generate_series(n_samples, seed):
    rng = np.random.default_rng(seed)
    t = np.arange(n_samples + C.SEQ_LEN)
    series = np.zeros((n_samples + C.SEQ_LEN, C.N_FEATURES), dtype=np.float32)
    for f in range(C.N_FEATURES):
        freq = C.SINE_FREQS[f % len(C.SINE_FREQS)]
        trend = 0.001 * t
        sine = np.sin(2 * np.pi * freq * t)
        noise = C.NOISE_STD * rng.standard_normal(size=t.shape)
        series[:, f] = sine + trend + noise
    return series


class TimeSeriesDataset(Dataset):
    """Sliding window over a multivariate series. Target = next-step series."""

    def __init__(self, n_samples, seed):
        series = _generate_series(n_samples, seed)
        # Build sliding windows
        X, Y = [], []
        for i in range(len(series) - C.SEQ_LEN):
            X.append(series[i:i + C.SEQ_LEN])
            Y.append(series[i + C.SEQ_LEN])
        self.X = torch.from_numpy(np.stack(X))
        self.Y = torch.from_numpy(np.stack(Y))

    def __len__(self):
        return len(self.X)

    def __getitem__(self, idx):
        return self.X[idx], self.Y[idx]


def load_train_data():
    return DataLoader(
        TimeSeriesDataset(C.N_TRAIN, seed=42),
        batch_size=C.BATCH_SIZE, shuffle=True,
    )


def load_eval_data():
    return DataLoader(
        TimeSeriesDataset(C.N_EVAL, seed=43),
        batch_size=C.BATCH_SIZE, shuffle=False,
    )
