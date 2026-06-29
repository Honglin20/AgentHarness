# -*- coding: utf-8 -*-
"""
DenseNet-style DeepJSCC variant — SOTA mutator iter 1
Replaces plain CNN encoder-decoder with DenseNet-style dense connectivity.
"""
import torch
import torch.nn as nn
from channel import Channel


def ratio2filtersize(x: torch.Tensor, ratio):
    if x.dim() == 4:
        before_size = float(x.size(1) * x.size(2) * x.size(3))
    elif x.dim() == 3:
        before_size = float(x.size(0) * x.size(1) * x.size(2))
    else:
        raise Exception('Unknown size of input')
    encoder_temp = _Encoder(is_temp=True)
    z_temp = encoder_temp(x)
    c = before_size * ratio / float(z_temp.size(-2) * z_temp.size(-1))
    return int(c)


class _DenseLayer(nn.Module):
    """Single DenseNet layer: Conv2D(3×3, growth_rate) + PReLU."""
    def __init__(self, in_channels, growth_rate):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, growth_rate, kernel_size=3, stride=1, padding=1)
        self.prelu = nn.PReLU()
        nn.init.kaiming_normal_(self.conv.weight, mode='fan_out', nonlinearity='leaky_relu')

    def forward(self, x):
        out = self.prelu(self.conv(x))
        # Concatenate input and output (dense connection)
        out = torch.cat([x, out], dim=1)
        return out


class _DenseBlock(nn.Module):
    """
    DenseBlock: N dense layers, each with growth_rate channels.
    Output channels = in_channels + N * growth_rate.
    """
    def __init__(self, in_channels, num_layers, growth_rate):
        super().__init__()
        self.layers = nn.ModuleList()
        current_channels = in_channels
        for i in range(num_layers):
            self.layers.append(_DenseLayer(current_channels, growth_rate))
            current_channels += growth_rate

    def forward(self, x):
        for layer in self.layers:
            x = layer(x)
        return x


class _Transition(nn.Module):
    """
    Transition layer: 1×1 conv (channel compression) + 2×2 avg pool.
    """
    def __init__(self, in_channels, out_channels):
        super().__init__()
        self.conv = nn.Conv2d(in_channels, out_channels, kernel_size=1, stride=1, padding=0)
        self.prelu = nn.PReLU()
        self.pool = nn.AvgPool2d(kernel_size=2, stride=2)
        nn.init.kaiming_normal_(self.conv.weight, mode='fan_out', nonlinearity='leaky_relu')

    def forward(self, x):
        x = self.prelu(self.conv(x))
        x = self.pool(x)
        return x


class _Encoder(nn.Module):
    """
    DenseNet-style encoder:
    Initial conv → DenseBlock1 → Transition1 → DenseBlock2 → bottleneck → power norm
    """
    def __init__(self, c=1, is_temp=False, P=1):
        super().__init__()
        self.is_temp = is_temp

        # Initial convolution: 3→32, 5×5 stride 2 (32→16 spatial)
        self.init_conv = nn.Conv2d(3, 32, kernel_size=5, stride=2, padding=2)
        self.init_prelu = nn.PReLU()
        nn.init.kaiming_normal_(self.init_conv.weight, mode='fan_out', nonlinearity='leaky_relu')

        # DenseBlock1: 32 channels in, 4 layers, growth=12 → 32+48=80 channels, 16×16
        self.db1 = _DenseBlock(in_channels=32, num_layers=4, growth_rate=12)

        # Transition1: 80→48 channels, 8×8 spatial
        self.trans1 = _Transition(in_channels=80, out_channels=48)

        # DenseBlock2: 48 channels in, 4 layers, growth=12 → 48+48=96 channels, 8×8
        self.db2 = _DenseBlock(in_channels=48, num_layers=4, growth_rate=12)

        # Bottleneck: 96→2*c
        if not is_temp:
            self.bottleneck = nn.Conv2d(96, 2 * c, kernel_size=3, stride=1, padding=1)
            self.bottleneck_prelu = nn.PReLU()
            nn.init.kaiming_normal_(self.bottleneck.weight, mode='fan_out', nonlinearity='leaky_relu')
            self.norm = self._normlizationLayer(P=P)

    @staticmethod
    def _normlizationLayer(P=1):
        def _inner(z_hat: torch.Tensor):
            # Ensure 4D: add batch dim if needed
            if z_hat.dim() == 3:
                z_hat = z_hat.unsqueeze(0)
            batch_size = z_hat.size()[0]
            k = torch.prod(torch.tensor([z_hat.size()[1], z_hat.size()[2], z_hat.size()[3]]))
            z_flat = z_hat.reshape(batch_size, -1).float()
            z_sq = torch.mul(z_flat, z_flat)
            z_norm = torch.sqrt(torch.sum(z_sq, dim=1, keepdim=True))
            tensor = torch.sqrt(P * k.float()) * z_hat / z_norm.view(batch_size, 1, 1, 1)
            return tensor
        return _inner

    def forward(self, x):
        # Ensure 4D: add batch dim if needed
        if x.dim() == 3:
            x = x.unsqueeze(0)
        x = self.init_prelu(self.init_conv(x))        # [B, 32, 16, 16]
        x = self.db1(x)                                 # [B, 80, 16, 16]
        x = self.trans1(x)                               # [B, 48, 8, 8]
        x = self.db2(x)                                  # [B, 96, 8, 8]

        if not self.is_temp:
            x = self.bottleneck_prelu(self.bottleneck(x))  # [B, 2*c, 8, 8]
            x = self.norm(x)
        return x


