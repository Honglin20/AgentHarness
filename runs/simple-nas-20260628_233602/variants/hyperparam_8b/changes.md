# Hyperparam Variant: RMSProp Optimizer

This variant tests the **RMSProp** optimizer on the **structural_1** model.

## Changes
- **optimizer**: Changed from (default) to `rmsprop` — RMSProp has never been tried in this experiment's history.
- **lr**: 5.0e-4 (proven learning rate)
- **batch_size**: 16
- **epochs**: 5
- **lr_scheduler**: steplr
- **warmup_steps**: 100
- **weight_decay**: 1e-5
- **momentum**: 0.9

## Rationale
RMSProp adapts the learning rate per-parameter using a moving average of squared gradients, which can help with non-stationary objectives and noisy gradients. The momentum term (0.9) is added to accelerate convergence. This is a fresh exploration beyond previously tested optimizers (Adam/SGD variants).
