"""Synthetic image data generator (3-channel 32x32, 5 classes)."""
import numpy as np
import torch
from torch.utils.data import Dataset, DataLoader


N_CLASSES = 5
IMG_SIZE = 32
N_CHANNELS = 3


def _generate_images(n_samples, seed):
    """Generate (images, labels).

    Each class has a different mean color + texture pattern.
    """
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, N_CLASSES, size=n_samples)
    # Per-class mean color (deterministic)
    class_colors = np.array([
        [1.0, 0.2, 0.2],  # red
        [0.2, 1.0, 0.2],  # green
        [0.2, 0.2, 1.0],  # blue
        [1.0, 1.0, 0.2],  # yellow
        [1.0, 0.2, 1.0],  # magenta
    ], dtype=np.float32)
    images = np.zeros((n_samples, N_CHANNELS, IMG_SIZE, IMG_SIZE), dtype=np.float32)
    for i, label in enumerate(labels):
        base_color = class_colors[label]
        # Add per-pixel Gaussian noise (signal) + class bias
        noise = 0.3 * rng.standard_normal(size=(N_CHANNELS, IMG_SIZE, IMG_SIZE)).astype(np.float32)
        images[i] = base_color.reshape(N_CHANNELS, 1, 1) + noise
    return torch.from_numpy(images), torch.from_numpy(labels.astype(np.int64))


class ImageDataset(Dataset):
    def __init__(self, n_samples, seed):
        self.images, self.labels = _generate_images(n_samples, seed)

    def __len__(self):
        return len(self.images)

    def __getitem__(self, idx):
        return self.images[idx], self.labels[idx]


def load_train_loader(batch_size=64):
    return DataLoader(ImageDataset(800, seed=42), batch_size=batch_size, shuffle=True)


def load_eval_loader(batch_size=64):
    return DataLoader(ImageDataset(200, seed=43), batch_size=batch_size, shuffle=False)
