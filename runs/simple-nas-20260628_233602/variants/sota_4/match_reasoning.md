# SOTA Template Match: Swin Transformer (iter 4)

## Project Characteristics
- **Task**: Image-to-image reconstruction (Deep-JSCC) — 3×32×32 → 3×32×32
- **Current parent**: structural_1 (PSNR=29.28, latency=0.415ms, params=105K)
- **Parent architecture**: CNN encoder-decoder + U-Net skip connections + residual blocks + bilinear upsampling decoder
- **Key constraint**: Must keep Channel layer (AWGN), power normalization, and interface

## SOTA History (what's been tried)
| Iter | Template | Result |
|------|----------|--------|
| 0 | UNet | PSNR=36.4 (amazing!) but latency=9.99ms |
| 1 | DenseNet | DEAD (diverged, PSNR=22.84) |
| 2 | ViT encoder | DEAD (didn't converge, PSNR=22.91) |
| 3 | MobileNetV2 | PSNR=29.45 (+0.17), params=61K, latency=0.553ms |

## Rotation Position
This is the **5th sota attempt** → per rotation strategy: **Swin Transformer**

## Why Swin Transformer Now
1. **Not yet tried** — UNet, DenseNet, ViT, MobileNetV2 all tried; Swin is next
2. **Ideal for image tasks** — Shifted window attention captures both local fine detail (window-level) and global context (via shifting), which is crucial for reconstruction quality
3. **Hierarchical design** — Matches Deep-JSCC's encoder-decoder structure naturally: 32×32→16×16→8×8 downsampling
4. **Better convergence than ViT** — Window-based attention is local, making it easier to train in few epochs (unlike full ViT which diverged in iter 2)
5. **Computationally efficient** — Window attention O(N×W²) vs full attention O(N²), much cheaper for 8×8 features

## Design Strategy
- **Keep the successful structural_1 decoder** (bilinear upsampling + 3×3 conv, U-Net skip)
- **Replace encoder with lightweight Swin**: Conv1 (3→16, 3×3 stride 2) for skip features, then Conv2 (16→32, 3×3 stride 2) + 2 Swin blocks (window=4, 4 heads) on 8×8 features
- **Keep all task-specific components**: Channel layer, power normalization
- **Target**: Match or exceed structural_1's PSNR (29.28) at similar latency

