"""Synthetic OFDM data generator.

Simulates QPSK symbol transmission over flat-fading channel + AWGN noise.
No external dataset needed — generates on the fly.
"""
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader


QPSK_CONSTELLATION = np.array([1+1j, 1-1j, -1+1j, -1-1j]) / np.sqrt(2)


def generate_ofdm_symbols(n_samples=1000, n_subcarriers=64, snr_db=20.0, seed=42):
    """Generate (received_signal, transmitted_symbol_indices) pairs.

    Returns:
        signals: torch.FloatTensor of shape (n_samples, n_subcarriers, 2) — real + imag
        symbols: torch.LongTensor of shape (n_samples, n_subcarriers) — QPSK class indices [0..3]
    """
    rng = np.random.default_rng(seed)
    symbol_indices = rng.integers(0, 4, size=(n_samples, n_subcarriers))
    symbols = QPSK_CONSTELLATION[symbol_indices]
    # No channel fading — task is pure QPSK demapping under AWGN (sanity-check level)
    received = symbols.copy()
    # AWGN noise (snr_db is signal-to-noise ratio; signal power = 1 for QPSK)
    snr_linear = 10 ** (snr_db / 10)
    noise_power = 1.0 / snr_linear
    noise_std = np.sqrt(noise_power / 2)
    noise = noise_std * (rng.standard_normal(size=received.shape)
                         + 1j * rng.standard_normal(size=received.shape))
    received = received + noise
    # complex -> 2 real channels
    received_real = np.stack([received.real, received.imag], axis=-1)  # (N, K, 2)
    return (
        torch.from_numpy(received_real).float(),
        torch.from_numpy(symbol_indices).long(),
    )


class OFDMDataset(Dataset):
    def __init__(self, n_samples=1000, n_subcarriers=64, snr_db=20.0, seed=42):
        self.signals, self.symbols = generate_ofdm_symbols(
            n_samples, n_subcarriers, snr_db, seed
        )

    def __len__(self):
        return len(self.signals)

    def __getitem__(self, idx):
        return self.signals[idx], self.symbols[idx]


def load_data(batch_size=32, n_subcarriers=64, snr_db=20.0,
              n_train=1000, n_eval=200):
    """Return (train_loader, eval_loader)."""
    train_ds = OFDMDataset(n_train, n_subcarriers, snr_db, seed=42)
    eval_ds = OFDMDataset(n_eval, n_subcarriers, snr_db, seed=43)
    return (
        DataLoader(train_ds, batch_size=batch_size, shuffle=True),
        DataLoader(eval_ds, batch_size=batch_size, shuffle=False),
    )
