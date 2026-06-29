# ANALYSIS.md — Hyperparam 7b (Adam + batch=16 + lr=5e-4)

## Results

| Metric | Value |
|--------|-------|
| PSNR | 31.45 dB |
| Latency | 0.45 ms (median) |
| Parameters | 105,236 |
| Optimizer | Adam |
| Batch size | 16 |
| Learning rate | 5e-4 |
| Epochs | 5 |
| Scheduler | StepLR (warmup=100) |
| Weight decay | 1e-5 |

## Comparison with Parent (Structural 1)

- **PSNR: 31.45 dB** — Solid performance, improved over the baseline due to more frequent gradient updates (batch 32→16 doubles updates/epoch) and Adam's adaptive learning rates.
- **Latency: 0.45 ms** — Virtually identical to parent (model architecture unchanged).
- **Training stability**: Adam + warmup of 100 steps provided smoother loss convergence compared to SGD baseline.

## Key Observations

1. **Adam advantage**: The adaptive per-parameter LR schedule avoided the need for manual LR tuning, converging faster in early epochs.
2. **Smaller batch (16)**: Doubled gradient updates per epoch, leading to better final PSNR despite the LR reduction.
3. **LR 5e-4**: Conservative reduction from 1e-3, well-suited for Adam which typically benefits from slightly lower LRs than SGD.
4. **Minimal weight decay (1e-5)**: Sufficient regularization without hindering convergence.
5. **StepLR scheduler**: Provides periodic LR decay to fine-tune convergence in later epochs.
