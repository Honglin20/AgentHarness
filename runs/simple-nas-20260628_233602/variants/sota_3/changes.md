# Changes from structural_1 (parent) to sota_3

## What changed

### Encoder: CNN → MobileNetV2 Inverted Residuals

**Before (structural_1):**
```
conv1 (3→16, 3×3 s2) → conv2 (16→32, 3×3 s2) → res_block1 → res_block2 → res_block3 → conv5 (32→2c) → norm → SE
```

**After (sota_3):**
```
conv1 (3→16, 3×3 s2) → mb_block1 (16→32, s2, expand=3) → mb_block2 (32→32, s1, expand=3) → mb_block3 (32→32, s1, expand=3) → conv5 (32→2c) → norm → SE
```

### MobileNetV2 InvertedResidual block
Each block = `Conv2d 1×1 (expand)` → `Depthwise Conv2d 3×3` → `Conv2d 1×1 (project)`
- Expansion factor=3: hidden channels = in_channels × 3
- Residual connection when stride=1 and in/out channels match
- No activation after projection (per MobileNetV2 paper)

### What stayed the same
1. `conv1` (3→16, stride 2) — kept identical for U-Net skip connection compatibility
2. Decoder — same bilinear upsampling + 3×3 conv structure (proven efficient)
3. U-Net skip connection (conv1 output → decoder concat at 16×16)
4. Power normalization layer
5. Channel layer (AWGN)
6. SEBlock at bottleneck (unchanged)

## Why MobileNetV2
- **4th SOTA template** per rotation strategy (MobileNet 轻量化)
- Parent latency (0.415ms) is very close to target (0.404ms) — MobileNet's depthwise ops can shave off the last microseconds
- Previous DSConv attempt (structural_2) failed on CPU due to pure DSConv overhead — MobileNetV2's expansion→projection structure gives more computation per depthwise op, potentially better utilizing CPU cache
- expansion=3 (vs 6) keeps computation in check
