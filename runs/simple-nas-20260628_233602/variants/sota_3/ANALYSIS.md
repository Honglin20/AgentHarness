# SOTA v3 Analysis — MobileNetV2 Inverted Residuals

## Summary

| Metric | parent (structural_1) | sota_3 (this) | Δ |
|--------|----------------------|---------------|----|
| PSNR (dB) | 29.28 | 29.45 | **+0.17** ✅ |
| Latency (ms) | 0.415 | 0.553 | **+33%** ❌ |
| Params | 105,236 | 61,859 | **−41%** ✅ |

## Template: MobileNetV2 (Inverted Residuals)

**Rotation position**: 4th SOTA template (following UNet→DenseNet→ViT)

### What was implemented
- 3 MobileNetV2-style `_InvertedResidual` blocks in the encoder (replacing `conv2` + 3 residual blocks)
- Expansion factor=3: each block does `1×1 (expand)` → `Depthwise 3×3` → `1×1 (project)`
- Residual connections where stride=1 & in/out channels match
- Kept U-Net skip connection, power norm, SE bottleneck, Channel layer, decoder unchanged

### Result interpretation

**PSNR**: Slight improvement (+0.17dB) despite 41% fewer parameters. The InvertedResidual blocks with expansion=3 provide reasonable representational capacity even at lower parameter count. Loss curve shows continued improvement at epoch 5 (not converged).

**Latency**: Increased 33% from 0.415ms to 0.553ms. This confirms the DSConv CPU bandwidth issue seen in structural_2. The expansion 1×1 + depthwise 3×3 + projection 1×1 pattern adds extra convolution passes that don't benefit from CPU cache locality. The parent's plain 3×3 convs are more CPU-friendly despite more parameters.

**Params**: 41% reduction (105K→62K) is significant. The depthwise separable ops drastically reduce weight count.

### Comparison with previous SOTA attempts

| Iter | Template | PSNR | Latency | Params | Verdict |
|------|----------|------|---------|--------|---------|
| 0 | UNet | 36.4 | 9.99ms | 187K | Promising (too slow) |
| 1 | DenseNet | 22.84 | 19.79ms | 163K | Dead (diverged) |
| 2 | ViT | 22.91 | 1.08ms | 242K | Dead (not converge) |
| 3 | MobileNetV2 | 29.45 | 0.553ms | 62K | **Neutral** |

### Conclusion
**Neutral** — PSNR maintained (+0.17dB) with −41% params, but latency regressed +33%. The MobileNetV2 approach does not help CPU latency despite parameter reduction, confirming that depthwise convolutions are not CPU-friendly on this platform. If going forward, consider:
- Using expansion=1 (just depthwise + 1×1) to reduce computation
- Or abandon depthwise approaches on CPU and focus on smaller plain convs
- The structural_1 parent (0.415ms) remains the latency leader
