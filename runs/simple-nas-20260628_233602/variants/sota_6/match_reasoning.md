# SOTA variant iter 6: ResNet Bottleneck Enhancement

## Template selected: ResNet (Bottleneck Residual Blocks)

### Why this template
1. **Untried** — All previous SOTA templates have been tried (UNet, DenseNet, ViT, MobileNetV2, Swin, Linear Attention). ResNet bottleneck enhancement is the most promising untried template.
2. **CPU-friendly** — Only uses regular convolutions (no depthwise separable which was slow on CPU in iter 2/3; no attention which was slow in iter 4/5).
3. **Natural progression** — Parent structural_1 already has `_ResidualBlock` (two 3x3 convs). Upgrading to bottleneck blocks (1x1→3x3→1x1) adds more depth with fewer parameters.
4. **Latency-aware** — Bottleneck design reduces FLOPs vs two 3x3 convs. Should keep latency close to target 0.404ms.

### Changes from parent (structural_1)
1. Replace `_ResidualBlock` (two 3x3 convs) with `_BottleneckBlock` (1x1→3x3→1x1, bottleneck ratio=4)
2. Increase from 3 residual blocks to 4 (deeper but each block is cheaper)
3. Keep all other components: U-Net skip, SE attention, bilinear upsampling, Channel layer

### Expected impact
- Params: slightly fewer (~95K vs 105K) due to bottleneck efficiency
- Latency: similar or slightly lower (~0.40-0.45ms)
- PSNR: modest improvement (+0.5-1.5dB) from better gradient flow
