# Hyperparam Variant A: OneCycleLR scheduler

## What changed
- scheduler: StepLR → OneCycleLR (never tried in previous iterations)
- weight_decay: 5e-4 → 0 (confirmed best in hyperparam_4)
- batch_size: 64 → 32 (confirmed best in hyperparam_1-4)
- Added warmup_steps=50 for OneCycleLR's warmup phase

## Rationale
OneCycleLR is specifically designed for short training schedules (5 epochs).
It warms up LR from low to high, then anneals back down — helping the model
explore the loss landscape quickly in the first few epochs. This is ideal for
our 5-epoch constraint where StepLR only steps once.

Previous best: Adam+StepLR+batch=32+wd=0 → psnr=31.16
Target: Beat 31.16 with OneCycleLR's faster convergence
