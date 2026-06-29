# Analysis — hyperparam_2

## Hyperparams applied
| Param | Value | Base (init) |
|---|---|---|
| lr | 1e-3 | 1e-3 |
| batch_size | 32 | 64 |
| optimizer | Adam | Adam |
| lr_scheduler | StepLR(step=640, γ=0.1) | None |
| weight_decay | 1e-4 | 5e-4 |
| epochs | 5 | 5 |

## Results vs Parent (structural_1: psnr=29.28, lat=0.415ms, params=105K)

| Metric | Parent | This variant | Δ |
|---|---|---|---|
| PSNR | 29.28 dB | **31.16 dB** | **+1.88 dB** |
| Val Loss | — | 49.78 | — |
| Train Loss | — | 51.31 | — |
| Latency | 0.415 ms | 0.519 ms | +0.104 ms |
| Params | 105,236 | 105,236 | 0 |

## Learning curve
Epoch 1: 27.69 dB → Epoch 2: 29.35 dB → Epoch 3: 30.21 dB → Epoch 4: 30.59 dB → Epoch 5: 31.16 dB
Consistent upward trend with no plateau — could benefit from more epochs.

## Key insight
Lower weight decay (1e-4 vs 5e-4) on the structural_1 architecture unlocked significantly better PSNR.
The smaller model (105K params) benefits from less regularization when trained for only 5 epochs.
StepLR scheduler at step=640 with γ=0.1 continues to prove effective.

## Comparison with iter 1 hyperparam
iter 1 hyperparam_1 (on structural_0 parent, 167K params): psnr=28.59
This variant (on structural_1 parent, 105K params): psnr=31.16
The combination of better architecture + lower weight decay yields +2.57 dB over iter 1's hyperparam effort.
