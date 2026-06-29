# hyperparam_4 — SGD with momentum

## What changed

Parent: structural_1 (psnr=29.28, latency=0.415ms, params=105K)

### Hyperparameter changes (vs init_hyperparams in setup.json)

| Param | Parent (init) | hyperparam_4 |
|-------|--------------|--------------|
| optimizer | adam | **sgd** |
| momentum | N/A | **0.9** |
| batch_size | 64 | **32** |
| lr | 0.001 | 0.001 |
| lr_scheduler | steplr | steplr |
| weight_decay | 5e-4 | **1e-4** |
| warmup_steps | 0 | 0 |
| epochs | 5 | 5 (fixed) |

### Why

**Rationale**: Previous hyperparam iterations have exhaustively explored Adam-family optimizers:
- hyperparam_2 (Adam+StepLR+wd=1e-4+batch=32) → **31.16** ★ BEST
- hyperparam_3 (AdamW+CosineAnnealing) → **30.27**

**SGD with momentum (0.9)** is completely unexplored. For small models (105K params), SGD+momentum can:
1. Converge to better generalizing minima than Adam (less aggressive adaptive LR)
2. Work particularly well with StepLR schedules in few-epoch scenarios
3. Benefit from momentum=0.9 for stable gradient descent

### Model
Unchanged (identical copy of structural_1/model.py).
