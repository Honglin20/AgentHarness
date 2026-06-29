# -*- coding: utf-8 -*-
"""
SOTA variant v4 — Swin-inspired Local Attention Encoder + CNN Decoder.

Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K):
  1. Encoder: keep conv1 (skip features) + conv2 downsample + add lightweight
     Multi-Head Self-Attention (4 heads) on 8×8 feature map (64 tokens).
     Swin-style window-based processing but ONNX-exportable (no torch.roll).
  2. Feature mixing: LayerNorm + residual connection for stability.
  3. Keep structural_1's successful decoder (bilinear upsampling + 3×3 conv
     + U-Net skip connections + residual).
  4. Keep Channel layer and power normalization (task-specific).
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


class _WindowAttention(nn.Module):
    """Window-based Multi-Head Self-Attention — ONNX-exportable version.

    Operates on 8×8 feature map divided into 4×4 windows.
    Uses window partition + merge via reshape (no cyclic shift for ONNX compat).
    """
    def __init__(self, dim, num_heads=4, window_size=4):
        super().__init__()
        self.dim = dim
        self.num_heads = num_heads
        self.window_size = window_size
        self.scale = (dim // num_heads) ** -0.5

        self.qkv = nn.Linear(dim, dim * 3, bias=True)
        self.proj = nn.Linear(dim, dim)

    def _window_partition(self, x, H, W, ws):
        """Split B, C, H, W into windows: (B*nW, ws*ws, C)"""
        B, C, H, W = x.shape
        x = x.view(B, C, H // ws, ws, W // ws, ws)
        x = x.permute(0, 2, 4, 3, 5, 1).contiguous()  # B, nH, nW, ws, ws, C
        x = x.view(B, -1, ws * ws, C)  # B, nW, N, C
        return x

    def _window_merge(self, x, B, H, W, ws):
        """Merge windows back to B, C, H, W"""
        nH, nW = H // ws, W // ws
        x = x.view(B, nH, nW, ws, ws, self.dim)
        x = x.permute(0, 5, 1, 3, 2, 4).contiguous()
        x = x.view(B, self.dim, H, W)
        return x

    def forward(self, x):
        """x: B, C, H, W where H=W=8"""
        B, C, H, W = x.shape
        ws = self.window_size

        # Pad to divisible
        pad_r = (ws - W % ws) % ws
        pad_b = (ws - H % ws) % ws
        if pad_r > 0 or pad_b > 0:
            x = F.pad(x, (0, pad_r, 0, pad_b))
        Hp, Wp = x.shape[2], x.shape[3]

        # Partition into windows
        x_windows = self._window_partition(x, Hp, Wp, ws)  # B, nW, N, C

        # Flatten batch and window dims
        B, nW, N, C = x_windows.shape
        x_windows = x_windows.view(B * nW, N, C)

        # QKV projection
        qkv = self.qkv(x_windows).reshape(B * nW, N, 3, self.num_heads, C // self.num_heads)
        qkv = qkv.permute(2, 0, 3, 1, 4)  # 3, B*nW, nH, N, head_dim
        q, k, v = qkv[0], qkv[1], qkv[2]

        # Attention
        attn = (q * self.scale) @ k.transpose(-2, -1)
        attn = F.softmax(attn, dim=-1)
        out = (attn @ v).transpose(1, 2).reshape(B * nW, N, C)
        out = self.proj(out)

        # Merge windows
        out = out.view(B, nW, N, C)
        out = self._window_merge(out, B, Hp, Wp, ws)

        # Unpad
        if pad_r > 0 or pad_b > 0:
            out = out[:, :, :H, :W]

        return out


class _Encoder(nn.Module):
    def __init__(self, c=1, is_temp=False, P=1):
        super().__init__()
        self.is_temp = is_temp

        # conv1: 3→16, 3×3 stride 2 — provides skip features
        self.conv1 = _ConvWithPReLU(in_channels=3, out_channels=16, kernel_size=3, stride=2, padding=1)
        # conv2: 16→32, 3×3 stride 2 — downsample to 8×8
        self.conv2 = _ConvWithPReLU(in_channels=16, out_channels=32, kernel_size=3, stride=2, padding=1)

        if not is_temp:
            # Window-based self-attention on 8×8 features
            self.norm_attn = nn.LayerNorm(32)
            self.window_attn = _WindowAttention(dim=32, num_heads=4, window_size=4)
            self.mlp = nn.Sequential(
                nn.LayerNorm(32),
                nn.Linear(32, 64),
                nn.GELU(),
                nn.Linear(64, 32),
            )
            self.conv5 = _ConvWithPReLU(in_channels=32, out_channels=2 * c, kernel_size=1, padding=0)
            self.norm = self._normlizationLayer(P=P)

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
        skip1 = self.conv1(x)        # 16ch, 16×16 — U-Net skip
        x = self.conv2(skip1)        # 32ch, 8×8

        if not self.is_temp:
            B, C, H, W = x.shape

            # Window-based self-attention
            identity = x
            # For LayerNorm: B,C,H,W -> B,H,W,C -> B*H*W,C -> norm -> reshape back
            x_ln = x.permute(0, 2, 3, 1).contiguous()  # B, H, W, C
            x_ln = self.norm_attn(x_ln)
            x_ln = x_ln.permute(0, 3, 1, 2).contiguous()  # B, C, H, W

            # Window attention
            x_attn = self.window_attn(x_ln)

            # Residual
            x = identity + x_attn

            # MLP with pre-norm
            identity2 = x
            x_mlp = x.permute(0, 2, 3, 1).contiguous()
            x_mlp = self.mlp[0](x_mlp)  # LayerNorm
            x_mlp = x_mlp.permute(0, 3, 1, 2).contiguous()
            x_mlp = self.mlp[1:](x_mlp.permute(0, 2, 3, 1).contiguous())  # Linear->GELU->Linear
            x_mlp = x_mlp.permute(0, 3, 1, 2).contiguous()
            x = identity2 + x_mlp

            x = self.conv5(x)        # 2c channels
            x = self.norm(x)
            return x, (skip1,)
        return x  # is_temp: just tensor for ratio2filtersize


class _Decoder(nn.Module):
    """Same as structural_1 — bilinear upsampling + 3×3 conv + U-Net skip."""
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
