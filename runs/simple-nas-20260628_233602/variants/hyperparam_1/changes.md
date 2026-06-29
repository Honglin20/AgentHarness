# hyperparam_1 — Hyperparameter Mutation

## Changes from parent (structural_0 / baseline init_hyperparams)

| Hyperparam | Baseline | hyperparam_0 (iter 0) | hyperparam_1 (iter 1, this) |
|------------|----------|----------------------|---------------------------|
| lr         | 1e-3     | 3e-4 ❌ (failed)     | **1e-3** (kept)           |
| batch_size | 64       | 128 ❌               | **32** (halved)            |
| epochs     | 5        | 5                    | 5 (fixed)                 |
| optimizer  | Adam     | AdamW (not supported)| Adam (hardcoded)          |
| scheduler  | none     | Cosine (not supported)| **StepLR** (step=640, γ=0.1) |
| weight_decay | 5e-4   | 1e-4                 | 5e-4 (kept)               |
| warmup_steps | 0      | 100 (not supported)  | 0                         |

## Rationale

1. **lr kept at 1e-3**: hyperparam_0 (iter 0) tried lr=3e-4 and failed (PSNR=21.79). With only 5 epochs the model needs a higher learning rate to converge quickly.

2. **batch_size 64→32**: Halving batch size doubles gradient updates per epoch. For the fixed 5-epoch budget, this gives the optimizer 10 passes through the data instead of 5, allowing more weight updates and better convergence.

3. **Added StepLR scheduler**: Baseline used no scheduler. Adding StepLR with step_size=640 (≈10 full passes at batch=32 on 50K CIFAR-10 images: 50K/32=1563 steps/batch → ~40% through training), gamma=0.1 reduces lr when approaching convergence. This can help fine-tune in late epochs.

4. **Expected impact**: More gradient updates (batch 32) + learning rate decay should improve PSNR convergence within the tight 5-epoch budget.
