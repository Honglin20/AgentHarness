# Changes from sota_8 to sota_10

## What changed
UNet architecture — narrowed channels across all encoder/decoder levels:
- Encoder: 3→**6**→**12**→**24** (was 3→8→16→32)
- Decoder: adjusted from 2c→16→32→16→3 → 2c→**12**→**24**→**12**→3
- All decoder hidden channels scaled down proportionally

## What was kept
- ✅ 3-level UNet encoder-decoder with skip connections
- ✅ Bilinear upsampling + conv (no transposed convs)
- ✅ PReLU activation
- ✅ SE channel attention at bottleneck
- ✅ Power normalization layer
- ✅ Channel layer (AWGN, SNR=7.0)
- ✅ Residual block at encoder level 3
- ✅ Input/output interface (3→32×32 → 3→32×32)

## Why this variant
Per iteration 10+ sota strategy: all 9 major SOTA templates exhausted, returning to best-performing UNet template for channel variants.
- sota_9 tried wider (10→20→40) → PSNR dropped
- sota_10 tries narrower (6→12→24) → targets latency under 0.404ms
- Params: 24,116 (was 47,232) — 49% reduction
- Expected latency: <0.38ms (should clear 0.404ms target)
- Expected PSNR: ~29-30dB (5.77dB headroom above tolerance 24.65)
