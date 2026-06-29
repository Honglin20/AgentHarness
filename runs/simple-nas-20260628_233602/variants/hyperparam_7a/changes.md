# Hyperparam Combination A: RMSProp Optimizer

## Changes
- **Optimizer**: RMSProp (never tried in this search) with `lr=1e-3`
- **Scheduler**: StepLR scheduler (proven best) with `batch_size=32`
- **Regularization**: No weight_decay, no warmup, no momentum
