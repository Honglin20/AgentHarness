# SOTA Template Matching — iter 10

## Current State
- **Parent**: sota_8 (Lightweight UNet, channels 8→16→32, PSNR=30.42, lat=0.4075ms, params=47K)
- **Parent PSNR tolerance**: baseline 24.65, current 30.42 (+5.77dB headroom)
- **Latency target**: 0.404ms (parent at 0.4075ms — only 3.5μs away!)

## Previously Tried Templates (all exhausted)
| Iter | Template | Result |
|------|----------|--------|
| 0 | UNet (20→40→80) | PSNR=36.4, lat=9.99ms — high PSNR but latency exploded |
| 1 | DenseNet | dead (diverged, PSNR=22.84) |
| 2 | ViT encoder | dead (PSNR=22.91, not convergent in 5 epochs) |
| 3 | MobileNetV2 inverted residuals | promising (PSNR=29.45, lat=0.553ms) |
| 4 | Swin Transformer | not promising (PSNR=28.68, lat=0.598ms) |
| 5 | Linear Attention (Performer) | promising (PSNR=31.04, lat=0.711ms) |
| 6 | ResNet Bottleneck | promising (PSNR=30.79, lat=0.564ms, params=54K) |
| 7 | Mamba/SSM encoder | promising+latency pain (PSNR=29.78, lat=1.603ms) |
| 8 | Lightweight UNet (8→16→32) | **BEST** (PSNR=30.42, lat=0.4075ms, params=47K) |
| 9 | UNet wider (10→20→40) | not promising (PSNR=29.55, lat=0.4267ms) |

## Selected Template
**UNet variant — Narrower channels (6→12→24)**

Rationale:
1. All 9 major SOTA templates exhausted → per instructions, return to best-performing template (UNet) for variants
2. sota_8 (8→16→32) at 0.4075ms is only 3.5μs from target
3. sota_9 tried wider (10→20→40) → PSNR dropped, latency increased
4. **Narrower channels (6→12→24)** is the untried direction: reduces params ~38%, lowers latency proportionally
5. With 5.77dB headroom (30.42-24.65), even a moderate PSNR drop still keeps us well above tolerance
6. Computations scale ~O(channels²), so 6→12→24 should reduce latency enough to cross the 0.404ms threshold

## Expected Impact
- **Params**: ~29K (vs 47K, −38%)
- **Latency**: estimated <0.38ms (vs 0.4075ms, should clear 0.404ms target)
- **PSNR**: estimated ~29-30dB (within tolerance with headroom)
