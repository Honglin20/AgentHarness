# hyperparam_3 — AdamW + CosineAnnealing on structural_1

## What changed (vs hyperparam_2 best config: Adam + StepLR + wd=1e-4 → PSNR=31.16)

| Hyperparam | hyperparam_2 (best) | hyperparam_3 (this) |
|---|---|---|
| optimizer | Adam | **AdamW** |
| lr | 1e-3 | 1e-3 (same) |
| batch_size | 32 | 32 (same) |
| lr_scheduler | StepLR (step=640, γ=0.1) | **CosineAnnealing** |
| warmup_steps | 0 | 0 (same) |
| weight_decay | 1e-4 | 1e-4 (same) |
| epochs | 5 | 5 (same — fixed) |

## Rationale

1. **AdamW → Adam**: AdamW decouples weight decay from gradient updates, providing more effective regularization for small models (105K params). This is especially beneficial when training only 5 epochs — the decoupled WD doesn't interfere with the adaptive learning rates.

2. **CosineAnnealing**: Replaces StepLR. Cosine annealing smoothly reduces LR from 1e-3 to near-zero over the 5 epochs. For short 5-epoch training, this provides a natural "cooldown" that StepLR's discrete drops at step 640 (epoch 2.5) cannot match. Cosine annealing has been shown to work exceptionally well with AdamW.

3. Both lr=1e-3 and batch=32 are kept from hyperparam_2 (proven effective). Weight_decay=1e-4 is also carried forward as it gave the best result in hyperparam_2.

**Expected**: PSNR improvement from 31.16 → potentially 31.5+, with similar latency (~0.5ms).
