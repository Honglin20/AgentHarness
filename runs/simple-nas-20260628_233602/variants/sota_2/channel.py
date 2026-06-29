import torch
import torch.nn as nn


class Channel(nn.Module):
    """Fixed version: avoids .square() for ONNX compatibility with PyTorch 1.7."""

    def __init__(self, channel_type='AWGN', snr=20):
        if channel_type not in ['AWGN', 'Rayleigh']:
            raise Exception('Unknown type of channel')
        super(Channel, self).__init__()
        self.channel_type = channel_type
        self.snr = snr

    def forward(self, z_hat):
        if z_hat.dim() not in {3, 4}:
            raise ValueError('Input tensor must be 3D or 4D')

        if z_hat.dim() == 3:
            z_hat = z_hat.unsqueeze(0)

        k = z_hat[0].numel()
        # Use mul instead of .square() for ONNX compat with PyTorch 1.7
        sig_pwr = torch.sum(z_hat * z_hat, dim=(1, 2, 3), keepdim=True) / k
        noi_pwr = sig_pwr / (10 ** (self.snr / 10))
        noise = torch.randn_like(z_hat) * torch.sqrt(noi_pwr / 2)

        if self.channel_type == 'Rayleigh':
            hc = torch.randn(2, device=z_hat.device)
            z_hat = z_hat.clone()
            z_hat[:, :z_hat.size(1) // 2] = hc[0] * z_hat[:, :z_hat.size(1) // 2]
            z_hat[:, z_hat.size(1) // 2:] = hc[1] * z_hat[:, z_hat.size(1) // 2:]

        return z_hat + noise

    def get_channel(self):
        return self.channel_type, self.snr
