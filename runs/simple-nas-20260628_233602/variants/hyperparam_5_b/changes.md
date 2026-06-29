# Hyperparam Variant B: RMSProp optimizer

## What changed
- optimizer: Adam → RMSProp (never tried in previous iterations)
- weight_decay: 5e-4 → 1e-4 (confirmed good in hyperparam_2)
- batch_size: 64 → 32 (confirmed best)
- scheduler: StepLR (kept as proven best)

## Rationale
RMSProp is an adaptive optimizer that works well for computer vision tasks.
All previous hyperparam runs tried Adam, AdamW, and SGD — RMSProp is the last
major optimizer untested. It may handle the U-Net skip-connection gradients
differently.

Previous best: Adam+StepLR+batch=32+wd=0 → psnr=31.16
