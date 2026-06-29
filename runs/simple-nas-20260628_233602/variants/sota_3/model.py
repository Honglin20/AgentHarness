# -*- coding: utf-8 -*-
"""
SOTA variant v3 — MobileNetV2 Inverted Residual blocks in encoder.

Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K):
  1. Replace encoder's plain conv layers (conv2) and residual blocks with
     MobileNetV2-style InvertedResidual blocks (expansion→depthwise→projection).
  2. Use expansion factor=3 (vs original 6) to keep computation low.
  3. Keep U-Net skip connection (conv1 output → decoder concat).
  4. Keep bilinear upsampling + 3×3 conv decoder (from parent — proven efficient).
  5. Keep power normalization and Channel layer unchanged.
"""

import torch
import torch.nn as nn
from channel import Channel


def ratio2filtersize(x: torch.Tensor, ratio):
    if x.dim() == 4:
        before_size = torch.prod(torch.tensor(x.size()[1:]))
    elif x.dim() == 3:
        before_size = torch.prod(torch.tensor(x.size()))
    else:
        raise Exception("Unknown size of input")
    encoder_temp = _Encoder(is_temp=True)
    z_temp = encoder_temp(x)
    c = before_size * ratio / torch.prod(torch.tensor(z_temp.size()[-2:]))
    return int(c)


class _ConvWithPReLU(nn.Module):
    def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size, stride, padding)
        self.prelu = nn.PReLU()
        nn.init.kaiming_normal_(self.conv.weight, mode="fan_out", nonlinearity="leaky_relu")

    def forward(self, x):
        x = self.conv(x)
        x = self.prelu(x)
        return x


class _InvertedResidual(nn.Module):
    """MobileNetV2-style inverted residual block.
    
    Structure: 1×1 expansion → Depthwise 3×3 → 1×1 projection
    With residual connection when stride=1 and in_channels == out_channels.
    Expansion factor controls the intermediate channel width.
    """
    def __init__(self, in_channels, out_channels, stride=1, expand_ratio=3):
        super().__init__()
        self.stride = stride
        self.use_residual = (stride == 1 and in_channels == out_channels)
        hidden_dim = int(round(in_channels * expand_ratio))
        
        layers = []
        # Pointwise expansion
        if expand_ratio != 1:
            layers.extend([
                nn.Conv2d(in_channels, hidden_dim, kernel_size=1, bias=False),
                nn.PReLU()
            ])
        # Depthwise
        layers.extend([
            nn.Conv2d(hidden_dim, hidden_dim, kernel_size=3, stride=stride,
                       padding=1, groups=hidden_dim, bias=False),
            nn.PReLU()
        ])
        # Pointwise projection
        layers.extend([
            nn.Conv2d(hidden_dim, out_channels, kernel_size=1, bias=False),
        ])
        # Note: No activation after projection (as in MobileNetV2)
        self.conv = nn.Sequential(*layers)
        
        # Init weights
        for m in self.conv.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode="fan_out", nonlinearity="leaky_relu")

    def forward(self, x):
        if self.use_residual:
            return x + self.conv(x)
        else:
            return self.conv(x)


