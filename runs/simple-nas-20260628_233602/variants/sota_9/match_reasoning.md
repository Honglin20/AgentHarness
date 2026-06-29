# Match Reasoning — sota_9

## SOTA Templates Tried in Previous Iterations (sota direction only)

| Iter | Template | PSNR | Latency | Status |
|------|----------|------|---------|--------|
| 0 | UNet (3→20→40→80) | 36.4 | 9.99ms | too high latency |
| 1 | DenseNet | 22.84 | 19.79ms | DEAD |
| 2 | ViT encoder + CNN decoder | 22.91 | 1.08ms | DEAD |
| 3 | MobileNetV2 (inverted residuals) | 29.45 | 0.553ms | promising |
| 4 | Swin Transformer | 28.68 | 0.598ms | not promising |
| 5 | Linear Attention (Performer) | 31.04 | 0.711ms | promising |
| 6 | ResNet Bottleneck | 30.79 | 0.564ms | promising |
| 7 | Mamba/SSM | 29.78 | 1.603ms | high latency |
| 8 | UNet lightweight (3→8→16→32) | 30.42 | 0.4075ms | BEST efficiency |

## Template Selection (Iter 9): UNet Variant — Wider Channels 10→20→40

**Priority**: 第8次+ — 回到最佳模板做变体

**Selected template**: UNet variant with scaled-up channels (10→20→40 vs parent 8→16→32)

**Rationale**:
1. UNet is the best-performing SOTA template for this image-to-image reconstruction task in both iterations (iter 0: +11.5dB, iter 8: triple win)
2. All other major templates have been tried (DenseNet, ViT, MobileNetV2, Swin, Linear Attention, ResNet Bottleneck, Mamba)
3. Per the轮转策略: after all major templates are tried, go back to best-performing ones for variants
4. The lightweight UNet (8→16→32) achieved excellent latency (0.4075ms, only 3.5μs from target) with PSNR=30.42
5. Scaling channels to 10→20→40 (+25% width at each level) should improve PSNR while keeping latency close to target
6. This avoids the extreme of sota_0 (20→40→80, lat=9.99ms) while offering capacity headroom over sota_8

**Expected trade-off**:
- PSNR improvement: ~+0.5 to +1.5dB over sota_8 (30.42dB)
- Latency increase: ~+20-40% from 0.4075ms → ~0.49-0.57ms (still within reasonable range)
- Parameter increase: from 47K to ~73K (still very compact)

**Preserved task-specific components**:
- ✅ Channel layer (AWGN noise simulation)
- ✅ Power normalization
- ✅ Sigmoid output (image pixel range [0,1])
- ✅ Input/output interface unchanged
