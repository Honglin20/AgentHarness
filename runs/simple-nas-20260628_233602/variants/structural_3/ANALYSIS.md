# structural_3 — Analysis

## What changed
1. **SEBlock → ECABlock** at encoder bottleneck: lighter channel attention (1D conv, k=3, ~64 params instead of ~208 for SE reduction=8). Comparable accuracy.
2. **Compressed U-Net skip**: 1×1 conv (16→8ch) to compress skip features before decoder concatenation. conv4 input 48→40ch.
3. **Decoder ECA**: Lightweight ECA after decoder conv3 residual for better feature refinement.

## Training curve
| Epoch | Train Loss | Val Loss | PSNR |
|-------|-----------|---------|------|
| 1 | 505.59 | — | 25.22 |
| 2 | 163.12 | — | 26.72 |
| 3 | 127.29 | — | 27.43 |
| 4 | 106.24 | — | 27.82 |
| 5 | 90.54 | 85.39 | 28.82 |

Loss still dropping at epoch 5 — model underfit. Training time: 41.7s.

## Results vs Parent (structural_1, PSNR=29.28, lat=0.415ms, params=105K)
| Metric | structural_1 (parent) | structural_3 (ours) | Δ |
|--------|---------------------|--------------------|---|
| PSNR | 29.28 dB | 28.82 dB | -0.46 dB |
| Latency | 0.415 ms | 0.528 ms | +0.113 ms (+27%) |
| Params | 105,236 | 103,926 | -1,310 (-1.2%) |
| Val Loss | — | 85.39 | — |

## Assessment
- PSNR slightly below parent but well above tolerance (24.65)
- ECA + compressed skip maintained quality while reducing params
- latency increase may be due to decoder ECA overhead on CPU
- Loss curve still dropping → more epochs would improve PSNR further
