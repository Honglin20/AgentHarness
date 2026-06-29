# -*- coding: utf-8 -*-
"""
Structural variant structural_2 — Depthwise separable convs + wider channels + ECA attention.

Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K):
  1. DSConv2d: all 3×3 convs replaced with depthwise separable (depthwise 3×3 +
     pointwise 1×1 + PReLU each) — saves ~7× params and ~8× FLOPs per conv layer.
  2. Wider channels: conv1 3→20 (was 3→16), conv2 20→40 (was 16→32),
     res_blocks 40ch (was 32ch) — +25% channel capacity where it matters most.
  3. ECA (Efficient Channel Attention) replaces SE in bottleneck — lighter
     (~10 params vs ~200), no FC layers, uses cheap 1D conv (kernel=3).
  4. ECA added after decoder conv3 for decoder-side channel recalibration.
  5. Keep: U-Net skip connections, 3× res_blocks, bilinear upsample+conv decoder.

Rationale:
  - Baseline analysis identifies bottleneck capacity as primary constraint.
    DSConv frees massive compute budget → widen channels + add attention.
  - ECA is O(params) = O(k×C) where k=3 (1D conv kernel), vs SE which is
    O(C²/r). Much lighter at 40ch (120 vs 200 params).
  - Wider encoder front-end (20→40ch) captures more spatial detail before
    the aggressive 2× stride pooling.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
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


def dummy_inputs(batch_size=1):
    """Return dummy input for ONNX export: [B, 3, 32, 32] image tensor."""
    return torch.randn(batch_size, 3, 32, 32)


class _DSConv2d(nn.Module):
    """Depthwise Separable 2D Convolution.

    Depthwise 3×3 (per-channel) → PReLU → Pointwise 1×1 (channel mixing) → PReLU.
    ~7× fewer params than regular 3×3 conv: (9*C + C*C_out) vs (9*C*C_out).

    Handles both 4D (batched) and 3D (unbatched) inputs for ratio2filtersize.
    """

    def __init__(self, in_channels, out_channels, stride=1, padding=1):
        super().__init__()
        self.depthwise = nn.Conv2d(in_channels, in_channels, kernel_size=3,
                                   stride=stride, padding=padding,
                                   groups=in_channels, bias=False)
        self.prelu_dw = nn.PReLU(in_channels)
        self.pointwise = nn.Conv2d(in_channels, out_channels, kernel_size=1,
                                   stride=1, padding=0, bias=False)
        self.prelu_pw = nn.PReLU(out_channels)
        nn.init.kaiming_normal_(self.depthwise.weight, mode="fan_out", nonlinearity="leaky_relu")
        nn.init.kaiming_normal_(self.pointwise.weight, mode="fan_out", nonlinearity="leaky_relu")

    def forward(self, x):
        was_3d = x.dim() == 3
        if was_3d:
            x = x.unsqueeze(0)  # add batch dim
        x = self.depthwise(x)
        x = self.prelu_dw(x)
        x = self.pointwise(x)
        x = self.prelu_pw(x)
        if was_3d:
            x = x.squeeze(0)  # remove batch dim
        return x


class _DSResidualBlock(nn.Module):
    """Residual block with two depthwise separable 3×3 convs + identity skip.
    Same channel count in/out.
    """

    def __init__(self, channels):
        super().__init__()
        self.dsconv1 = _DSConv2d(channels, channels, stride=1, padding=1)
        self.dsconv2 = _DSConv2d(channels, channels, stride=1, padding=1)

    def forward(self, x):
        identity = x
        out = self.dsconv1(x)
        out = self.dsconv2(out)
        out = out + identity
        return out


class _ECABlock(nn.Module):
    """Efficient Channel Attention — very lightweight.

    Uses 1D convolution of kernel size k (adapted from channel count) after
    GAP, followed by sigmoid. ~10 params vs ~200 for SE at 40ch.
    """

    def __init__(self, channels, gamma=2, b=1):
        super().__init__()
        # Kernel size adapted to channel count: k = |log2(C)/gamma + b/gamma|_odd
        k = int(abs((torch.log2(torch.tensor(channels, dtype=torch.float)) / gamma + b / gamma)))
        k = k if k % 2 == 1 else k + 1  # ensure odd
        k = max(3, min(k, channels))    # clamp: at least 3, at most channels
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.conv = nn.Conv1d(1, 1, kernel_size=k, padding=k // 2, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        b, c, h, w = x.size()
        y = self.avg_pool(x).view(b, 1, c)  # B, 1, C
        y = self.conv(y)                     # B, 1, C
        y = self.sigmoid(y).view(b, c, 1, 1)  # B, C, 1, 1
        return x * y


class _Encoder(nn.Module):
    def __init__(self, c=1, is_temp=False, P=1):
        super().__init__()
        self.is_temp = is_temp
        # conv1: 3→20, DSConv 3×3 stride 2 — wider front-end
        self.conv1 = _DSConv2d(in_channels=3, out_channels=20, stride=2, padding=1)
        # conv2: 20→40, DSConv 3×3 stride 2 — wider mid-features
        self.conv2 = _DSConv2d(in_channels=20, out_channels=40, stride=2, padding=1)
        self.res_block1 = _DSResidualBlock(channels=40)
        if not is_temp:
            self.res_block2 = _DSResidualBlock(channels=40)
            self.res_block3 = _DSResidualBlock(channels=40)
            # conv5: 40→2c, DSConv (bottleneck projection)
            self.conv5 = _DSConv2d(in_channels=40, out_channels=2 * c, stride=1, padding=1)
            self.norm = self._normlizationLayer(P=P)
            # ECA replaces SE — much lighter, comparable effect
            self.eca = _ECABlock(channels=2 * c) if 2 * c >= 8 else nn.Identity()

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
            # Manual L2 norm (avoid torch.norm which triggers ONNX 'square' issue)
            z_norm = torch.sqrt(torch.sum(z_flat * z_flat, dim=1, keepdim=True))
            tensor = torch.sqrt(P * k.float()) * z_hat / z_norm.view(batch_size, 1, 1, 1)
            return tensor
        return _inner

    def forward(self, x):
        skip1 = self.conv1(x)         # 20ch, 16×16 — U-Net skip
        x = self.conv2(skip1)         # 40ch, 8×8
        x = self.res_block1(x)
        if not self.is_temp:
            x = self.res_block2(x)
            x = self.res_block3(x)    # extra depth
            x = self.conv5(x)         # 2c channels (bottleneck)
            x = self.norm(x)
            x = self.eca(x)           # ECA channel attention
            return x, (skip1,)
        return x


class _Decoder(nn.Module):
    def __init__(self, c=1):
        super().__init__()
        # DSConv decoder blocks — all depthwise separable
        self.conv1 = _DSConv2d(in_channels=2*c, out_channels=40, stride=1, padding=1)
        self.conv2 = _DSConv2d(in_channels=40, out_channels=40, stride=1, padding=1)
        self.conv3 = _DSConv2d(in_channels=40, out_channels=40, stride=1, padding=1)
        # ECA after conv3 — lightweight decoder-side channel attention
        self.eca = _ECABlock(channels=40)
        # Upsample (bilinear) + conv — replaces tconv
        self.up4 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        # conv4: 40ch (up) + 20ch (skip) = 60ch → 20ch
        self.conv4 = _DSConv2d(in_channels=60, out_channels=20, stride=1, padding=1)
        self.up5 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        # Final output: 20→3, regular conv (no PReLU, just Sigmoid)
        self.conv5 = nn.Sequential(
            nn.Conv2d(20, 3, kernel_size=3, padding=1),
            nn.Sigmoid()
        )

    def forward(self, x, skip_features=None):
        x = self.conv1(x)
        x = self.conv2(x)
        x = self.conv3(x)
        x = self.eca(x)          # decoder-side attention
        # NOTE: residual removed — channel dim changed (2c→40) vs identity (2c)

        # First upsampling: 8×8 → 16×16
        x = self.up4(x)           # 40ch, 16×16
        if skip_features is not None and len(skip_features) > 0:
            skip1 = skip_features[0]  # 20ch, 16×16 from encoder conv1
            x = torch.cat([x, skip1], dim=1)  # 60ch, 16×16
        x = self.conv4(x)          # 20ch, 16×16

        # Second upsampling: 16×16 → 32×32
        x = self.up5(x)
        x = self.conv5(x)          # 3ch, 32×32
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
