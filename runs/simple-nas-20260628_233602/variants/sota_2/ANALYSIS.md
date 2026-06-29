# SOTA Variant Analysis: ViT Encoder + CNN Decoder

## Template Used
**ViT Encoder + CNN Decoder** (priority #3 in rotation — after UNet in iter 0, DenseNet in iter 1)

## Match Reasoning
The task is image-to-image reconstruction (3×32×32 → 3×32×32) with a tight bottleneck. ViT's global self-attention captures long-range spatial dependencies that pure CNN encoders miss, which is theoretically beneficial for efficient compression through the bottleneck.

## Results vs Parent (structural_1)

| Metric | Parent (structural_1) | SOTA (ViT) | Delta |
|--------|----------------------|------------|-------|
| PSNR (dB) | 29.28 | 22.91 | **−6.37** |
| Latency (ms) | 0.415 | 1.080 | **+160%** |
| Params | 105,236 | 242,183 | **+130%** |

## Analysis

### Why PSNR Dropped
1. **Insufficient training**: CIFAR-10 at 32×32 is small for ViT (64 patches), but ViTs typically need more epochs to converge than CNNs. With only 5 epochs, the transformer blocks haven't learned meaningful attention patterns.
2. **Training instability**: The PSNR curve peaked at epoch 3 (22.91) then declined, suggesting the learning rate (1e-3) may be too high for the ViT's Adam-based optimization.
3. **No skip connections**: Unlike the parent (which has U-Net skip from encoder conv1 to decoder), the ViT encoder produces single-scale features, denying the decoder access to fine-grained spatial details.

### Why Latency Increased
1. **Self-attention overhead**: Even with only 64 tokens, the QKV projections and attention matrix multiply (64×64) add latency versus the pure-CNN encoder.
2. **More parameters**: 242K vs 105K — the transformer blocks dominate encoder compute.

### Comparison with Previous SOTA Attempts
| Iter | Template | PSNR | Latency | Params | Verdict |
|------|----------|------|---------|--------|---------|
| 0 | UNet | 36.4 | 9.99ms | 187K | Promising (high PSNR) |
| 1 | DenseNet | 22.84 | 19.79ms | 163K | Dead (diverged) |
| **2** | **ViT encoder** | **22.91** | **1.08ms** | **242K** | **Underperforming** |

## Conclusion
The ViT encoder hybrid approach underperforms on this 5-epoch CIFAR-10 task. ViTs typically need 10× more epochs to converge than CNNs. **Not promising** for the short-training NAS setting. For future SOTA iterations, consider:
- **MobileNet-style depthwise separable convs** (lightweight, good for latency)
- **Swin Transformer** (window attention reduces compute, local+global features)
- Or go back to UNet with reduced channel count (sota_0 had 36.4 PSNR but 9.99ms latency — a lighter UNet could balance quality and speed)
