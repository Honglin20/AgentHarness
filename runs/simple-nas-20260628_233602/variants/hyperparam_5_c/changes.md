# Hyperparam Variant C: ReduceLROnPlateau scheduler

## What changed
- scheduler: StepLR → ReduceLROnPlateau (never tried)
- weight_decay: 5e-4 → 0 (confirmed best in hyperparam_4)
- batch_size: 64 → 32 (confirmed best)

## Rationale
ReduceLROnPlateau monitors validation loss and reduces LR when progress stalls.
For 5-epoch training, this could be more adaptive than StepLR's fixed schedule.
It might find a better final LR for the last epoch.

Previous best: Adam+StepLR+batch=32+wd=0 → psnr=31.16
