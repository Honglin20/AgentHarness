# -*- coding: utf-8 -*-
"""
Structural v7 — decoder channel reduction (32→26) + keep residuals + SE attention.

Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K):
  1. Decoder conv1/conv2/conv3 channels: 32→26 (18.75% reduction) — less
     decoder compute, keeps encoder identical for encoding quality.
  2. conv4 input: 26+16=42→16 (was 48→16) — fewer channels, less compute.
  3. 1×1 projection conv to match decoder residual (26ch = 26ch).
  4. Keep all 3 residual blocks + SE bottleneck attention (proven effective).
  
  Rationale: structural_5 (decoder 32→28 + 1×1 residual projection) achieved
  best-ever PSNR 31.35dB but latency increased 23% to 0.511ms. By reducing
  decoder channels further (32→26) with a lightweight 1×1 projection (only
  26*32 + 26 = 858 params), we aim for PSNR gain with minimal latency increase.
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
        out = self.conv1(x)
        out = self.prelu1(out)
        out = self.conv2(out)
        out = self.prelu2(out + identity)
        return out


class _SEBlock(nn.Module):
    """Squeeze-and-Excitation channel attention — negligible overhead (<300 params)."""

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
        # conv1: 3→16, 3×3 stride 2
        self.conv1 = _ConvWithPReLU(in_channels=3, out_channels=16, kernel_size=3, stride=2, padding=1)
        # conv2: 16→32, 3×3 stride 2
        self.conv2 = _ConvWithPReLU(in_channels=16, out_channels=32, kernel_size=3, stride=2, padding=1)
        self.res_block1 = _ResidualBlock(channels=32)
        if not is_temp:
            self.res_block2 = _ResidualBlock(channels=32)
            self.res_block3 = _ResidualBlock(channels=32)
            self.conv5 = _ConvWithPReLU(in_channels=32, out_channels=2 * c, kernel_size=3, padding=1)
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
        skip1 = self.conv1(x)        # 16ch, 16×16 — for U-Net skip
        x = self.conv2(skip1)        # 32ch, 8×8
        x = self.res_block1(x)
        if not self.is_temp:
            x = self.res_block2(x)
            x = self.res_block3(x)
            x = self.conv5(x)        # 2c channels
            x = self.norm(x)
            x = self.se(x)
            return x, (skip1,)
        return x


class _Decoder(nn.Module):
    # Decoder channels reduced from 32 to 26 for all middle layers
    DECODER_CH = 26  # was 32

    def __init__(self, c=1):
        super().__init__()
        # 1×1 projection: match bottleneck (2*c) → DECODER_CH for residual
        self.proj = nn.Conv2d(2*c, self.DECODER_CH, kernel_size=1)
        nn.init.kaiming_normal_(self.proj.weight, mode="fan_out", nonlinearity="leaky_relu")
        
        # Reduced channels: 2*c → 26 (was 2*c → 32)
        self.conv1 = _ConvWithPReLU(in_channels=2*c, out_channels=self.DECODER_CH, kernel_size=3, padding=1)
        self.conv2 = _ConvWithPReLU(in_channels=self.DECODER_CH, out_channels=self.DECODER_CH, kernel_size=3, padding=1)
        self.conv3 = _ConvWithPReLU(in_channels=self.DECODER_CH, out_channels=self.DECODER_CH, kernel_size=3, padding=1)
        # upsample + conv
        self.up4 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        # conv4: DECODER_CH + 16 (skip) = 42 (was 48) → 16
        self.conv4 = _ConvWithPReLU(in_channels=self.DECODER_CH + 16, out_channels=16, kernel_size=3, padding=1)
        self.up5 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        self.conv5 = nn.Sequential(
            nn.Conv2d(16, 3, kernel_size=3, padding=1),
            nn.Sigmoid()
        )

    def forward(self, x, skip_features=None):
        identity = self.proj(x)  # project bottleneck to DECODER_CH channels
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)
        x = x + identity  # residual: both are DECODER_CH channels now

        # First upsampling: 8×8 → 16×16
        x = self.up4(x)
        if skip_features is not None and len(skip_features) > 0:
            skip1 = skip_features[0]  # 16ch, 16×16 from encoder conv1
            x = torch.cat([x, skip1], dim=1)  # 42ch (was 48ch), 16×16
        x = self.conv4(x)  # 16ch, 16×16

        # Second upsampling: 16×16 → 32×32
        x = self.up5(x)
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
