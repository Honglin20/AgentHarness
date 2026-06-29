# structural_4

## Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K)
- **Encoder conv1**: 3→16 → 3→20 (wider input stage, +108 params)
- **Decoder conv4**: adjusted from 48→16 to 52→20 (matches wider skip connection from conv1)
- **Decoder conv5**: adjusted from 16→3 to 20→3 (wider features before output)
- **Encoder conv2**: adjusted from 16→32 to 20→32 (+1,152 params)

All other elements preserved: U-Net skip connection, bilinear upsample+3×3 conv decoder,
3 encoder residual blocks, SE at bottleneck, PReLU activations.

Total params: 109,060 (+3.6%). Latency: 0.475ms (+14.5%). PSNR: 29.15 dB (-0.44%).
