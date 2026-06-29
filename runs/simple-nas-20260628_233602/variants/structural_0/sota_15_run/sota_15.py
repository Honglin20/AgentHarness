# -*- coding: utf-8 -*-
"""
SOTA variant sota_15: Linear Attention bottleneck (Performer-style).

Replaces the 3× ResBottleneck blocks + CBAM at the 8×8 bottleneck with
2× Linear Self-Attention blocks using the ELU+1 feature map (Linear Transformer,
Katharopoulos et al., 2020). This captures global dependencies across the entire
8×8 spatial grid (64 tokens) with O(n) complexity — unlike the local 3×3 conv
receptive field of ResBottleneck blocks.

Architecture changes from parent (structural_12):
1. Remove ResBottleneck blocks (conv3, conv4, conv4b) + CBAM
2. Add 2× LinearAttentionBlock at 8×8 bottleneck (28ch, 4 heads, expansion=4)
3. Keep encoder conv1/conv2 downsampling, proj(32→28), ChannelRefinement
4. Keep decoder identical (2c→28→cat→28→16→cat→16→3)
5. Keep Channel layer (AWGN), Power Normalization

Rationale:
- Linear Attention is a genuinely untried SOTA template
- O(n) complexity avoids the latency blowup that Swin (O(n²)) caused
- Global receptive field at bottleneck should improve reconstruction quality
- Lightweight (<1ms latency expected)
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import sys
import os
import math

try:
    from channel import Channel
except ImportError:
    _proj_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../../projects/Deep-JSCC-PyTorch'))
    if os.path.isfile(os.path.join(_proj_root, 'channel.py')):
        sys.path.insert(0, _proj_root)
    else:
        sys.path.insert(0, os.getcwd())
    from channel import Channel


def dummy_inputs(batch_size=1):
    """Return dummy input for ONNX export: [B, 3, 32, 32] image tensor."""
    return torch.randn(batch_size, 3, 32, 32)


def ratio2filtersize(x: torch.Tensor, ratio):
    if x.dim() == 4:
        before_size = torch.prod(torch.tensor(x.size()[1:]))
    elif x.dim() == 3:
        before_size = torch.prod(torch.tensor(x.size()))
    else:
        raise Exception('Unknown size of input')
    encoder_temp = _UNetEncoder(is_temp=True)
    z_temp = encoder_temp(x)
    c = before_size * ratio / torch.prod(torch.tensor(z_temp.size()[-2:]))
    return int(c)


def _ensure_4d(x):
    """Add batch dim if input is 3D (unbatched). Returns (tensor, was_3d)."""
    if x.dim() == 3:
        return x.unsqueeze(0), True
    return x, False


def _restore_shape(x, was_3d):
    """Remove batch dim if original was 3D."""
    if was_3d:
        return x.squeeze(0)
    return x


class _ConvWithPReLU(nn.Module):
    """Conv layer with PReLU activation (faster, learnable)."""
    def __init__(self, in_channels, out_channels, kernel_size, stride=1, padding=0):
        super(_ConvWithPReLU, self).__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size, stride, padding)
        self.act = nn.PReLU(out_channels)
        nn.init.kaiming_normal_(self.conv.weight, mode='fan_out', nonlinearity='leaky_relu')

    def forward(self, x):
        x, was_3d = _ensure_4d(x)
        x = self.conv(x)
        x = self.act(x)
        return _restore_shape(x, was_3d)


class _TransConvWithPReLU(nn.Module):
    """Transposed Conv layer with PReLU activation."""
    def __init__(self, in_channels, out_channels, kernel_size, stride, padding=0, output_padding=0):
        super(_TransConvWithPReLU, self).__init__()
        self.transconv = nn.ConvTranspose2d(
            in_channels, out_channels, kernel_size, stride, padding, output_padding)
        self.act = nn.PReLU(out_channels)
        nn.init.xavier_normal_(self.transconv.weight)

    def forward(self, x):
        x, was_3d = _ensure_4d(x)
        x = self.transconv(x)
        x = self.act(x)
        return _restore_shape(x, was_3d)


class _LinearSelfAttention(nn.Module):
    """
    Linear Self-Attention with ELU+1 feature map (Katharopoulos et al., 2020).
    
    Instead of softmax(QK^T)V which is O(n²), this uses:
        V' = phi(Q) @ (phi(K)^T @ V)
    where phi(x) = ELU(x) + 1, giving O(n) complexity.
    
    Multi-head with 4 heads for diversity of attention patterns.
    """
    def __init__(self, channels, num_heads=4, eps=1e-6):
        super(_LinearSelfAttention, self).__init__()
        assert channels % num_heads == 0, f"channels {channels} must be divisible by num_heads {num_heads}"
        self.num_heads = num_heads
        self.head_dim = channels // num_heads
        self.eps = eps
        
        self.to_qkv = nn.Linear(channels, 3 * channels, bias=False)
        self.to_out = nn.Linear(channels, channels, bias=False)
        
        nn.init.xavier_uniform_(self.to_qkv.weight)
        nn.init.xavier_uniform_(self.to_out.weight)
    
    @staticmethod
    def _elu_feature_map(x):
        """ELU(x) + 1 feature map. Returns non-negative features for attention."""
        return F.elu(x) + 1.0
    
    def forward(self, x):
        """
        x: [B, C, H, W] — spatial features
        Returns: [B, C, H, W]
        """
        x, was_3d = _ensure_4d(x)
        B, C, H, W = x.shape
        N = H * W  # number of spatial positions (tokens)
        
        # Flatten spatial: [B, C, H, W] -> [B, N, C]
        x_flat = x.view(B, C, N).transpose(1, 2)  # [B, N, C]
        
        # Project to Q, K, V
        qkv = self.to_qkv(x_flat)  # [B, N, 3*C]
        Q, K, V = qkv.chunk(3, dim=-1)  # each [B, N, C]
        
        # Reshape for multi-head: [B, N, C] -> [B, N, H, D] -> [B*H, N, D]
        Q = Q.reshape(B, N, self.num_heads, self.head_dim).transpose(1, 2).reshape(B * self.num_heads, N, self.head_dim)
        K = K.reshape(B, N, self.num_heads, self.head_dim).transpose(1, 2).reshape(B * self.num_heads, N, self.head_dim)
        V = V.reshape(B, N, self.num_heads, self.head_dim).transpose(1, 2).reshape(B * self.num_heads, N, self.head_dim)
        
        # Apply feature map
        Q_prime = self._elu_feature_map(Q)  # [B*H, N, D]
        K_prime = self._elu_feature_map(K)  # [B*H, N, D]
        
        # Linear attention: V' = Q' @ (K'^T @ V) / (Q' @ sum(K'))
        # K'^T @ V: [D, D] — O(D²) not O(N²)
        KV = torch.bmm(K_prime.transpose(1, 2), V)  # [B*H, D, D]
        
        # Q' @ KV: [B*H, N, D]
        out = torch.bmm(Q_prime, KV)  # [B*H, N, D]
        
        # Normalization: denominator = Q' @ sum(K', dim=1)
        K_sum = K_prime.sum(dim=1, keepdim=True)  # [B*H, 1, D]
        denom = torch.bmm(Q_prime, K_sum.transpose(1, 2))  # [B*H, N, 1]
        denom = denom.clamp(min=self.eps)
        out = out / denom  # [B*H, N, D]
        
        # Reshape back: [B*H, N, D] -> [B, N, H, D] -> [B, N, C]
        out = out.reshape(B, self.num_heads, N, self.head_dim).transpose(1, 2).reshape(B, N, C)
        
        # Output projection
        out = self.to_out(out)  # [B, N, C]
        
        # Reshape back to spatial: [B, N, C] -> [B, C, H, W]
        out = out.transpose(1, 2).reshape(B, C, H, W)
        
        return _restore_shape(out, was_3d)


class _LinearAttentionBlock(nn.Module):
    """
    Linear Attention Block: LN → LinearSelfAttn → residual → LN → FFN → residual.
    
    The FFN is a 2-layer MLP: linear → GELU → linear with expansion=4.
    """
    def __init__(self, channels, num_heads=4, expansion=4):
        super(_LinearAttentionBlock, self).__init__()
        
        # Pre-attention LayerNorm
        self.norm1 = nn.LayerNorm(channels)
        
        # Linear Self-Attention
        self.attn = _LinearSelfAttention(channels, num_heads=num_heads)
        
        # Pre-FFN LayerNorm
        self.norm2 = nn.LayerNorm(channels)
        
        # FFN: linear → GELU → linear
        hidden_dim = channels * expansion
        self.ffn = nn.Sequential(
            nn.Linear(channels, hidden_dim, bias=True),
            nn.GELU(),
            nn.Linear(hidden_dim, channels, bias=True),
        )
        
        # Initialize FFN
        for layer in self.ffn:
            if isinstance(layer, nn.Linear):
                nn.init.xavier_uniform_(layer.weight)
                if layer.bias is not None:
                    nn.init.constant_(layer.bias, 0)
    
    def forward(self, x):
        """
        x: [B, C, H, W]
        Returns: [B, C, H, W]
        """
        x, was_3d = _ensure_4d(x)
        B, C, H, W = x.shape
        
        # Attention sub-block
        # Apply LayerNorm on channel dimension: need [B, N, C] format
        x_perm = x.permute(0, 2, 3, 1).reshape(B, H * W, C)  # [B, N, C]
        x_norm = self.norm1(x_perm)
        x_norm = x_norm.transpose(1, 2).reshape(B, C, H, W)  # [B, C, H, W]
        
        attn_out = self.attn(x_norm)  # [B, C, H, W]
        x = x + attn_out  # residual
        
        # FFN sub-block
        x_perm = x.permute(0, 2, 3, 1).reshape(B, H * W, C)  # [B, N, C]
        x_norm = self.norm2(x_perm)
        
        ffn_out = self.ffn(x_norm)  # [B, N, C]
        ffn_out = ffn_out.transpose(1, 2).reshape(B, C, H, W)  # [B, C, H, W]
        x = x + ffn_out  # residual
        
        return _restore_shape(x, was_3d)


class _ChannelRefinement(nn.Module):
    """
    Lightweight pre-bottleneck channel refinement: 1×1 conv + GELU.
    
    Adds non-linear channel mixing before the attention blocks process
    the compressed representation. Very lightweight (~ch² params).
    """
    def __init__(self, channels):
        super(_ChannelRefinement, self).__init__()
        self.conv = nn.Conv2d(channels, channels, kernel_size=1, stride=1, padding=0)
        self.act = nn.GELU()
        nn.init.kaiming_normal_(self.conv.weight, mode='fan_out', nonlinearity='relu')
        if self.conv.bias is not None:
            nn.init.constant_(self.conv.bias, 0)

    def forward(self, x):
        x, was_3d = _ensure_4d(x)
        identity = x
        x = self.conv(x)
        x = self.act(x)
        x = x + identity  # Residual connection for stable gradients
        return _restore_shape(x, was_3d)


class _UNetEncoder(nn.Module):
    """
    UNet encoder with Linear Attention bottleneck (replaces ResBottleneck + CBAM).
    
    conv1 → conv2 downsampling → proj → ChannelRefinement → 
    2× LinearAttentionBlock (with 4-head linear self-attention) →
    conv5 (output projection to 2c) → Power Normalization
    """
    def __init__(self, c=1, is_temp=False, P=1):
        super(_UNetEncoder, self).__init__()
        self.is_temp = is_temp
        bottleneck_ch = 28  # Same as parent structural_12
        
        # Down 1: 32x32 -> 16x16
        self.conv1 = _ConvWithPReLU(in_channels=3, out_channels=16, kernel_size=3, stride=2, padding=1)
        # Down 2: 16x16 -> 8x8
        self.conv2 = _ConvWithPReLU(in_channels=16, out_channels=32, kernel_size=3, stride=2, padding=1)
        
        # --- SOTA CHANGE: Linear Attention blocks (replacing 3× ResBottleneck + CBAM) ---
        self.attn_block1 = _LinearAttentionBlock(channels=bottleneck_ch, num_heads=4, expansion=4)
        self.attn_block2 = _LinearAttentionBlock(channels=bottleneck_ch, num_heads=4, expansion=4)
        
        # Output projection: bottleneck_ch -> 2c
        self.conv5 = _ConvWithPReLU(in_channels=bottleneck_ch, out_channels=2*c, kernel_size=3, padding=1)
        
        # Projection: conv2 out (32ch) -> bottleneck (28ch)
        self.proj = nn.Conv2d(32, bottleneck_ch, kernel_size=1, stride=1, padding=0)
        nn.init.kaiming_normal_(self.proj.weight, mode='fan_out', nonlinearity='leaky_relu')
        if self.proj.bias is not None:
            nn.init.constant_(self.proj.bias, 0)
        
        # Pre-attention channel refinement (kept from parent)
        self.refine = _ChannelRefinement(channels=bottleneck_ch)
        
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
            else:
                raise Exception('Unknown size of input')
            z_temp = z_hat.reshape(batch_size, 1, 1, -1)
            z_trans = z_hat.reshape(batch_size, 1, -1, 1)
            tensor = torch.sqrt(P * k) * z_hat / torch.sqrt((z_temp @ z_trans))
            if batch_size == 1:
                return tensor.squeeze(0)
            return tensor
        return _inner

    def forward(self, x):
        s1 = self.conv1(x)        # [B, 16, 16, 16]
        s2 = self.conv2(s1)       # [B, 32, 8, 8]
        
        x = self.proj(s2)         # [B, 28, 8, 8]
        x = self.refine(x)        # [B, 28, 8, 8]
        
        # --- Linear Attention blocks (replacing ResBottleneck + CBAM) ---
        x = self.attn_block1(x)   # [B, 28, 8, 8]
        x = self.attn_block2(x)   # [B, 28, 8, 8]
        
        if not self.is_temp:
            x = self.conv5(x)     # [B, 2c, 8, 8]
            x = self.norm(x)
            s1, _ = _ensure_4d(s1)
            s2, _ = _ensure_4d(s2)
            return x, s1, s2
        else:
            return x


class _UNetDecoder(nn.Module):
    """
    UNet decoder (identical to parent structural_12).
    
    tconv1(2c→28) → cat(28+32=60) → tconv2(60→28) → 
    tconv3(28→16, upsample) → cat(16+16=32) → tconv4(32→16) → 
    tconv5(16→3, sigmoid)
    """
    def __init__(self, c=1):
        super(_UNetDecoder, self).__init__()
        interm_ch = 28
        
        self.tconv1 = _TransConvWithPReLU(
            in_channels=2*c, out_channels=interm_ch, kernel_size=3, stride=1, padding=1)
        
        self.tconv2 = _TransConvWithPReLU(
            in_channels=interm_ch + 32, out_channels=interm_ch, kernel_size=3, stride=1, padding=1)
        
        self.tconv3 = _TransConvWithPReLU(
            in_channels=interm_ch, out_channels=16, kernel_size=3, stride=2, padding=1, output_padding=1)
        
        self.tconv4 = _TransConvWithPReLU(
            in_channels=32, out_channels=16, kernel_size=3, stride=1, padding=1)
        
        self.tconv5 = _TransConvWithActSigmoid(
            in_channels=16, out_channels=3, kernel_size=3, stride=2, padding=1, output_padding=1)

    def forward(self, x, s1, s2):
        x, _ = _ensure_4d(x)
        s1, _ = _ensure_4d(s1)
        s2, _ = _ensure_4d(s2)
        
        x = self.tconv1(x)                     # [B, 28, 8, 8]
        x = torch.cat([x, s2], dim=1)          # [B, 60, 8, 8]  (28 + 32)
        x = self.tconv2(x)                     # [B, 28, 8, 8]
        x = self.tconv3(x)                     # [B, 16, 16, 16]
        x = torch.cat([x, s1], dim=1)          # [B, 32, 16, 16]
        x = self.tconv4(x)                     # [B, 16, 16, 16]
        x = self.tconv5(x)                     # [B, 3, 32, 32]
        return x


class _TransConvWithActSigmoid(nn.Module):
    """Transposed Conv with Sigmoid activation (for final reconstruction)."""
    def __init__(self, in_channels, out_channels, kernel_size, stride, padding=0, output_padding=0):
        super(_TransConvWithActSigmoid, self).__init__()
        self.transconv = nn.ConvTranspose2d(
            in_channels, out_channels, kernel_size, stride, padding, output_padding)
        self.act = nn.Sigmoid()
        nn.init.xavier_normal_(self.transconv.weight)

    def forward(self, x):
        x, was_3d = _ensure_4d(x)
        x = self.transconv(x)
        x = self.act(x)
        return _restore_shape(x, was_3d)


class DeepJSCC(nn.Module):
    """
    DeepJSCC with Linear Attention bottleneck.
    
    Encoder uses 2× LinearAttentionBlock (4 heads, ELU+1 feature map)
    at the 8×8 bottleneck instead of ResBottleneck + CBAM.
    """
    def __init__(self, c, channel_type='AWGN', snr=None):
        super(DeepJSCC, self).__init__()
        self.encoder = _UNetEncoder(c=c)
        if snr is not None:
            self.channel = Channel(channel_type, snr)
        self.decoder = _UNetDecoder(c=c)

    def forward(self, x):
        z, s1, s2 = self.encoder(x)
        if hasattr(self, 'channel') and self.channel is not None:
            z = self.channel(z)
        x_hat = self.decoder(z, s1, s2)
        return x_hat