class _Decoder(nn.Module):
    """
    DenseNet-style decoder:
    Init conv → DenseBlock3 → Upsample → DenseBlock4 → Upsample → output
    """
    def __init__(self, c=1):
        super().__init__()

        # Initial projection: 2*c → 48
        self.init_conv = nn.Conv2d(2 * c, 48, kernel_size=3, stride=1, padding=1)
        self.init_prelu = nn.PReLU()
        nn.init.kaiming_normal_(self.init_conv.weight, mode='fan_out', nonlinearity='leaky_relu')

        # DenseBlock3: 48 channels in, 4 layers, growth=12 → 48+48=96, 8×8
        self.db3 = _DenseBlock(in_channels=48, num_layers=4, growth_rate=12)

        # Transition to 32 channels for upsampling
        self.trans2 = nn.Conv2d(96, 32, kernel_size=1, stride=1, padding=0)
        self.trans2_prelu = nn.PReLU()
        nn.init.kaiming_normal_(self.trans2.weight, mode='fan_out', nonlinearity='leaky_relu')

        # DenseBlock4: 32 channels in, 4 layers, growth=12 → 32+48=80, 16×16
        self.db4 = _DenseBlock(in_channels=32, num_layers=4, growth_rate=12)

        # Transition to 16 channels for final upsampling
        self.trans3 = nn.Conv2d(80, 16, kernel_size=1, stride=1, padding=0)
        self.trans3_prelu = nn.PReLU()
        nn.init.kaiming_normal_(self.trans3.weight, mode='fan_out', nonlinearity='leaky_relu')

        # DenseBlock5: 16 channels in, 3 layers, growth=12 → 16+36=52, 32×32
        self.db5 = _DenseBlock(in_channels=16, num_layers=3, growth_rate=12)

        # Output: 52→3, 3×3, sigmoid
        self.out_conv = nn.Conv2d(52, 3, kernel_size=3, stride=1, padding=1)
        self.sigmoid = nn.Sigmoid()
        nn.init.xavier_normal_(self.out_conv.weight)

    def forward(self, x):
        # Ensure 4D: add batch dim if needed
        if x.dim() == 3:
            x = x.unsqueeze(0)
        x = self.init_prelu(self.init_conv(x))          # [B, 48, 8, 8]
        x = self.db3(x)                                  # [B, 96, 8, 8]

        # Upsample to 16×16
        x = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)(x)
        x = self.trans2_prelu(self.trans2(x))            # [B, 32, 16, 16]
        x = self.db4(x)                                  # [B, 80, 16, 16]

        # Upsample to 32×32
        x = nn.Upsample(scale_factor=2, mode='bilinear', align_corners=False)(x)
        x = self.trans3_prelu(self.trans3(x))            # [B, 16, 32, 32]
        x = self.db5(x)                                  # [B, 52, 32, 32]

        x = self.sigmoid(self.out_conv(x))               # [B, 3, 32, 32]
        return x


class DeepJSCC(nn.Module):
    """
    DenseNet-based DeepJSCC with dense connections for maximum feature reuse.
    Preserves: Channel layer, power normalization, input/output interface.
    """
    def __init__(self, c, channel_type='AWGN', snr=None):
        super().__init__()
        self.encoder = _Encoder(c=c)
        if snr is not None:
            self.channel = Channel(channel_type, snr)
        self.decoder = _Decoder(c=c)

    def forward(self, x):
        z = self.encoder(x)
        if hasattr(self, 'channel') and self.channel is not None:
            z = self.channel(z)
        x_hat = self.decoder(z)
        return x_hat

    def change_channel(self, channel_type='AWGN', snr=None):
        if snr is None:
            self.channel = None
        else:
            self.channel = Channel(channel_type, snr)

    def get_channel(self):
        if hasattr(self, 'channel') and self.channel is not None:
            return self.channel.get_channel()
        return None

    def loss(self, prd, gt):
        criterion = nn.MSELoss(reduction='mean')
        return criterion(prd, gt)


def dummy_inputs(batch_size=1):
    """Provide dummy input shape for ONNX export."""
    return torch.randn(batch_size, 3, 32, 32)


if __name__ == '__main__':
    model = DeepJSCC(c=16)
    print(f"Parameters: {sum(p.numel() for p in model.parameters()):,}")
    x = torch.rand(1, 3, 32, 32)
    y = model(x)
    print(f"Input: {x.shape} → Output: {y.shape}")
    
    # Test 3D input (like ratio2filtersize)
    x3d = torch.rand(3, 32, 32)
    c = ratio2filtersize(x3d, ratio=1/6)
    print(f"ratio2filtersize(3D input) = {c}")
