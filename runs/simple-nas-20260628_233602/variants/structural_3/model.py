# -*- coding: utf-8 -*-
"""
Structural variant v1.3 — ECA attention + compressed U-Net skip + decoder ECA.

Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K):
  1. Replace SEBlock (two FC layers) with ECABlock (1D conv, k=3 for 2c=32).
     ECA is computationally lighter (O(C) vs O(C²/reduction)) with comparable
     accuracy — fewer params, less latency.
  2. Compress U-Net skip connection via 1×1 conv (16→8 channels) before
     concatenation in decoder. conv4 input: 32 (upsampled) + 8 (compressed skip)
     = 40 channels instead of 48. Reduces decoder FLOPs with minimal quality loss.
  3. Add lightweight ECA in decoder after conv3 residual connection for better
     feature refinement during reconstruction.
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
    """Two 3x3 convs with identity skip — same channels in/out."""

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


class _ECABlock(nn.Module):
    """Efficient Channel Attention (ECA) — lightweight channel attention.

    Replaces the heavier SEBlock (two FC layers) with a 1D convolution
    that has adaptive kernel size k. Fewer parameters, comparable accuracy.
    """

    def __init__(self, channels, gamma=2, b=1):
        super().__init__()
        # Adaptive kernel size: k = |(log2(C) + b) / gamma|_odd
        k = int(abs((torch.log2(torch.tensor(channels, dtype=torch.float32)) + b) / gamma))
        k = k if k % 2 == 1 else k + 1  # ensure odd
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.conv = nn.Conv1d(1, 1, kernel_size=k, padding=k // 2, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        b, c, h, w = x.size()
        y = self.avg_pool(x).view(b, 1, c)
        y = self.sigmoid(self.conv(y))
        y = y.view(b, c, 1, 1)
        return x * y


class _Encoder(nn.Module):
    def __init__(self, c=1, is_temp=False, P=1):
        super().__init__()
        self.is_temp = is_temp
        self.conv1 = _ConvWithPReLU(in_channels=3, out_channels=16, kernel_size=3, stride=2, padding=1)
        self.conv2 = _ConvWithPReLU(in_channels=16, out_channels=32, kernel_size=3, stride=2, padding=1)
        self.res_block1 = _ResidualBlock(channels=32)
        if not is_temp:
            self.res_block2 = _ResidualBlock(channels=32)
            self.res_block3 = _ResidualBlock(channels=32)
            self.conv5 = _ConvWithPReLU(in_channels=32, out_channels=2 * c, kernel_size=3, padding=1)
            self.norm = self._normlizationLayer(P=P)
            # REPLACED: SEBlock -> ECABlock (lighter)
            self.eca = _ECABlock(channels=2 * c) if 2 * c >= 4 else nn.Identity()

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
            # F.normalize with p=2 computes x / ||x||_2
            z_normed = torch.nn.functional.normalize(z_flat, p=2, dim=1)
            scale = torch.sqrt(P * k.float())
            tensor = z_normed * scale
            return tensor.view(batch_size, z_hat.size(1), z_hat.size(2), z_hat.size(3))
        return _inner

    def forward(self, x):
        skip1 = self.conv1(x)
        x = self.conv2(skip1)
        x = self.res_block1(x)
        if not self.is_temp:
            x = self.res_block2(x)
            x = self.res_block3(x)
            x = self.conv5(x)
            x = self.norm(x)
            x = self.eca(x)
            return x, (skip1,)
        return x


class _Decoder(nn.Module):
    def __init__(self, c=1):
        super().__init__()
        self.conv1 = _ConvWithPReLU(in_channels=2*c, out_channels=32, kernel_size=3, padding=1)
        self.conv2 = _ConvWithPReLU(in_channels=32, out_channels=32, kernel_size=3, padding=1)
        self.conv3 = _ConvWithPReLU(in_channels=32, out_channels=32, kernel_size=3, padding=1)
        # NEW: ECA block after conv3 residual for decoder feature refinement
        self.decoder_eca = _ECABlock(channels=32)
        self.up4 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        # NEW: 1x1 conv to compress U-Net skip from 16->8 channels
        self.skip_compress = nn.Conv2d(16, 8, kernel_size=1, bias=False)
        # conv4 receives 32ch (upsampled) + 8ch (compressed skip) = 40ch (was 48)
        self.conv4 = _ConvWithPReLU(in_channels=40, out_channels=16, kernel_size=3, padding=1)
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
        x = x + identity
        x = self.decoder_eca(x)

        x = self.up4(x)
        if skip_features is not None and len(skip_features) > 0:
            skip1 = skip_features[0]
            skip1 = self.skip_compress(skip1)
            x = torch.cat([x, skip1], dim=1)
        x = self.conv4(x)

        x = self.up5(x)
        x = self.conv5(x)
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
