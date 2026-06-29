# Hyperparam Variant 5 — Analysis

## Summary
**Winner: Variant C (ReduceLROnPlateau scheduler)** — psnr=31.15, latency=0.464ms

### 3 Variants Tested

| Variant | Optimizer | Scheduler | PSNR | Latency | Verdict |
|---------|-----------|-----------|------|---------|---------|
| A | Adam | OneCycleLR | 28.60 | — | Below best |
| B | RMSProp | StepLR | 5.37 | — | DEAD (diverged) |
| **C** | **Adam** | **ReduceLROnPlateau** | **31.15** | **0.464ms** | **Best** |

### Key Findings
1. **ReduceLROnPlateau** (Variant C) achieves psnr=31.15 — tying the historical best
   from hyperparam_2 and hyperparam_4. The val_loss (49.93) is the lowest ever recorded,
   and the PSNR curve is still steep at epoch 5 (30.48→31.15).
2. **OneCycleLR** (Variant A) only reaches 28.60 — not competitive with StepLR for this
   model in 5 epochs. The warmup phase may be wasting training steps.
3. **RMSProp** (Variant B) completely diverges (psnr=5.37) — same failure mode as SGD
   in hyperparam_4. This model requires Adam-family optimizers.

### Comparison with History
- hyperparam_2: Adam+StepLR+wd=1e-4 → psnr=31.16, lat=0.519ms
- hyperparam_4: Adam+StepLR+wd=0 → psnr=31.16, lat=0.483ms
- **hyperparam_5_c**: Adam+Plateau+wd=0 → psnr=31.15, lat=0.464ms

The latency improvement (0.464ms vs 0.483-0.519ms) is within measurement noise.
The key contribution is confirming ReduceLROnPlateau as an equally viable scheduler
for this model — providing an alternative to StepLR for future iterations.
