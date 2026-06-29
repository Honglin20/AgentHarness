# -*- coding: utf-8 -*-
"""
SOTA variant v2 — ViT Encoder + CNN Decoder (hybrid).

Template: ViT (Vision Transformer) encoder + bilinear-upsample CNN decoder.
Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K):
  1. CNN encoder → ViT encoder (patch embedding + 4× Transformer blocks)
  2. ViT captures global context via self-attention at 8×8 patch grid
  3. Decoder adapted from parent (removed U-Net skip, adjusted channels)
  4. Keeps: Channel (AWGN), power normalization, output interface

Rationale: Global self-attention helps the bottleneck allocate bits
efficiently for wireless image transmission — common in SOTA image
restoration (SwinIR, Restormer).
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
    encoder_temp = ViTEncoder(is_temp=True)
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


class MultiHeadAttention(nn.Module):
    """Scaled dot-product multi-head attention."""

    def __init__(self, dim, num_heads=4):
        super().__init__()
        assert dim % num_heads == 0, f"dim {dim} not divisible by num_heads {num_heads}"
        self.num_heads = num_heads
        self.head_dim = dim // num_heads
        self.scale = self.head_dim ** -0.5

        self.qkv = nn.Linear(dim, dim * 3)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x):
        B, N, C = x.shape
        qkv = self.qkv(x).reshape(B, N, 3, self.num_heads, self.head_dim)
        qkv = qkv.permute(2, 0, 3, 1, 4)  # 3, B, H, N, D
        q, k, v = qkv[0], qkv[1], qkv[2]

        attn = (q @ k.transpose(-2, -1)) * self.scale
        attn = attn.softmax(dim=-1)

        x = (attn @ v).transpose(1, 2).reshape(B, N, C)
        x = self.proj(x)
        return x


class MLP(nn.Module):
    def __init__(self, dim, hidden_dim=None, mlp_ratio=4.0):
        super().__init__()
        hidden_dim = hidden_dim or int(dim * mlp_ratio)
        self.fc1 = nn.Linear(dim, hidden_dim)
        self.act = nn.GELU()
        self.fc2 = nn.Linear(hidden_dim, dim)

    def forward(self, x):
        x = self.fc1(x)
        x = self.act(x)
        x = self.fc2(x)
        return x


class TransformerBlock(nn.Module):
    def __init__(self, dim, num_heads=4, mlp_ratio=4.0):
        super().__init__()
        self.norm1 = nn.LayerNorm(dim)
        self.attn = MultiHeadAttention(dim, num_heads)
        self.norm2 = nn.LayerNorm(dim)
        self.mlp = MLP(dim, mlp_ratio=mlp_ratio)

    def forward(self, x):
        x = x + self.attn(self.norm1(x))
        x = x + self.mlp(self.norm2(x))
        return x


class ViTEncoder(nn.Module):
    """
    Vision Transformer encoder.
    
    - Patch embedding: Conv2d(3→embed_dim, kernel=patch_size, stride=patch_size)
    - Position embedding: learnable 1D
    - Transformer blocks with LayerNorm + MHA + MLP
    - Output projection to 2*c channels (bottleneck)
    
    Supports is_temp mode for ratio2filtersize computation.
    """

    def __init__(self, c=1, is_temp=False, P=1,
                 img_size=32, patch_size=4, embed_dim=64, depth=4, num_heads=4):
        super().__init__()
        self.is_temp = is_temp
        self.patch_size = patch_size
        self.embed_dim = embed_dim
        self.img_size = img_size

        # Patch embedding
        self.patch_embed = nn.Conv2d(3, embed_dim, kernel_size=patch_size, stride=patch_size)
        num_patches = (img_size // patch_size) ** 2  # 64 for 32×32 img, patch=4

        # Position embedding
        self.pos_embed = nn.Parameter(torch.randn(1, num_patches, embed_dim) * 0.02)
        self.pos_drop = nn.Dropout(0.1)

        # Transformer blocks
        self.blocks = nn.ModuleList([
            TransformerBlock(embed_dim, num_heads) for _ in range(depth)
        ])
        self.norm = nn.LayerNorm(embed_dim)

        if not is_temp:
            # Project transformer output to bottleneck channels (2*c)
            self.proj = nn.Linear(embed_dim, 2 * c)
            # Power normalization (same as parent)
            self.norm_layer = self._normlizationLayer(P=P)

    @staticmethod
    def _normlizationLayer(P=1):
        class PowerNorm(nn.Module):
            def __init__(self, P_val):
                super().__init__()
                self.P = P_val
            def forward(self, z_hat):
                B = z_hat.size(0)
                k = z_hat.size(1) * z_hat.size(2) * z_hat.size(3)
                z_flat = z_hat.reshape(B, -1).float()
                # Manual norm: sqrt(sum(x^2)) - avoid torch.norm for ONNX compat
                z_sq_sum = (z_flat ** 2).sum(dim=1, keepdim=True)
                z_norm = z_sq_sum ** 0.5
                scale = torch.sqrt(torch.tensor(self.P * k, dtype=z_hat.dtype))
                return scale * z_hat / z_norm.view(B, 1, 1, 1).to(z_hat.dtype)
        return PowerNorm(P)

    def forward(self, x):
        B = x.shape[0]

        # Patch embed: B, 3, 32, 32 → B, embed_dim, 8, 8
        x = self.patch_embed(x)

        if self.is_temp:
            # is_temp: just return patch embedding output for ratio2filtersize
            return x

        H, W = x.shape[2], x.shape[3]
        # Flatten to sequence: B, embed_dim, H, W → B, N, embed_dim
        x = x.flatten(2).transpose(1, 2)  # B, N=64, embed_dim

        # Add position embedding
        x = x + self.pos_embed
        x = self.pos_drop(x)

        # Transformer blocks
        for blk in self.blocks:
            x = blk(x)

        x = self.norm(x)

        # Project to bottleneck: B, N, embed_dim → B, N, 2*c
        x = self.proj(x)  # B, N, 2*c

        # Reshape back to spatial: B, 2*c, H, W
        x = x.transpose(1, 2).reshape(B, -1, H, W)  # B, 2*c, 8, 8

        # Power normalization
        x = self.norm_layer(x)

        # No skip features for ViT (single-scale processing)
        return x, ()


class Decoder(nn.Module):
    """
    CNN decoder with bilinear upsampling + 3×3 convs.
    Adapted from structural_1 — removed U-Net skip connection handling.
    """

    def __init__(self, c=1):
        super().__init__()
        # conv1-3: process bottleneck features
        self.conv1 = _ConvWithPReLU(in_channels=2*c, out_channels=32, kernel_size=3, padding=1)
        self.conv2 = _ConvWithPReLU(in_channels=32, out_channels=32, kernel_size=3, padding=1)
        self.conv3 = _ConvWithPReLU(in_channels=32, out_channels=32, kernel_size=3, padding=1)

        # Upsample + conv (8×8 → 16×16)
        self.up4 = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)
        self.conv4 = _ConvWithPReLU(in_channels=32, out_channels=16, kernel_size=3, padding=1)

        # Upsample + conv (16×16 → 32×32)
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
        x = x + identity  # residual connection

        # Upsample 8×8 → 16×16
        x = self.up4(x)  # 32ch, 16×16
        x = self.conv4(x)  # 16ch, 16×16

        # Upsample 16×16 → 32×32
        x = self.up5(x)
        x = self.conv5(x)  # 3ch, 32×32
        return x


class DeepJSCC(nn.Module):
    def __init__(self, c, channel_type="AWGN", snr=None):
        super().__init__()
        self.encoder = ViTEncoder(c=c)
        if snr is not None:
            self.channel = Channel(channel_type, snr)
        self.decoder = Decoder(c=c)

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
