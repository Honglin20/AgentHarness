# SOTA Analysis: sota_4 — Swin-inspired Window Attention Encoder

## Template
**Swin Transformer** (lightweight variant) — 5th sota attempt per rotation

## Match Reasoning
- This is the 5th sota attempt: UNet(iter 0)→DenseNet(iter 1)→ViT(iter 2)→MobileNetV2(iter 3)→Swin(iter 4)
- Swin-style window attention captures local detail (window-level) while maintaining cross-window communication
- Only applied at 8×8 bottleneck (64 tokens, 4 windows of 4×4), keeping compute cheap
- Keeps structural_1's successful decoder and U-Net skip connections

## Results vs Parent (structural_1, PSNR=29.28, lat=0.415ms, params=105K)

| Metric | Parent | sota_4 | Change |
|--------|--------|--------|--------|
| PSNR (dB) | 29.28 | 28.68 | −0.60 (−2.0%) |
| Latency (ms) | 0.415 | 0.598 | +0.183 (+44%) |
| Params | 105,236 | 49,802 | −55,434 (−52.7%) |

## Analysis

### What Worked
1. **Parameter efficiency**: 49.8K params is by far the smallest model tried so far. The window attention + MLP adds only ~12K params but provides meaningful feature refinement.
2. **Competitive PSNR**: 28.68 dB is within 2% of parent despite having 53% fewer parameters. The attention mechanism effectively compensates for reduced channel capacity.
3. **Stable training**: Loss curve drops smoothly (536→93), no divergence like DenseNet or ViT earlier.
4. **Underfitting still**: Loss at epoch 5 is still dropping rapidly, suggesting more epochs would close the PSNR gap.

### What Didn't
1. **Latency regression**: +44% vs parent (0.598 vs 0.415ms). The window partition/merge + attention adds CPU overhead despite fewer params. The reshape operations (view, permute) are not free on CPU.
2. **PSNR gap**: −0.60 dB vs parent. The attention mechanism doesn't fully compensate for halving the channel count in the encoder.

### Comparison with Other SOTA Attempts
- **sota_0 (UNet)**: PSNR=36.4 (best ever) but latency=9.99ms. Our approach is much more latency-efficient.
- **sota_3 (MobileNetV2)**: PSNR=29.45, params=61.9K, lat=0.553ms. Our approach has fewer params (49.8K) but higher latency (0.598ms), confirming DSConv is CPU-friendly but attention is not.
- **sota_1 (DenseNet)**: Diverged. Our approach is stable and converges well.

## Verdict
**Promising (conditional)** — The Swin-inspired attention achieves competitive PSNR with minimal parameters. The key trade-off is params↓ vs latency↑. If latency is the primary concern (target 0.404ms), this variant doesn't improve over structural_1. However, it demonstrates that attention-based feature refinement works for this task, and could be further optimized (e.g., removing the MLP, using single-head attention) to reduce latency.

## Next Step Suggestions
- Remove the MLP after attention (keep only attention + residual) to lower latency
- Reduce num_heads from 4→1 to lower attention overhead
- Experiment with attention only in the decoder (not encoder) — decoder has larger feature maps
- Combine with hyperparam tuning (hyperparam_2's best config: Adam+StepLR, wd=1e-4, batch=32)
