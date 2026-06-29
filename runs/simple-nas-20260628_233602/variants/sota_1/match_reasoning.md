# SOTA Template Matching: iter 1

## Selected Template: **DenseNet-style Dense Connections** (CNN Variant)

### Matching Analysis

| Factor | Current (structural_0 parent) | DenseNet match reason |
|--------|------------------------------|-----------------------|
| Task type | Image-to-image reconstruction | DenseNet's feature reuse is ideal for reconstruction tasks where both low- and high-level features matter |
| Architecture | CNN encoder-decoder with 2 residual blocks in encoder + SE attention | DenseNet's dense connectivity (each layer gets all prev features) is a more thorough form of feature reuse than 2 residual blocks |
| Input shape | [B, 3, 32, 32] | DenseNet handles any image size |
| Output shape | [B, 3, 32, 32] | Matches exactly |
| Current feature reuse | 2 residual blocks only in encoder (conv3/conv4 stage); decoder has zero residual connections | DenseNet provides feature reuse in BOTH encoder and decoder, at ALL layers |
| Current bottleneck | SE attention at bottleneck (channels only) | DenseNet's dense connections naturally enhance gradient flow without needing explicit attention modules |

### Why DenseNet Specifically (vs UNet already tried)

1. **Different mechanism from UNet**: UNet uses spatial skip connections (encoder→decoder same-level). DenseNet uses dense within-block connections (every layer to every later layer). These are complementary — UNet solves the spatial information bottleneck, DenseNet solves the feature reuse bottleneck.

2. **Addresses baseline_understanding bottleneck**: "No residual connections — plain feedforward stack." While structural_0 added 2 residual blocks, DenseNet goes much further with dense connectivity at every layer.

3. **Better gradient flow**: DenseNet's dense connections provide shortcut paths for gradients to flow from the decoder output all the way back to early encoder layers, enabling more effective training.

4. **Parameter efficiency**: DenseNet uses narrow growth rates (e.g., 12 channels per layer) and reuses features through concatenation, making it parameter-efficient compared to widening architectures.

5. **Latency consideration**: Uses 3×3 convs and upsample+conv (no transposed convs), keeping latency lower than the UNet variant which had 9.99ms.

### Not Selected This Iteration
- UNet: Already tried in iter 0 (PSNR=36.4, latency=9.99ms)
- ViT: Reserved for future iteration (needs more data or better suited for later exploration)
- MobileNet: Reserved for lightweight exploration after dense connectivity is benchmarked
- Mamba/SSM: Novel but high implementation risk for first SOTA iteration
