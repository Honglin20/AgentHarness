# Changes in sota_4 (Swin Transformer Encoder)

## What Changed
1. **Encoder**: Replaced CNN residual blocks + conv5 with Swin Transformer blocks
   - Keep conv1 (3→16, 3×3 stride 2) for U-Net skip features (unchanged)
   - Keep conv2 (16→32, 3×3 stride 2) for downsampling to 8×8 (unchanged)
   - Removed: res_block1, res_block2, res_block3 (3 residual blocks, 32ch)
   - Added: _SwinBasicLayer with 2 Swin blocks (window_size=4, num_heads=4)
   - Added: LayerNorm after Swin
   - Changed: conv5 from 3×3 to 1×1 (pointwise, since features are already processed)
   - Added: residual connection (Swin output + conv2 output) for training stability

2. **Decoder**: Unchanged from structural_1
   - bilinear upsampling + 3×3 convs
   - U-Net skip connections (concatenate skip1 from conv1)
   - residual connection in decoder

3. **Task-specific components**: Unchanged
   - Power normalization (_normlizationLayer)
   - Channel layer (AWGN)
   - DeepJSCC wrapper interface

## Why Swin Transformer
- Shifted window attention captures both local detail (window-level) and global context (via shifting)
- Hierarchical: 32×32 → 16×16 (conv1) → 8×8 (conv2) → Swin processing matches Deep-JSCC pyramid
- Window-based attention is more efficient than full ViT (O(N×W²) vs O(N²))
- Local attention converges faster in few epochs (addressing ViT's failure in iter 2)
- Only 64 tokens at 8×8 resolution, window_size=4 → 4 windows of 16 tokens → very cheap

## Expected Impact
- **PSNR**: Target ≥29.5 (Swin's local+global should improve reconstruction quality)
- **Latency**: Target ≤0.5ms (Swin on 64 tokens is negligible; main cost is conv layers)
- **Params**: ~100-110K (similar to structural_1's 105K; Swin blocks add ~20K params but conv5 is 1×1)
