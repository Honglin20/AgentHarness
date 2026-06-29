# hyperparam_10 — Hyperparam mutation on sota_8 (Lightweight UNet)

## Parent: sota_8
- psnr=30.42, latency=0.4075ms (仅差3.5μs达目标), params=47K
- Lightweight UNet (3-level, channels 8→16→32)

## Hyperparams (vs parent's assumed defaults)
| Parameter         | sota_8 (assumed) | hyperparam_10 | Rationale |
|-------------------|-----------------|---------------|-----------|
| optimizer         | adam (default)  | adam          | Adam consistently best across all prior runs (SGD failed in iter 4, AdamW underperformed) |
| lr                | 1e-3            | **5e-4**      | hyperparam_7 (lr=5e-4+StepLR) gave 31.45dB on structural_1; testing with CosineAnnealing on UNet |
| batch_size        | 64 (from setup) | **16**        | hyperparam_7/8c/9 all confirmed batch=16 optimal for 5-epoch training |
| lr_scheduler      | none/steplr     | **cosine**    | CosineAnnealing gave all-time best 32.23dB (hyperparam_8c) — best scheduler for short training |
| warmup_steps      | 0               | **50**        | Moderate warmup (not extreme 150). Balances between cold start (0) and long warmup (150) |
| weight_decay      | 5e-4 (from setup)| **1e-5**     | hyperparam_7 showed wd=1e-5 works well; tiny regularization helps generalization |
| momentum          | 0.9             | 0.9           | Default, not critical for Adam |
| epochs            | 5               | 5             | Fixed per setup.json |

## Novel combination rationale
hyperparam_9 applied hyperparam_8c's best config (Cosine+lr=8e-4+warmup=150+batch=16+wd=0) to sota_8 → 31.36dB.
This iteration tries a DIFFERENT combo: lower lr (5e-4) + moderate warmup (50) + tiny wd (1e-5) + CosineAnnealing.
This combines the best lr from hyperparam_7 (5e-4) with the best scheduler from hyperparam_8c (CosineAnnealing),
while removing the extreme warmup (150→50) that acted as a hack to keep lr very low.
Hypothesis: moderate lr + cosine decay + short warmup may converge better on the UNet architecture in 5 epochs.
