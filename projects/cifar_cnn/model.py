"""Small CNN for 3-channel image classification."""
import torch
import torch.nn as nn


N_CLASSES = 5


class SmallCNN(nn.Module):
    """2 conv blocks + FC head."""

    def __init__(self, n_channels=3, n_classes=N_CLASSES, hidden_dim=64, n_conv_blocks=2):
        super().__init__()
        layers = []
        in_ch = n_channels
        cur_size = 32
        for _ in range(n_conv_blocks):
            layers.append(nn.Conv2d(in_ch, hidden_dim, kernel_size=3, padding=1))
            layers.append(nn.ReLU())
            layers.append(nn.MaxPool2d(2))
            in_ch = hidden_dim
            cur_size = cur_size // 2
        self.features = nn.Sequential(*layers)
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Linear(in_ch * cur_size * cur_size, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, n_classes),
        )

    def forward(self, x):
        # x: (B, 3, 32, 32)
        f = self.features(x)
        return self.classifier(f)

    def dummy_inputs(self):
        return torch.zeros(1, 3, 32, 32)
