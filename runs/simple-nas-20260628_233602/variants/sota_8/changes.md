# SOTA Variant sota_8 — Lightweight UNet

## What changed

Replaced the parent's 2-level encoder-decoder (with 1 skip connection) with a
**full 3-level Lightweight UNet** architecture inspired by the iter 0 UNet
(sota_0: psnr=36.4dB) but with heavily reduced channels for latency control.

### Architecture comparison

| Component | Parent (structural_1) | This variant (sota_8) |
|-----------|----------------------|----------------------|
| Encoder levels | 2 levels (16→32ch) | 3 levels (8→16→32ch) |
| Skip connections | 1 skip (level 1→decoder) | 2 skips (all levels→decoder) |
| Decoder | 3 convs + upsample ×2 | 1 conv + upsample×2 + conv + upsample×2 + out |
| Channels | 16→32 (encoder), 2c→32→16→3 (decoder) | 8→16→32 (encoder), 2c→32→16→24→3 (decoder) |
| Residual blocks | 3× (32ch) | 1× (32ch) |
| Attention | SE at bottleneck (2c≥8) | SE at bottleneck (2c≥8) |
| Power norm | Yes | Yes (preserved) |
| Channel layer | Yes (AWGN) | Yes (preserved) |

### Design rationale

1. **Channel reduction**: 8→16→32 vs parent's 16→32 and original UNet's 20→40→80.
   Tiny channels keep params low (~50K estimated) while UNet's multi-scale skip
   connections provide rich feature reuse.

2. **Full 3-level UNet**: Unlike parent which only bridges level-1 skip to decoder,
   this variant connects both level-1 and level-2 features to the corresponding
   decoder levels — giving the decoder access to fine spatial details at every scale.

3. **Preserved successful patterns**: Bilinear upsampling+conv (not tconvs), PReLU
   activations, SE attention, power normalization, Channel layer.

## Match reasoning
- UNet is the most natural template for image-to-image reconstruction
- sota_0 showed UNet achieves psnr=36.4 but was crippled by latency (9.99ms)
- Reducing channels from 20→40→80 to 8→16→32 should bring latency under control
  while retaining multi-scale reconstruction quality
