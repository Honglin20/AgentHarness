import torch
import torch.nn as nn

class Channel(nn.Module):
    """Channel module — patched copy with no .square() for ONNX compatibility."""

    def __init__(self, channel_type="AWGN", snr=None):
        super().__init__()
        self.channel_type = channel_type
        self.snr = snr

    def forward(self, z_hat):
        if self.channel_type == "AWGN":
            if z_hat.dim() == 4:
                k = torch.prod(torch.tensor(z_hat.size()[1:]))
            elif z_hat.dim() == 3:
                k = torch.prod(torch.tensor(z_hat.size()))
            else:
                raise Exception("Unknown size of input")
            # Signal power (use * instead of .square() for ONNX compat)
            sig_pwr = torch.sum(torch.abs(z_hat) * torch.abs(z_hat),
                                dim=(1, 2, 3), keepdim=True) / k
            snr_linear = 10.0 ** (self.snr / 10.0)
            noise_pwr = sig_pwr / snr_linear
            noise = torch.sqrt(noise_pwr) * torch.randn_like(z_hat)
            return z_hat + noise
        elif self.channel_type == "Rayleigh":
            h = torch.randn_like(z_hat)
            return h * z_hat
        else:
            raise ValueError(f"Unknown channel type: {self.channel_type}")
