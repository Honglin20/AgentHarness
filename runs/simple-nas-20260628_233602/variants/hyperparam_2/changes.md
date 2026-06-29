# Hyperparam Mutation — iter 2

## Parent
structural_1 (psnr=29.28, lat=0.415ms, params=105K) — U-Net skip connections + 3×3 convs

## What changed (vs init_hyperparams from setup.json)
| Hyperparam | init (baseline) | iter 1 success | This variant | Rationale |
|---|---|---|---|---|
| lr | 1e-3 | 1e-3 | 1e-3 | Proven effective (iter 1: psnr=28.59). Keeping high LR for fast 5-epoch convergence. |
| batch_size | 64 | 32 | 32 | Smaller batch = more updates/epoch = better convergence in limited epochs. Proven effective. |
| weight_decay | 5e-4 | 5e-4 | **1e-4** | Lower weight decay = less regularization. Parent model has only 105K params (vs iter 1's 167K), needs less regularization to converge fully in 5 epochs. |
| scheduler | None | StepLR (step=640, γ=0.1) | StepLR (step=640, γ=0.1) | StepLR proved effective in iter 1. Reduces LR partway through training to fine-tune. |
| optimizer | Adam | Adam | Adam | Adam is hardcoded in entry script. |

## Key difference from iter 1
Weight decay reduced from 5e-4 to 1e-4. The parent structural_1 model is smaller (105K vs 167K params) and has better architecture (U-Net skip connections). Lower weight decay should allow it to fit the training data more closely within 5 epochs.

## Hypothesis
Lower weight decay (1e-4) on the already-better structural_1 architecture should achieve PSNR > 29.28 (parent's own psnr).

## Search strategy
- lr: 1e-3 (within ±1 order of magnitude of parent init 1e-3)
- batch_size: 32 (within ±50% of parent init 64 → range 32-96)
- epochs: 5 (fixed by setup.json)
- optimizer: Adam (hardcoded in entry)
- lr_scheduler: StepLR (proven)
- weight_decay: 1e-4 (from 5e-4)
