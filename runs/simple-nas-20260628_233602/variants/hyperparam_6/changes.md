# hyperparam_6 — OneCycleLR scheduler + proven best config

## Changes from parent (structural_1)

### Model
- **Unchanged** — identical copy of structural_1/model.py

### Hyperparams
| Param | Parent (init) | hyperparam_6 | Rationale |
|-------|--------------|--------------|-----------|
| lr | 1e-3 | **1e-3** | Proven optimal across 5 iterations (31.15-31.16dB) |
| batch_size | 64 | **32** | Proven optimal — batch=32 gives better gradient estimates |
| optimizer | adam | **adam** | Best for this architecture — SGD and AdamW trailed |
| lr_scheduler | steplr | **onecycle** | **Novel**: OneCycleLR never tried on structural_1. Designed for rapid convergence in few epochs — starts warmup, peaks at max_lr, then anneals. |
| weight_decay | 5e-4 | **0** | Proven equivalent to 1e-4 (hyperparam_4). Simpler. |
| warmup_steps | — | **0** | OneCycle handles warmup internally |

### Why OneCycleLR?
Previous iterations established that Adam+StepLR and Adam+ReduceLROnPlateau both plateau at PSNR=31.15-31.16 on structural_1. OneCycleLR's cycle strategy (warmup→high LR→anneal) may extract more learning signal from the limited 5 epochs, potentially pushing PSNR beyond 31.16dB.

Key insight: OneCycleLR starts training at low LR (warmup), climbs to high LR for exploration, then anneals to low LR for fine-tuning — all within 5 epochs. This is more adaptive than StepLR which only steps at fixed intervals.
