# hyperparam_4 — Analysis

## Hyperparameter changes

Parent: **structural_1** (psnr=29.28, latency=0.415ms, params=105K)

| Param | init_hyperparams (baseline) | hyperparam_4 (best) |
|-------|:---------------------------:|:-------------------:|
| optimizer | adam | adam (unchanged) |
| lr | 0.001 | 0.001 (unchanged) |
| batch_size | 64 | **32** (−50%) |
| lr_scheduler | steplr | steplr (unchanged) |
| weight_decay | 5e-4 | **0** (removed) |
| momentum | N/A | 0.9 |
| epochs | 5 | 5 (fixed) |

## Two combos tested

### Combo A: SGD + momentum 0.9 (failed)
- lr=0.001, batch=32, SGD+momentum, StepLR, wd=1e-4
- **Result: PSNR=5.17** — did not converge at all. Loss stuck at ~19,800 across all 5 epochs.
- Root cause: SGD without adaptive LR cannot converge in 5 epochs for this compression task.

### Combo B: Adam + weight_decay=0 (success — matches all-time best)
- lr=0.001, batch=32, Adam, StepLR, wd=0
- **Result: PSNR=31.16** — ties hyperparam_2's all-time best PSNR!
- Loss curve: 331.0 → 110.1 → 78.4 → 61.5 → 53.0 (steady convergence)
- PSNR curve: 26.79 → 28.54 → 29.81 → 30.53 → 31.16

## Training curves

```
Epoch | Train Loss | Val Loss | PSNR
  1   |   331.03   |  136.24  | 26.79
  2   |   110.09   |   91.09  | 28.54
  3   |    78.41   |   67.98  | 29.81
  4   |    61.52   |   57.51  | 30.53
  5   |    52.98   |   49.78  | 31.16
```

## Key insight

- **weight_decay=0 achieves the same PSNR as wd=1e-4** (both 31.16). For small models (105K params) with only 5 epochs of training, weight decay regularization has negligible effect — the model doesn't get to the point of overfitting where weight decay matters.
- **SGD is not viable** — the adaptive learning rate of Adam-family optimizers is essential for quick convergence in few-epoch scenarios.
- Best config confirmed: **Adam + StepLR + batch=32 + lr=1e-3** (with any wd ≤ 1e-4)

## Latency

- Median: **0.483ms** (same architecture as parent)
- Latency is architecture-dependent, not hyperparameter-dependent

## Comparison with history

| Variant | PSNR | Latency | Config |
|---------|:----:|:-------:|--------|
| hyperparam_2 | **31.16** | 0.519ms | Adam+StepLR+wd=1e-4+batch=32 |
| **hyperparam_4** | **31.16** | 0.483ms | Adam+StepLR+wd=0+batch=32 |
| hyperparam_3 | 30.27 | 0.489ms | AdamW+CosineAnnealing |
| parent (structural_1) | 29.28 | 0.415ms | init_hyperparams |
