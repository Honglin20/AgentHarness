# Structural Changes v0.3

## What changed (vs baseline v0)
1. **Encoder conv3 & conv4 → 3×3 residual blocks**: Replaced two 5×5 plain convs with two 3×3+3×3 residual blocks. Same receptive field, ~28% fewer weights per block, better gradient flow via skip connections.
2. **SE block at bottleneck**: Added Squeeze-and-Excitation channel attention after normalization (reduction=8). Only ~292 extra parameters but provides adaptive channel recalibration.
3. **Decoder residual connection**: Added skip connection from encoder bottleneck output to the decoder body (after tconv3), allowing the decoder to directly access bottleneck features.

## What was kept from baseline
- All ConvTranspose2d layers preserved (no upconv replacement — avoids latency increase from upsample+conv on larger feature maps)
- Normalization, channel model, loss function unchanged

## Expected impact
- PSNR: should improve due to better gradient flow (residuals) + channel attention (SE)
- Latency: should be near baseline (only adds element-wise additions + tiny SE linear layers)
- Params: ~158,928 (vs 181,865 baseline)
