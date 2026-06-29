# Changes from parent (structural_1)

## Architecture change: ResNet Bottleneck Enhancement

### What changed
1. **`_ResidualBlock` → `_BottleneckBlock`**: 
   - Old: two 3x3 convs with identity skip (params: 2×3×3×C×C = 18C²)
   - New: 1x1 reduce → 3x3 → 1x1 expand with identity skip (params: 1×1×C×C/4 + 3×3×C/4×C/4 + 1×1×C/4×C ≈ 1.125C²)
   - ~16x fewer params per block, allowing more depth

2. **More blocks**: 3 → 4 bottleneck blocks in encoder (deeper but each cheaper)

3. **No other changes**: U-Net skip connection, SE attention, bilinear upsampling,
   Channel layer, power normalization all preserved.

### Rationale
ResNet bottlenecks are the standard way to build very deep networks efficiently.
The bottleneck structure learns a compressed representation (C/4) then expands back,
acting as a learned autoencoder within each block. This improves gradient flow
through the deeper network while keeping total compute low.
