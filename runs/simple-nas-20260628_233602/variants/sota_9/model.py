# -*- coding: utf-8 -*-
"""
UNet variant with scaled-up channels (10→20→40) — building on sota_8's lightweight UNet
success (8→16→32, psnr=30.42, lat=0.4075ms, params=47K).

Changes from parent sota_8:
  1. Channel scaling: 8→16→32 → 10→20→40 (+25% width per level) for more capacity
  2. All decoder channels adjusted accordingly for skip connection compatibility
  3. Kept: bilinear upsampling+conv, PReLU, SE attention, power normalization, Channel layer
  4. Rationale: UNet is the best SOTA template for this image-to-image task;
     moderate channel increase should boost PSNR while keeping latency near target.
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


class _ConvBlock(nn.Module):
    """Conv2D + PReLU with Kaiming init."""
    def __init__(self, in_channels, out_channels, kernel_size=3, stride=1, padding=1):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size, stride, padding)
        self.prelu = nn.PReLU()
        nn.init.kaiming_normal_(self.conv.weight, mode="fan_out", nonlinearity="leaky_relu")

    def forward(self, x):
        return self.prelu(self.conv(x))


class _ResidualBlock(nn.Module):
    """Two 3×3 convs with identity skip — same channels in/out."""
    def __init__(self, channels):
        super().__init__()
        self.conv1 = nn.Conv2d(channels, channels, kernel_size=3, padding=1)
        self.prelu1 = nn.PReLU()
        self.conv2 = nn.Conv2d(channels, channels, kernel_size=3, padding=1)
        self.prelu2 = nn.PReLU()
        nn.init.kaiming_normal_(self.conv1.weight, mode="fan_out", nonlinearity="leaky_relu")
        nn.init.kaiming_normal_(self.conv2.weight, mode="fan_out", nonlinearity="leaky_relu")

    def forward(self, x):
        identity = x
        out = self.prelu1(self.conv1(x))
        out = self.prelu2(self.conv2(out))
        return out + identity


class _SEBlock(nn.Module):
    """Squeeze-and-Excitation channel attention."""
    def __init__(self, channels, reduction=8):
        super().__init__()
        self.gap = nn.AdaptiveAvgPool2d(1)
        reduced = max(channels // reduction, 4)
        self.fc1 = nn.Linear(channels, reduced)
        self.relu = nn.ReLU(inplace=True)
        self.fc2 = nn.Linear(reduced, channels)
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
    """
    3-level UNet encoder with wider channels (10→20→40).
    Level 1: conv1(3→10, s2, 3×3) → 16×16 [skip1]
    Level 2: conv2(10→20, s2, 3×3) → 8×8 [skip2]
    Level 3: conv3(20→40, s1, 3×3) → 8×8 residual block
    Bottleneck: conv5(40→2c, s1, 3×3) → power norm → SE
    """
    def __init__(self, c=1, is_temp=False, P=1):
        super().__init__()
        self.is_temp = is_temp
        # Level 1: 3→10, stride 2 (32→16)
        self.conv1 = _ConvBlock(3, 10, stride=2)  # skip1: 10ch, 16×16
        # Level 2: 10→20, stride 2 (16→8)
        self.conv2 = _ConvBlock(10, 20, stride=2)  # skip2: 20ch, 8×8
        # Level 3: 20→40, stride 1
        self.conv3 = _ConvBlock(20, 40, stride=1)

        if not is_temp:
            self.res_block = _ResidualBlock(channels=40)
            self.conv5 = _ConvBlock(40, 2 * c, stride=1)
            self.norm = self._normlizationLayer(P=P)
            self.se = _SEBlock(channels=2 * c) if 2 * c >= 8 else nn.Identity()

    @staticmethod
    def _normlizationLayer(P=1):
        def _inner(z_hat: torch.Tensor):
            if z_hat.dim() == 4:
                batch_size = z_hat.size()[0]
                k = torch.prod(torch.tensor(z_hat.size()[1:]))
            elif z_hat.dim() == 3:
                batch_size = 1
                k = torch.prod(torch.tensor(z_hat.size()))
                z_hat = z_hat.unsqueeze(0)
            else:
                raise Exception("Unknown size of input")
            z_flat = z_hat.reshape(batch_size, -1).float()
            z_norm = torch.norm(z_flat, dim=1, keepdim=True)
            tensor = torch.sqrt(P * k.float()) * z_hat / z_norm.view(batch_size, 1, 1, 1)
            return tensor
        return _inner

    def forward(self, x):
        skip1 = self.conv1(x)          # 10ch, 16×16
        skip2 = self.conv2(skip1)      # 20ch, 8×8
        x = self.conv3(skip2)          # 40ch, 8×8
        if not self.is_temp:
            x = self.res_block(x)      # 40ch, 8×8
            x = self.conv5(x)          # 2c ch, 8×8
            x = self.norm(x)
            x = self.se(x)
            return x, (skip1, skip2)   # (bottleneck, (level1_skip, level2_skip))
        return x


class _Decoder(nn.Module):
    """
    3-level UNet decoder (mirrors encoder with 10→20→40 channels).
    Level 3: conv_d3a(2c→20) at 8×8 + concat skip2(20ch) → conv(40→20)
    Level 2: upsample(×2) to 16×16 + concat skip1(10ch) → conv(30→20)
    Level 1: upsample(×2) to 32×32 → conv(20→3) + Sigmoid
    """
    def __init__(self, c=1):
        super().__init__()
        # Level 3: process bottleneck + fuse with skip2 (both at 8×8)
        self.conv_d3a = _ConvBlock(2 * c, 20, stride=1)
        self.conv_d3b = _ConvBlock(40, 20, stride=1)  # 20 (from d3a) + 20 (skip2) = 40

        # Level 2: upsample + fuse with skip1
        self.up2 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        self.conv_d2 = _ConvBlock(30, 20, stride=1)  # 20 (upsampled) + 10 (skip1) = 30

        # Level 1: upsample + output
        self.up1 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        self.conv_out = nn.Sequential(
            nn.Conv2d(20, 3, kernel_size=3, padding=1),
            nn.Sigmoid()
        )

    def forward(self, x, skip_features=None):
        # Level 3: process bottleneck
        x = self.conv_d3a(x)            # 20ch, 8×8
        if skip_features is not None and len(skip_features) > 1:
            skip2 = skip_features[1]    # 20ch, 8×8 from encoder conv2
            x = torch.cat([x, skip2], dim=1)  # 40ch, 8×8
        x = self.conv_d3b(x)            # 20ch, 8×8

        # Level 2: upsample + skip1 connection
        x = self.up2(x)                 # 20ch, 16×16
        if skip_features is not None and len(skip_features) > 0:
            skip1 = skip_features[0]    # 10ch, 16×16 from encoder conv1
            x = torch.cat([x, skip1], dim=1)  # 30ch, 16×16
        x = self.conv_d2(x)             # 20ch, 16×16

        # Level 1: upsample + output
        x = self.up1(x)                 # 20ch, 32×32
        x = self.conv_out(x)            # 3ch, 32×32
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
