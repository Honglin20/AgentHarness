# Match Reasoning — iter 8

## Template Rotation Status

All 8 major SOTA templates have been tried across iter 0-7:

| Iter | Template | Result |
|------|----------|--------|
| 0 | UNet (20→40→80ch) | Promising: psnr=36.4, lat=9.99ms |
| 1 | DenseNet | Dead: psnr=22.84, lat=19.79ms |
| 2 | ViT | Dead: psnr=22.91, lat=1.08ms |
| 3 | MobileNetV2 | Promising: psnr=29.45, lat=0.553ms |
| 4 | Swin Transformer | Not promising: psnr=28.68, lat=0.598ms |
| 5 | Linear Attention | Promising: psnr=31.04, lat=0.711ms |
| 6 | ResNet Bottleneck | Promising: psnr=30.79, lat=0.564ms |
| 7 | Mamba/SSM | Promising but costly: psnr=29.78, lat=1.603ms |

Per rotation strategy: **"第8次+: 回到 UNet/ViT 做变体"** — revisiting the most successful template.

## Template Selection

**Template 1: Lightweight UNet (3 levels, small channels 8→16→32)**
- Reason: UNet was the #1 SOTA performer (psnr=36.4dB) but latency was crippling (9.99ms) due to 20→40→80 channels
- Optimization: Reduce channels to 8→16→32 (~40% of original), keep 3-level encoder-decoder with full skip connections
- Expected: Lower params and latency while retaining UNet's multi-scale reconstruction advantage
- Key idea: The parent structural_1 already has 1 skip connection; a full 3-level UNet provides richer multi-scale features

**Template 2: EfficientNet-style MBConv encoder blocks**
- Reason: EfficientNet-style inverted residual blocks (1×1 expansion → 3×3 depthwise → 1×1 projection) haven't been tried specifically
- Difference from MobileNetV2 (iter 3): Different expansion ratio config, stronger SE integration, optimized for channel scaling
- Expected: Good parameter efficiency with potential for high quality reconstruction

## Task Match Assessment

- Image-to-image reconstruction → UNet family is the most natural match
- Task-specific components preserved: Channel layer, power normalization, c from ratio2filtersize
- Input/output shapes unchanged: [B,3,32,32] → [B,3,32,32]
