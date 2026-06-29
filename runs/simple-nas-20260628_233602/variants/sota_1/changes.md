# Changes: SOTA Variant iter 1 — DenseNet Architecture

## What Changed

### Architecture: Residual-enhanced CNN Encoder-Decoder → DenseNet-style Dense Connectivity

**Old (structural_0 parent):**
- Encoder: CNN with 2 residual blocks (3×3 convs) at conv3/conv4 stage, SE attention at bottleneck
- Decoder: 5× ConvTranspose2D (5×5), with a skip from encoder bottleneck
- Power normalization at encoder output

**New (DenseNet):**
- Encoder: 
  - Initial 5×5 conv (3→32, stride 2)
  - DenseBlock1: 4 dense layers, growth_rate=12 (32→80 channels)
  - Transition1: 1×1 conv (80→48) + 2×2 avg pool
  - DenseBlock2: 4 dense layers, growth_rate=12 (48→96 channels)
  - Bottleneck: 3×3 conv (96→2c)
  - Power normalization

- Decoder:
  - Initial 3×3 conv (2c→48)
  - DenseBlock3: 4 dense layers, growth_rate=12 (48→96)
  - Upsample 2× (bilinear) + 1×1 conv (96→32)
  - DenseBlock4: 4 dense layers, growth_rate=12 (32→80)
  - Upsample 2× (bilinear) + 1×1 conv (80→16)
  - DenseBlock5: 3 dense layers, growth_rate=12 (16→52)
  - Output: 3×3 conv (52→3) + Sigmoid

**Preserved (unchanged):** Channel layer, power normalization, input/output interface (DeepJSCC class), loss function, dummy_inputs

## Rationale

1. **Dense connectivity maxes feature reuse**: Each DenseBlock layer concatenates ALL previous outputs, making every layer receive all features from earlier layers. This is more thorough than the 2 residual blocks in structural_0.

2. **Bypasses computation hotspots**: Replaces all 5×5 transposed convs (identified as computation hotspot) with upsample + conv. Uses 3×3 convs throughout (vs 5×5 in parent).

3. **Parameter efficient**: 163K params (vs parent 167K) despite having 4× DenseBlocks with 4 layers each. The narrow growth rate (12) keeps params low.

4. **Gradient flow**: Dense connections provide shortcut paths for gradients from decoder output to early encoder layers.

5. **Latency goal**: Interpolation+conv instead of tconv should keep latency lower than UNet variant (9.99ms).

## Expected Benefits
- Higher PSNR from better feature reuse (but may not match UNet's 36.4 dB)
- Lower latency than UNet variant due to simpler operations
- Better gradient flow during training
