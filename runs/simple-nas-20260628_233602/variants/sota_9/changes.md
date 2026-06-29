# Changes: sota_9 — UNet with Wider Channels (10→20→40)

## What Changed vs Parent (sota_8: 8→16→32)

### Encoder
| Component | sota_8 (parent) | sota_9 (this) | Change |
|-----------|-----------------|---------------|--------|
| conv1 | 3→8, s2 | 3→10, s2 | +25% width |
| conv2 | 8→16, s2 | 10→20, s2 | +25% width |
| conv3 | 16→32, s1 | 20→40, s1 | +25% width |
| res_block | 32ch (3×3×2) | 40ch (3×3×2) | +25% width |
| conv5 | 32→2c, s1 | 40→2c, s1 | wider input |

### Decoder
| Component | sota_8 (parent) | sota_9 (this) | Change |
|-----------|-----------------|---------------|--------|
| conv_d3a | 2c→16 | 2c→20 | wider intermediate |
| conv_d3b | 32→16 (16+16) | 40→20 (20+20) | wider skip fusion |
| conv_d2 | 24→16 (16+8) | 30→20 (20+10) | wider skip fusion |
| conv_out | 16→3 | 20→3 | wider final layer |

## Rationale
- UNet is the best SOTA template for image-to-image reconstruction
- sota_8 achieved excellent latency (0.4075ms, only 3.5μs from target)
- Moderate channel scaling (+25%) should improve PSNR while keeping latency near target
- This avoids the extreme jump to sota_0's 20→40→80 (lat=9.99ms)

## Preserved Components
- ✅ Channel layer (AWGN noise simulation)
- ✅ Power normalization
- ✅ PReLU activation, Kaiming init
- ✅ SE attention at bottleneck
- ✅ Bilinear upsampling + conv (no transposed convs)
- ✅ Sigmoid output
- ✅ Input/output interface unchanged
