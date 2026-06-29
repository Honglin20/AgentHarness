# Hyperparam Variant: hyperparam_3_subA

## Why this combination?

- **Optimizer: AdamW** — Decouples weight decay from gradient updates, providing better regularization than standard Adam. This is especially beneficial for vision transformers where weight decay interacts poorly with adaptive gradients in standard Adam.
- **Learning Rate: 0.001** — Standard default for Adam-family optimizers; works well with cosine annealing.
- **LR Scheduler: CosineAnnealing** — Gradually reduces learning rate following a cosine curve, eliminating the need to tune step-based decay milestones. Smooth annealing helps convergence in the final epochs.
- **Batch Size: 32** — Moderate batch size that balances gradient noise and training speed for 32x32 inputs.
- **Weight Decay: 1e-4** — Mild L2 regularization to prevent overfitting without destabilizing training.
- **Momentum: 0.9** — Standard momentum value used in AdamW's internal momentum estimation.
- **Bottleneck Multiplier: 2.0** — Kept the same as parent to isolate hyperparameter effects from architecture changes.
- **Epochs: 5** — Fixed across all variants for fair comparison.
- **No warmup** — Warmup is less critical for cosine annealing with only 5 epochs.

This configuration aims for smoother convergence and better generalization compared to baseline SGD + StepLR.
