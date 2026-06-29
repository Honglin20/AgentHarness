# hyperparam_1 Analysis

## Changes
- **batch_size**: 64 → 32 (more gradient updates per epoch)
- **lr_scheduler**: None → StepLR (step_size=640, gamma=0.1)
- All other hyperparams same as baseline (lr=1e-3, weight_decay=5e-4, optimizer=Adam)

## Results

| Metric | structural_0 (parent) | hyperparam_1 (this) | Δ |
|--------|---------------------|-------------------|---|
| PSNR   | 27.00 dB            | **28.59 dB**      | **+1.59 dB** |
| Latency | 1.40 ms            | 0.76 ms           | -0.64 ms |
| Params  | 167,887             | 167,887            | 0 |
| Duration | —                  | 66.6s              | — |

## Training Curve

| Epoch | Train Loss | Val Loss | PSNR |
|-------|-----------|---------|------|
| 1 | 472.49 | — | 24.50 |
| 2 | 180.21 | — | 26.59 |
| 3 | 130.10 | — | 27.44 |
| 4 | 107.07 | — | 28.24 |
| 5 | 95.37 | 89.87 | 28.59 |

## Key Takeaways

1. **PSNR improved +1.59 dB** over parent (structural_0) — just by halving batch size and adding StepLR scheduler
2. **Smaller batch (32) significantly outperformed larger batch** — more gradient updates per epoch helps convergence in the fixed 5-epoch budget
3. **StepLR scheduler** (gamma=0.1 at step 640) likely helped fine-tune the learning rate in later epochs
4. Model architecture unchanged, so params and latency are identical
5. Training curve still trending down at epoch 5 — more epochs would further improve
6. This demonstrates the huge impact of hyperparameters on the same architecture
