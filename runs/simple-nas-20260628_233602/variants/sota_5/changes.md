# Changes — sota_5 (Linear Attention at Bottleneck)

## What changed
Added Performer-style Linear Attention (ELU+1 feature map) at the encoder bottleneck of structural_1.

## Architecture diff vs structural_1 (parent)
- **NEW**: `_LinearAttention` module (dim=32, heads=4) between res_blocks and conv5
- **NEW**: `LayerNorm` for per-position normalization before attention
- **NEW**: Residual connection around attention block
- Everything else: identical to structural_1 (3×3 convs, residual blocks, SE attention,
  U-Net skip connections, bilinear upsampling decoder, Channel module)

## Why Linear Attention
- SE attention (already present in parent) does **channel-wise** weighting
- Linear attention does **spatial** mixing — which positions matter for reconstruction
- Together they complement each other: channel attention + spatial attention
- O(n*d) complexity vs O(n²): at 8×8 bottleneck (n=64), performance cost is minimal
- ELU+1 feature map ensures positive values, avoiding softmax saturation
- Previous attention attempts (ViT iter 2, Swin iter 4) used O(n²) softmax attention
  and struggled with 5-epoch convergence — linear attention's simpler formulation
  with residual connection should train more stably

## Parameter impact
- Parent (structural_1): 105,236 params
- Sota_5: 109,396 params (+4,160 = +3.95%)
- Additional params from: to_qkv (32→48, 1×1), to_out (48→32, 1×1), LayerNorm (64)
- Well within the 5× limit

## Conservative approach
This is a minimal, safe addition to the proven structural_1 backbone:
- No change to the successful 3×3 conv + residual block + bilinear upsampling pipeline
- No change to U-Net skip connections (proven effective from iter 0 UNet)
- No change to task-specific components (Channel, power norm, Sigmoid)
- Residual connection around attention ensures training stability
