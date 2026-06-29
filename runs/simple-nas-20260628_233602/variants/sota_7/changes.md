# Changes: sota_7 — Mamba/SSM Encoder

## What Changed
- Replaced `_ResidualBlock × 3` in encoder → `_MambaBlock × 3`
- Added new `_MambaBlock` class implementing SSM-based sequence processing

## Architecture Flow
```
conv1(3→16, /2) → conv2(16→32, /2) → mamba1 → mamba2 → mamba3 → conv5(32→2c) → norm → SE
                                                                                    ↓
                                                                              Decoder (unchanged)
```

## Mamba/SSM Design
Each `_MambaBlock(dim=32, d_state=8, expand=2)`:
1. **LayerNorm** on sequence (B, L=64, C=32)
2. **Linear expansion**: C=32 → inner=64, split into x1 (→SSM) and x2 (→gate)
3. **Depthwise conv1d** (kernel=3, groups=inner) — local context along spatial sequence
4. **Selective SSM**: input-dependent delta, B, C parameters
   - h_t = exp(dt*A) * h_{t-1} + (1 - exp(dt*A)) * B * x_t
   - y_t = C * h_t + x (residual)
5. **Gating**: y * SiLU(x2)
6. **Output projection**: inner→C + residual

## Why Mamba
- Linear complexity O(n) vs self-attention's O(n²) — scales to higher resolutions
- Input-dependent parameters (selective SSM) adapt to spatial content
- SiLU gating + depthwise conv1d are CPU-friendly operations
- Previous SOTA attempts (iter0 UNet PSNR=36.4, iter5 Linear Attention 31.04, iter6 Bottleneck 30.79) all showed promise; Mamba offers a different inductive bias

## Preserved Components
✅ conv1 (U-Net skip source) — unchanged
✅ Channel layer — unchanged
✅ Decoder (bilinear upsample + 3×3 conv + skip) — unchanged
✅ Power normalization — unchanged
✅ SE block at bottleneck — unchanged
✅ Input/Output interface (3ch × 32×32) — unchanged
