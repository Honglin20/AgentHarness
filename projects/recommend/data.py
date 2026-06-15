"""Synthetic user-item interaction data for NCF training."""
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader


N_USERS = 100
N_ITEMS = 200
EMBED_DIM = 32


def _generate_interactions(n_samples, seed):
    """Generate (user_id, item_id, label) tuples.

    Label = 1 if user × item latent dot product > threshold else 0.
    """
    rng = np.random.default_rng(seed)
    user_latent = rng.standard_normal(size=(N_USERS, EMBED_DIM)).astype(np.float32)
    item_latent = rng.standard_normal(size=(N_ITEMS, EMBED_DIM)).astype(np.float32)
    user_ids = rng.integers(0, N_USERS, size=n_samples)
    item_ids = rng.integers(0, N_ITEMS, size=n_samples)
    scores = (user_latent[user_ids] * item_latent[item_ids]).sum(axis=1)
    # Binarize: top 50% scores → label 1, rest → 0
    threshold = np.median(scores)
    labels = (scores > threshold).astype(np.float32)
    return (
        torch.from_numpy(user_ids.astype(np.int64)),
        torch.from_numpy(item_ids.astype(np.int64)),
        torch.from_numpy(labels),
    )


class InteractionDataset(Dataset):
    def __init__(self, n_samples, seed):
        self.users, self.items, self.labels = _generate_interactions(n_samples, seed)

    def __len__(self):
        return len(self.users)

    def __getitem__(self, idx):
        return (self.users[idx], self.items[idx]), self.labels[idx]


def load_train_loader(batch_size=64):
    return DataLoader(InteractionDataset(2000, seed=42), batch_size=batch_size, shuffle=True)


def load_eval_loader(batch_size=64):
    return DataLoader(InteractionDataset(500, seed=43), batch_size=batch_size, shuffle=False)
