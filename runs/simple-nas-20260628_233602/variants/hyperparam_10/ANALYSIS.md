# hyperparam_10 — Analysis

## Hyperparams applied
- **optimizer**: Adam (default for parent, kept)
- **lr**: 5e-4 (halved from parent's 1e-3, inspired by hyperparam_7's successful 5e-4)
- **batch_size**: 16 (from 64, matching hyperparam_7/8c/9 best practice)
- **lr_scheduler**: CosineAnnealing (replacing parent's default steplr; hyperparam_8c's best scheduler)
- **warmup_steps**: 50 (moderate — not extreme 150 which acts as low-lr hack)
- **weight_decay**: 1e-5 (small regularization, from hyperparam_7's config)
- **epochs**: 5 (fixed)

## Training curve
- Epoch 1: train_loss=379.5, val_loss=155.9, PSNR=26.20
- Epoch 2: train_loss=150.9, val_loss=121.2, PSNR=27.29
- Epoch 3: train_loss=107.3, val_loss=94.9, PSNR=28.36 ← BEST EPOCH
- Epoch 4: train_loss=133.9, val_loss=131.0, PSNR=26.96 (loss spike)
- Epoch 5: train_loss=129.4, val_loss=127.4, PSNR=27.08

## Result vs parent (sota_8)
| Metric       | Parent (sota_8) | hyperparam_10 | Δ     |
|-------------|----------------|---------------|-------|
| PSNR        | 30.42          | 27.08         | -3.34 |
| Latency (ms)| 0.4075         | 0.4289        | +5.3% |
| Params      | 47,232         | 47,232        | same  |

## Analysis
The CosineAnnealing + lr=5e-4 + warmup=50 combination did NOT work well on the UNet architecture.
Best epoch PSNR was 28.36 (epoch 3), but the final PSNR was 27.08 due to a loss spike at epoch 4.
The loss spike suggests the lr schedule may be causing instability — CosineAnnealing resets lr each epoch,
and with warmup overriding the schedule, the combined effect may be detrimental.

## Key lessons
1. hyperparam_9's config (Cosine + lr=8e-4 + warmup=150 + batch=16 + wd=0 → 31.36dB) is still the best
   confirmed hyperparam config for this UNet architecture
2. The warmup=50 + CosineAnnealing combo seems worse than both warmup=0 (no scheduler) and warmup=150 (effectively low lr)
3. halving the lr (5e-4 vs 1e-3) without very long warmup hurts convergence in 5 epochs
4. For future hyperparam explorations on this UNet: stick with lr ~8e-4 + warmup ~150 or just use plain Adam with lr=1e-3
