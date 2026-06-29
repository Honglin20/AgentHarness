# Match Reasoning: ViT Encoder + CNN Decoder

## Why ViT Encoder + CNN Decoder?

### Task Analysis
- **Task**: Image-to-image reconstruction (Deep-JSCC for wireless image transmission)
- **Input**: 3×32×32 (CIFAR-like images)
- **Output**: 3×32×32 (reconstructed images)
- **Current Parent**: structural_1 (CNN encoder with residual blocks + bilinear upsample decoder, PSNR=29.28, latency=0.415ms)

### Why This Template Fits
1. **Hybrid ViT-CNN architectures** are SOTA for image restoration tasks (e.g., SwinIR, Restormer). The ViT encoder captures **global context** through self-attention, which is critical for wireless channel coding where the bottleneck (32×8×8=2,048 values for 3,072 pixels) requires efficient compression of global structure.

2. **Previous attempts compared**:
   - sota_0 (UNet): PSNR=36.4 but latency=9.99ms — excellent PSNR but too slow
   - sota_1 (DenseNet): PSNR=22.84, diverged — unstable without BN
   
3. **ViT advantage**: Unlike UNet's local feature processing, ViT's self-attention can model long-range dependencies in the spatial domain, which helps the encoder allocate bits more efficiently to important image regions.

4. **Latency consideration**: With patch_size=4, the ViT processes 64 tokens — this is lightweight enough to keep latency reasonable while adding global reasoning capability.

### Template Mapping
| Template Component | Implementation |
|-------------------|---------------|
| PatchEmbedding | Conv2d(3→64, kernel=4, stride=4) → 8×8 grid, 64 patches |
| Position Embedding | Learnable 1×64×64 |
| Transformer Blocks | 4 blocks, each: LayerNorm + MHA(4 heads, 64dim) + MLP(64→256→64) |
| Output Projection | Linear(64→2c) to match bottleneck (32 channels) |
| Normalization | Power normalization (kept from parent) |
| Channel | AWGN (kept from parent) |
| Decoder | CNN decoder from parent (bilinear upsample + 3×3 convs) |

### Expected Trade-offs
- **PSNR**: ViT's global attention should improve compression efficiency → expected +1~3dB vs parent
- **Latency**: Transformer adds overhead vs pure CNN, but with only 4 blocks × 64 tokens it stays manageable
- **Params**: ~170K (within 2× of parent 105K)
