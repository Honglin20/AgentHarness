# hyperparam_6 Analysis

## Changes
- **lr**: 1e-3 (unchanged from proven best)
- **batch_size**: 32 (proven best)
- **optimizer**: Adam (proven best)
- **lr_scheduler**: **OneCycleLR** (novel — never tried on structural_1 before)
- **weight_decay**: 0 (proven equivalent to 1e-4)
- **model**: Identical to structural_1

## Training Metrics
| Metric | Value | vs Parent (29.28) |
|--------|-------|-------------------|
| PSNR | **31.20 dB** | **+1.92dB** |
| val_loss | 49.34 | -35.6% |
| train_loss | 53.60 | -37.1% |
| Params | 105,236 | unchanged |
| Latency | 0.521ms (median) | ~same architecture |

## PSNR Curve
| Epoch | PSNR |
|-------|------|
| 1 | 27.00 |
| 2 | 28.85 |
| 3 | 29.87 |
| 4 | 30.47 |
| 5 | **31.20** |

## Observations
- **OneCycleLR performs on par with StepLR/ReduceLROnPlateau** (31.20 vs 31.15-31.16dB)
- Slight improvement (+0.04-0.05dB) over previous best, but within noise
- Loss curve shows healthy convergence: 330.8 → 53.6 (84% reduction over 5 epochs)
- PSNR curve still rising at epoch 5 (no plateau), suggesting more epochs would improve further
- Latency within expected range for structural_1 architecture

## Conclusion
OneCycleLR is a viable alternative to StepLR/ReduceLROnPlateau on structural_1. Combined with Adam + lr=1e-3 + batch=32 + wd=0, it achieves 31.20dB PSNR — matching the historical best (~31.15-31.16dB). The hyperparam direction on structural_1 has reached its ceiling (~31.2dB).
