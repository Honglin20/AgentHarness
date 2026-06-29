# Match Reasoning — iter 5 (sota_5)

## Template Selected: Linear Attention / Performer (rotation #6)

### Why this template
Per the rotation strategy, we have tried:
1. UNet (iter 0) — PSNR=36.4, latency=9.99ms (promising)
2. DenseNet (iter 1) — PSNR=22.84, dead
3. ViT encoder (iter 2) — PSNR=22.91, dead
4. MobileNetV2 (iter 3) — PSNR=29.45, latency=0.553ms (promising)
5. Swin Transformer (iter 4) — PSNR=28.68, latency=0.598ms (not promising)
6. **Linear Attention / Performer ← THIS (not yet tried)**

### Task match
- **Input**: [B,3,32,32] images → encoder produces 32ch 8×8 feature maps (n=64 spatial tokens)
- **Current bottleneck**: SE channel attention only — no spatial mixing
- **Linear attention**: Adds content-based spatial mixing at O(n*d) complexity instead of O(n²)
- **Parent architecture** (structural_1) already has powerful backbone: 3×3 convs, residual blocks, U-Net skips, bilinear upsampling decoder
- Adding linear attention at bottleneck is the natural next step: enables the model to learn which spatial features to emphasize for reconstruction

### Why not other untried templates
- **Mamba/SSM**: State-space models require more training data/epochs to converge; 5-epoch constraint likely too short
- **ResNet bottleneck blocks**: Already partially present as residual blocks in parent. Marginal gain.
- **Full Transformer with cross-attention**: Previous ViT attempt (iter 2) failed to converge in 5 epochs

### Implementation approach
1. Keep parent's encoder backbone (conv1 → conv2 → res_block1/2/3)
2. Add Performer-style linear attention (ELU+1 feature map) at bottleneck, after res_blocks
3. Keep conv5 → norm → SE (channel attention) pipeline (SE+LinearAttention complement each other)
4. Keep decoder exactly as parent — U-Net skip connections + bilinear upsampling + 3×3 convs
5. Residual connection around linear attention block for training stability
