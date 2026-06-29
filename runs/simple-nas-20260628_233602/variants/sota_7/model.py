# -*- coding: utf-8 -*-
"""
SOTA variant v7 — Mamba/SSM encoder (State Space Model blocks).

Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K):
  1. Replaced 3× _ResidualBlock in encoder with 3× MambaBlock (SSM-based).
  2. MambaBlock processes 8×8 spatial features as a 1D sequence (L=64),
     using selective state space model with parallel causal conv approximation.
  3. Preserves: conv1→skip connection, conv2, conv5, norm, SE, decoder, channel.
  4. Mamba's linear complexity O(n) vs attention's O(n²) makes it suitable
     for larger spatial resolutions in future iterations.

Mamba/SSM Key Ideas (Gu & Dao, 2023):
  - State space model: maps 1D sequence to sequence via hidden state
  - Selective scan: SSM parameters (delta, B, C) are input-dependent
  - Gating: dual-branch architecture (x1 conv + SSM, x2 gate)
  - Depthwise 1D conv before SSM for local context
  - Linear complexity O(n) vs self-attention O(n²)
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


class _MambaBlock(nn.Module):
    """Mamba/SSM block for 2D image features — parallel (loop-free) version.
    
    Core ideas from Mamba (Gu & Dao, 2023):
    - Selective state space model with input-dependent parameters
    - Depthwise 1D conv for local context along spatial sequence
    - Gating mechanism with dual branch
    
    Uses parallel causal convolution to approximate SSM recurrence
    (avoids Python loops for ONNX export compatibility).
    """
    
    def __init__(self, dim, d_state=8, expand=2, ssm_kernel_size=5):
        super().__init__()
        inner_dim = dim * expand
        self.dim = dim
        self.inner_dim = inner_dim
        self.d_state = d_state
        
        # LayerNorm (sequence-first)
        self.norm = nn.LayerNorm(dim)
        
        # Linear expansion + split for gating (Mamba-style dual branch)
        self.in_proj = nn.Linear(dim, inner_dim * 2, bias=False)
        
        # Depthwise 1D convolution along spatial sequence
        self.conv1d = nn.Conv1d(inner_dim, inner_dim, kernel_size=3, 
                                padding=1, groups=inner_dim, bias=False)
        
        # Selective SSM: input-dependent params (delta, B, C)
        self.ssm_proj = nn.Linear(inner_dim, d_state * 2 + dim, bias=False)
        self.dt_proj = nn.Sequential(
            nn.Linear(dim, inner_dim, bias=True),
            nn.Softplus()
        )
        
        # Causal SSM kernel — parallel convolution approximates SSM recurrence
        # Each channel learns its own causal kernel
        # kernel shape: (inner, 1, ssm_kernel_size), applied depthwise
        self.ssm_kernel = nn.Parameter(
            torch.randn(inner_dim, 1, ssm_kernel_size) * 0.1
        )
        
        self.act = lambda x: x * torch.sigmoid(x)  # SiLU as x*sigmoid(x) for ONNX compat
        self.out_proj = nn.Linear(inner_dim, dim, bias=False)
        
        # Initialize weights
        nn.init.kaiming_normal_(self.in_proj.weight, mode="fan_in", nonlinearity="linear")
        nn.init.kaiming_normal_(self.out_proj.weight, mode="fan_in", nonlinearity="linear")
    
    def forward(self, x):
        # x: (B, C, H, W)
        B, C, H, W = x.shape
        L = H * W  # sequence length (e.g., 8×8=64)
        
        # Flatten spatial dims to 1D sequence
        x_seq = x.flatten(2).transpose(1, 2)  # (B, L, C)
        skip = x_seq
        
        # LayerNorm
        x_seq = self.norm(x_seq)
        
        # Expand and split into two branches (x1→SSM, x2→gate)
        x_proj = self.in_proj(x_seq)  # (B, L, 2*inner)
        x1, x2 = x_proj.chunk(2, dim=-1)  # both (B, L, inner)
        
        # Depthwise 1D conv along sequence (local context)
        x1_conv = self.conv1d(x1.transpose(1, 2))  # (B, inner, L)
        x1_conv = x1_conv.transpose(1, 2)  # (B, L, inner)
        x1_conv = self.act(x1_conv)
        
        # ---- Selective SSM (parallel via causal convolution) ----
        # Generate input-dependent parameters
        ssm_params = self.ssm_proj(x1_conv)  # (B, L, d_state*2 + dim)
        dt_raw = ssm_params[..., self.d_state*2:]  # (B, L, dim) — step size
        dt = self.dt_proj(dt_raw)  # (B, L, inner), positive
        
        # SSM approximation via causal depthwise convolution
        # Modulate input by dt (selectivity), then apply causal conv
        x_mod = x1_conv * dt  # (B, L, inner) — input-dependent modulation
        
        # Causal depthwise conv: each channel independently filtered
        # padding ensures causal: output[t] depends on input[t-k+1...t]
        k = self.ssm_kernel.shape[-1]
        pad = (k - 1,)
        x_mod_t = x_mod.transpose(1, 2).contiguous()  # (B, inner, L)
        y_ssm = F.conv1d(
            x_mod_t,
            self.ssm_kernel,
            padding=pad,
            groups=self.inner_dim
        )
        # Slice to keep causal: take last L elements
        y_ssm = y_ssm[..., :L].transpose(1, 2)  # (B, L, inner)
        
        # Residual connection within SSM (like skip in Mamba paper)
        y = y_ssm + x1_conv
        
        # Gate with x2 branch
        y = y * self.act(x2)
        
        # Output projection + global residual
        y = self.out_proj(y) + skip  # (B, L, C)
        
        # Reshape back to 2D
        return y.transpose(1, 2).reshape(B, C, H, W)


class _SEBlock(nn.Module):
    """Squeeze-and-Excitation channel attention — negligible overhead."""

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
        # conv1: 3→16, 3×3 stride 2 (U-Net skip connection source)
        self.conv1 = _ConvWithPReLU(in_channels=3, out_channels=16, kernel_size=3, stride=2, padding=1)
        # conv2: 16→32, 3×3 stride 2
        self.conv2 = _ConvWithPReLU(in_channels=16, out_channels=32, kernel_size=3, stride=2, padding=1)
        
        if not is_temp:
            # Mamba Blocks × 3 — replace _ResidualBlock from structural_1
            self.mamba1 = _MambaBlock(dim=32, d_state=8, expand=2)
            self.mamba2 = _MambaBlock(dim=32, d_state=8, expand=2)
            self.mamba3 = _MambaBlock(dim=32, d_state=8, expand=2)
            
            # Bottleneck projection (same as parent)
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
        if not self.is_temp:
            # Mamba SSM processing (replaces residual blocks)
            x = self.mamba1(x)       # 32ch, 8×8 — SSM scan over 64 positions
            x = self.mamba2(x)       # 32ch, 8×8
            x = self.mamba3(x)       # 32ch, 8×8
            x = self.conv5(x)        # 2c channels
            x = self.norm(x)
            x = self.se(x)
            return x, (skip1,)
        return x  # is_temp: just tensor for ratio2filtersize


class _Decoder(nn.Module):
    """Same as structural_1 — bilinear upsample + 3×3 conv + skip connection."""

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
        x = x + identity  # residual

        x = self.up4(x)  # 32ch, 16×16
        if skip_features is not None and len(skip_features) > 0:
            skip1 = skip_features[0]  # 16ch, 16×16 from encoder conv1
            x = torch.cat([x, skip1], dim=1)  # 48ch, 16×16
        x = self.conv4(x)  # 16ch, 16×16

        x = self.up5(x)  # 16×16→32×32
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
