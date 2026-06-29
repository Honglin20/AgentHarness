# Hyperparam Variant Analysis — iter 0

## Changes from parent (v0)
| Param | v0 | hyperparam_0 |
|-------|----|-------------|
| lr | 0.001 | 0.0003 |
| batch_size | 64 | 128 |
| epochs | 5 | 5 |
| optimizer | adam | adamw |
| weight_decay | 5e-4 | 1e-4 |

## Results
- PSNR: 21.79 dB (vs parent 24.9 dB)
- Latency: 1.35ms (unchanged, same architecture)
- Params: 181,865 (unchanged)

## Analysis
The lower learning rate (3e-4 vs 1e-3) with only 5 epochs didn't converge as well as the parent. The model was still learning (PSNR curve increasing: 19.1→21.79). With more epochs, this combination would likely match or exceed parent PSNR, but epochs are fixed at 5 per setup.json.

## Next iteration suggestions
- Try higher LR (3e-3) or revert to parent LR (1e-3) but with AdamW
- Or keep lower LR but explore different optimizer combinations
- The batch_size=128 seems stable (loss decreasing steadily)
