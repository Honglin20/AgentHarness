# hyperparam_3 — AdamW + CosineAnnealing

## What changed
| Hyperparam | hyperparam_2 (best) | hyperparam_3 (this) |
|---|---|---|
| optimizer | Adam | **AdamW** |
| lr | 1e-3 | 1e-3 (same) |
| batch_size | 32 | 32 (same) |
| lr_scheduler | StepLR (step=640, γ=0.1) | **CosineAnnealing** |
| warmup_steps | 0 | 0 (same) |
| weight_decay | 1e-4 | 1e-4 (same) |

## Results vs parent (structural_1: PSNR=29.28, lat=0.415ms)
| Metric | Value | vs Parent |
|---|---|---|
| **PSNR** | **30.27 dB** | **+0.99 dB** ↑ |
| **Latency (median)** | **0.489 ms** | +0.074 ms ↑ |
| **Params** | 105,236 | (same — model unchanged) |
| **Training time** | 73.6s | (similar) |

## Results vs hyperparam_2 (Adam+StepLR: PSNR=31.16, lat=0.519ms)
- PSNR: 30.27 vs 31.16 (↓0.89 dB) — AdamW + CosineAnnealing underperformed Adam + StepLR
- Latency: 0.489 vs 0.519ms (↓0.03ms) — slightly faster (same model, natural variation)

## Analysis
1. **AdamW + CosineAnnealing** did not outperform **Adam + StepLR** on this model for 5-epoch training.
2. CosineAnnealing reduces LR smoothly to near-zero over 5 epochs, which may be too aggressive for short training. StepLR's discrete drop at step 640 (~epoch 2.5) seems better matched to the 5-epoch budget.
3. The PSNR curve confirms: Epoch 1-3 gaps are small (<0.5dB) but later epochs show Adam+StepLR pulling ahead (30.27 vs 31.16 at epoch 5).
4. **Recommendation**: Stick with Adam + StepLR for this model. AdamW might benefit from longer training schedules.

## Verdict
**Promising** — PSNR=30.27 is well above baseline (24.9) and tolerance min (24.65). Latency 0.489ms is close to target 0.404ms. Not the best hyperparam variant (hyperparam_2 at 31.16 is better), but a valid data point showing AdamW+Cosine is slightly worse than Adam+StepLR for 5-epoch training.
