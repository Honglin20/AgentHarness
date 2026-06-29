# SOTA Template Match: Mamba / SSM (State Space Model)

## Why This Template (Not Previously Tried)

- **Tried SOTA templates**: UNet (iter0), DenseNet (iter1), ViT (iter2), MobileNetV2 (iter3), Swin (iter4), Linear Attention (iter5), ResNet Bottleneck (iter6)
- **Untried**: Mamba/SSM, Transformer (编解码)
- **Priority**: Per the轮转策略, Mamba (#7) is the next untried template

## Task Match Analysis

| Property | Current (structural_1) | Mamba/SSM Suitability |
|----------|----------------------|----------------------|
| Input | [B,3,32,32] image | ✅ Patch embedding works for 32×32 images |
| Output | [B,3,32,32] image | ✅ Keep decoder unchanged |
| Task | Image-to-image (JSCC) | ✅ Encoder needs to compress; Mamba's linear complexity O(n) vs O(n²) is beneficial |
| Encoder features | 32ch, 8×8 spatial | ✅ 64 spatial positions as sequence — ideal for SSM |
| Latency concern | Parent 0.415ms (near target) | ⚠️ Mamba adds conv1d + linear ops; may increase latency moderately |
| Short training (5 epochs) | ⚠️ Previous ViT/DenseNet failed | ✅ Mamba uses simpler ops (conv1d + linear) vs attention, more stable in short training |

## Why Mamba Instead of Transformer (编解码)

Transformer encoder-decoder would require CrossAttention between encoder and decoder outputs, adding complexity. Mamba replaces just the encoder's residual blocks with SSM blocks — minimal disruption to the working structural_1 architecture (skip connections, decoder, channel layer all preserved).

## Implementation Strategy

Replace the 3 _ResidualBlock instances in the encoder with MambaBlocks:
1. conv1: 3→16, 3×3 stride 2 (keep — encoder skip connection source)
2. conv2: 16→32, 3×3 stride 2 (keep)
3. **res_block1/2/3** → **MambaBlock ×3** at 32ch, 8×8 spatial (sequence length 64)
4. conv5: 32→2*c, 3×3 (keep)
5. Norm + SE (keep)
6. Decoder unchanged (keep U-Net skip + bilinear upsample + conv)

Each MambaBlock processes the 8×8=64 spatial positions as a 1D sequence with:
- LayerNorm → linear expansion → depthwise conv1d → SiLU activation
- Simplified SSM (linear recurrence with learned parameters)
- Gating + residual connection
- Reshape back to 2D

This keeps the parameter count manageable and preserves all task-specific components.