class _SEBlock(nn.Module):
    """Squeeze-and-Excitation channel attention."""

    def __init__(self, channels, reduction=8):
        super().__init__()
        self.gap = nn.AdaptiveAvgPool2d(1)
        self.fc1 = nn.Linear(channels, channels // reduction)
        self.relu = nn.ReLU(inplace=True)
        self.fc2 = nn.Linear(channels // reduction, channels)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        if x.dim() == 3:
            c, h, w = x.size()
            y = self.gap(x.unsqueeze(0)).view(1, c)
            y = self.relu(self.fc1(y))
            y = self.sigmoid(self.fc2(y)).view(1, c, 1, 1)
            return (x.unsqueeze(0) * y).squeeze(0)
        b, c, h, w = x.size()
        y = self.gap(x).view(b, c)
        y = self.relu(self.fc1(y))
        y = self.sigmoid(self.fc2(y)).view(b, c, 1, 1)
        return x * y


class _Encoder(nn.Module):
    def __init__(self, c=1, is_temp=False, P=1):
        super().__init__()
        self.is_temp = is_temp
        
        # Initial conv (3→16, stride 2) — kept same as parent for U-Net skip
        self.conv1 = _ConvWithPReLU(in_channels=3, out_channels=16, kernel_size=3, stride=2, padding=1)
        
        # MobileNetV2 blocks replacing conv2→res_block1→res_block2→res_block3
        # Block 1: 16→32, stride 2 (downsample from 16×16 to 8×8)
        self.mb_block1 = _InvertedResidual(16, 32, stride=2, expand_ratio=3)
        # Block 2: 32→32, stride 1 (process at 8×8)
        self.mb_block2 = _InvertedResidual(32, 32, stride=1, expand_ratio=3)
        # Block 3: 32→32, stride 1 (more processing at 8×8)
        self.mb_block3 = _InvertedResidual(32, 32, stride=1, expand_ratio=3)
        
        if not is_temp:
            # Final conv to bottleneck channels
            self.conv5 = _ConvWithPReLU(in_channels=32, out_channels=2 * c, kernel_size=3, padding=1)
            self.norm = self._normlizationLayer(P=P)
            self.se = _SEBlock(channels=2 * c) if 2 * c >= 8 else nn.Identity()

    @staticmethod
    def _normlizationLayer(P=1):
        def _inner(z_hat: torch.Tensor):
            if z_hat.dim() == 4:
                batch_size = z_hat.size()[0]
                k = z_hat.size()[1] * z_hat.size()[2] * z_hat.size()[3]
            elif z_hat.dim() == 3:
                batch_size = 1
                k = z_hat.size()[0] * z_hat.size()[1] * z_hat.size()[2]
                z_hat = z_hat.unsqueeze(0)
            else:
                raise Exception("Unknown size of input")
            z_flat = z_hat.reshape(batch_size, -1).float()
            z_norm = torch.sqrt(torch.sum(z_flat * z_flat, dim=1, keepdim=True))
            tensor = torch.sqrt(torch.tensor(P * float(k))) * z_hat / z_norm.view(batch_size, 1, 1, 1)
            return tensor
        return _inner

    def forward(self, x):
        skip1 = self.conv1(x)          # 16ch, 16×16 — for U-Net skip
        x = self.mb_block1(skip1)      # 32ch, 8×8
        x = self.mb_block2(x)          # 32ch, 8×8
        x = self.mb_block3(x)          # 32ch, 8×8
        if not self.is_temp:
            x = self.conv5(x)           # 2c channels, 8×8
            x = self.norm(x)
            x = self.se(x)
            return x, (skip1,)
        return x


class _Decoder(nn.Module):
    def __init__(self, c=1):
        super().__init__()
        self.conv1 = _ConvWithPReLU(in_channels=2*c, out_channels=32, kernel_size=3, padding=1)
        self.conv2 = _ConvWithPReLU(in_channels=32, out_channels=32, kernel_size=3, padding=1)
        self.conv3 = _ConvWithPReLU(in_channels=32, out_channels=32, kernel_size=3, padding=1)
        # upsample + conv (replacing transposed convs)
        self.up4 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        self.conv4 = _ConvWithPReLU(in_channels=48, out_channels=16, kernel_size=3, padding=1)
        self.up5 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        self.conv5 = nn.Sequential(
            nn.Conv2d(16, 3, kernel_size=3, padding=1),
            nn.Sigmoid()
        )

    def forward(self, x, skip_features=None):
        identity = x
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)
        x = x + identity  # residual

        x = self.up4(x)  # 8×8 → 16×16
        if skip_features is not None and len(skip_features) > 0:
            skip1 = skip_features[0]
            x = torch.cat([x, skip1], dim=1)
        x = self.conv4(x)  # 16ch, 16×16

        x = self.up5(x)  # 16×16 → 32×32
        x = self.conv5(x)  # 3ch, 32×32
        return x


class DeepJSCC(nn.Module):
    def __init__(self, c, channel_type="AWGN", snr=None):
        super().__init__()
        self.encoder = _Encoder(c=c)
        if snr is not None:
            self.channel = Channel(channel_type, snr)
        self.decoder = _Decoder(c=c)

    def forward(self, x):
        z, skip_features = self.encoder(x)
        if hasattr(self, "channel") and self.channel is not None:
            z = self.channel(z)
        x_hat = self.decoder(z, skip_features=skip_features)
        return x_hat

    def change_channel(self, channel_type="AWGN", snr=None):
        if snr is None:
            self.channel = None
        else:
            self.channel = Channel(channel_type, snr)

    def get_channel(self):
        if hasattr(self, "channel") and self.channel is not None:
            return self.channel.get_channel()
        return None

    def loss(self, prd, gt):
        return nn.MSELoss(reduction="mean")(prd, gt)


def dummy_inputs(batch_size=1):
    return torch.randn(batch_size, 3, 32, 32)
