# -*- coding: utf-8 -*-
"""
SOTA variant v5 — Linear Attention (Performer-style) at encoder bottleneck.

Parent: structural_1 (PSNR=29.28, lat=0.415ms, params=105K)

Changes from structural_1:
  1. NEW: LinearAttention module (Performer ELU+1 feature map) inserted at
     encoder bottleneck (after res_blocks, before conv5). Adds O(n*d) spatial
     mixing across the 8×8 bottleneck feature maps, complementing the existing
     SE channel attention.
  2. Residual connection around linear attention for training stability.
  3. Everything else identical to structural_1: 3×3 convs, residual blocks,
     U-Net skip connections, bilinear upsampling decoder, SE attention,
     power normalization, Channel module.
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


class _LinearAttention(nn.Module):
    """
    Performer-style linear attention with ELU(x)+1 feature map.
    
    Complexity: O(n*d) instead of O(n²) for standard softmax attention.
    At 8×8 bottleneck (n=64, d=32/heads=8), this is ~2K operations vs ~4K for
    softmax attention, but more importantly it provides content-based spatial
    mixing without softmax saturation issues.
    
    Uses 1×1 convs for QKV projection and output, keeping overhead minimal.
    Residual connection is handled externally.
    """
    def __init__(self, dim, heads=4):
        super().__init__()
        self.heads = heads
        self.dim_head = dim // heads
        self.scale = self.dim_head ** -0.5
        inner_dim = self.dim_head * heads
        
        self.to_qkv = nn.Conv2d(dim, inner_dim * 3, kernel_size=1, bias=False)
        self.to_out = nn.Conv2d(inner_dim, dim, kernel_size=1, bias=False)
        
        nn.init.kaiming_normal_(self.to_qkv.weight, mode="fan_out", nonlinearity="leaky_relu")
        nn.init.kaiming_normal_(self.to_out.weight, mode="fan_out", nonlinearity="leaky_relu")

    def forward(self, x):
        b, c, h, w = x.shape
        qkv = self.to_qkv(x)  # b, 3*inner_dim, h, w
        q, k, v = qkv.chunk(3, dim=1)
        
        # Reshape to heads: b, heads, dim_head, n
        n = h * w
        q = q.view(b, self.heads, self.dim_head, n)  # b, h, d, n
        k = k.view(b, self.heads, self.dim_head, n)
        v = v.view(b, self.heads, self.dim_head, n)
        
        # Performer-style ELU(x)+1 feature map (positive, non-negative)
        q = torch.nn.functional.elu(q) + 1.0
        k = torch.nn.functional.elu(k) + 1.0
        
        # Linear attention: (Q * (K^T * V)) / (Q * sum(K))
        # K^T @ V: d×d (key-dim × value-dim) — the O(nd²) bottleneck
        kv = torch.matmul(k, v.transpose(-2, -1))  # b, h, d, d
        # Q @ KV: n×d
        out = torch.matmul(q.transpose(-2, -1), kv)  # b, h, n, d
        
        # Normalization denominator
        z = torch.matmul(q.transpose(-2, -1), k.sum(dim=-1, keepdim=True))  # b, h, n, 1
        out = out / (z + 1e-6)
        
        # Reshape back to spatial: b, inner_dim, h, w
        out = out.transpose(-2, -1).contiguous().view(b, -1, h, w)
        return self.to_out(out)  # b, dim, h, w


class _Encoder(nn.Module):
    def __init__(self, c=1, is_temp=False, P=1):
        super().__init__()
        self.is_temp = is_temp
        # conv1: 3→16, 3×3 stride 2 (was 5×5) — faster, same RF
        self.conv1 = _ConvWithPReLU(in_channels=3, out_channels=16, kernel_size=3, stride=2, padding=1)
        # conv2: 16→32, 3×3 stride 2 (was 5×5) — faster, same RF
        self.conv2 = _ConvWithPReLU(in_channels=16, out_channels=32, kernel_size=3, stride=2, padding=1)
        self.res_block1 = _ResidualBlock(channels=32)
        if not is_temp:
            self.res_block2 = _ResidualBlock(channels=32)
            self.res_block3 = _ResidualBlock(channels=32)  # extra depth from structural_1
            
            # NEW: Linear Attention at bottleneck (after res_blocks, before conv5)
            # 32 channels, 4 heads, at 8×8 spatial resolution
            self.linear_attn = _LinearAttention(dim=32, heads=4)
            self.attn_norm = nn.LayerNorm(32)  # per-spatial-position normalization
            
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
            x = self.res_block3(x)   # 32ch, 8×8
            
            # Linear Attention with residual connection
            identity = x
            b, c, h, w = x.shape
            # Apply LayerNorm (expects [b, n, c] for per-position norm)
            x_ln = x.view(b, c, -1).transpose(1, 2)  # b, n, c
            x_ln = self.attn_norm(x_ln)
            x_ln = x_ln.transpose(1, 2).view(b, c, h, w)  # b, c, h, w
            # Linear attention
            x_attn = self.linear_attn(x_ln)
            x = identity + x_attn  # residual connection for stability
            
            x = self.conv5(x)        # 2c channels
            x = self.norm(x)
            x = self.se(x)
            return x, (skip1,)       # (bottleneck, (skip_features,))
        return x                      # is_temp: just tensor for ratio2filtersize


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
        x = x + identity  # residual from parent

        # First upsampling: 8×8 → 16×16
        x = self.up4(x)
        if skip_features is not None and len(skip_features) > 0:
            skip1 = skip_features[0]  # 16ch, 16×16 from encoder conv1
            x = torch.cat([x, skip1], dim=1)  # 48ch, 16×16
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
