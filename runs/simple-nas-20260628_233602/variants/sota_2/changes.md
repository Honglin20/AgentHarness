# Changes: ViT Encoder + CNN Decoder

## What Changed

### Encoder: CNN → ViT (Vision Transformer)
- **Removed**: All CNN encoder layers (conv1-2, residual blocks, conv5)
- **Added**: ViTEncoder with:
  - Patch embedding: Conv2d(3→64, kernel=4, stride=4) → 8×8 patch grid (64 patches)
  - Learnable position embedding (1×64×64)
  - 4× Transformer blocks (LayerNorm + MultiHeadAttention 4-head + MLP 64→256→64)
  - Output projection: embed_dim(64) → bottleneck(2*c=32)
  - Power normalization kept from parent

### Decoder: CNN (adapted from parent)
- **Removed**: U-Net skip connection path (ViT doesn't produce multi-scale features)
- **Changed**: conv4 in_channels from 48→32 (no longer concatenating skip features)
- **Kept**: Bilinear upsampling + 3×3 convs (efficient decoder design)

### Unchanged
- `Channel` layer (AWGN, SNR=7.0)
- Power normalization (`_normlizationLayer`)
- `DeepJSCC` class interface (forward, change_channel, loss, dummy_inputs)
- `ratio2filtersize` function (ViTEncoder supports is_temp=True)

## Why ViT Encoder

1. **Global context**: Self-attention captures long-range spatial dependencies that CNN convs miss — critical for efficient image compression through a tight bottleneck (32×8×8=2048 values).
2. **SOTA precedent**: Hybrid ViT-CNN architectures dominate image restoration benchmarks.
3. **Lightweight**: Only 64 tokens with embed_dim=64 and 4 heads → manageable compute.
4. **New direction**: Previous SOTA attempts were UNet (dense local) and DenseNet (deep local). ViT explores global attention.

## Estimated Params
- Patch embed: ~3K
- Position embed: ~4K
- Transformer blocks (4×): ~200K
- Output proj: ~2K
- Decoder: ~30K
- **Total**: ~239K (≈2.3× parent 105K — within 5× limit)
