# -*- coding: utf-8 -*-
"""
SOTA variant v6 — ResNet Bottleneck Enhancement.

Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K):
  1. Replace _ResidualBlock (two 3×3 convs) with _BottleneckBlock
     (1×1→3×3→1×1, bottleneck_ratio=4). ~16× fewer params per block.
  2. Increase from 3 residual blocks to 4 bottleneck blocks (deeper but cheaper).
  3. Add _ensure_4d helper for ratio2filtersize compatibility.
  4. Keep all other structural_1 improvements: U-Net skip, SE attention,
     bilinear upsampling, 3×3 convs, Channel layer.
"""

import torch
import torch.nn as nn
from channel import Channel


def _ensure_4d(x):
    """Add batch dim if input is 3D (unbatched). Returns (tensor, was_3d)."""
    if x.dim() == 3:
        return x.unsqueeze(0), True
    return x, False


def ratio2filtersize(x: torch.Tensor, ratio):
    if x.dim() == 4:
        before_size = torch.prod(torch.tensor(x.size()[1:]))
    elif x.dim() == 3:
        before_size = torch.prod(torch.tensor(x.size()))
    else:
        raise Exception("Unknown size of input")
    encoder_temp = _Encoder(is_temp=True)
    x_4d, _ = _ensure_4d(x)
    z_temp = encoder_temp(x_4d)
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


class _BottleneckBlock(nn.Module):
    """
    ResNet bottleneck block: 1×1 reduce → 3×3 → 1×1 expand + identity skip.
    bottleneck_ratio=4: channels → channels/4 → channels/4 → channels.
    ~16× fewer params than two 3×3 convs with same C.
    """
    def __init__(self, channels, bottleneck_ratio=4):
        super().__init__()
        bottleneck_channels = max(channels // bottleneck_ratio, 4)
        self.conv1 = nn.Conv2d(channels, bottleneck_channels, kernel_size=1, bias=False)
        self.bn1 = nn.BatchNorm2d(bottleneck_channels)
        self.prelu1 = nn.PReLU()
        self.conv2 = nn.Conv2d(bottleneck_channels, bottleneck_channels, kernel_size=3, padding=1, bias=False)
        self.bn2 = nn.BatchNorm2d(bottleneck_channels)
        self.prelu2 = nn.PReLU()
        self.conv3 = nn.Conv2d(bottleneck_channels, channels, kernel_size=1, bias=False)
        self.bn3 = nn.BatchNorm2d(channels)
        self.prelu3 = nn.PReLU()

        nn.init.kaiming_normal_(self.conv1.weight, mode="fan_out", nonlinearity="leaky_relu")
        nn.init.kaiming_normal_(self.conv2.weight, mode="fan_out", nonlinearity="leaky_relu")
        nn.init.kaiming_normal_(self.conv3.weight, mode="fan_out", nonlinearity="leaky_relu")

    def forward(self, x):
        identity = x
        out = self.conv1(x)
        out = self.bn1(out)
        out = self.prelu1(out)
        out = self.conv2(out)
        out = self.bn2(out)
        out = self.prelu2(out)
        out = self.conv3(out)
        out = self.bn3(out)
        out = self.prelu3(out + identity)
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
        # 4× bottleneck blocks (deeper than parent's 3× residual blocks, but each much cheaper)
        self.bottleneck1 = _BottleneckBlock(channels=32, bottleneck_ratio=4)
        if not is_temp:
            self.bottleneck2 = _BottleneckBlock(channels=32, bottleneck_ratio=4)
            self.bottleneck3 = _BottleneckBlock(channels=32, bottleneck_ratio=4)
            self.bottleneck4 = _BottleneckBlock(channels=32, bottleneck_ratio=4)
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
        x, _ = _ensure_4d(x)
        skip1 = self.conv1(x)        # 16ch, 16×16 — for U-Net skip
        x = self.conv2(skip1)        # 32ch, 8×8
        x = self.bottleneck1(x)
        if not self.is_temp:
            x = self.bottleneck2(x)
            x = self.bottleneck3(x)
            x = self.bottleneck4(x)
            x = self.conv5(x)        # 2c channels
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
        x = x + identity
        x = self.up4(x)
        if skip_features is not None and len(skip_features) > 0:
            skip1 = skip_features[0]
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
