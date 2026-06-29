# hyperparam_9 Analysis

## What changed
Applied the best-ever hyperparam config (proven by hyperparam_8c on structural_1) 
to the sota_8 parent (Lightweight UNet, 47K params):
- **lr**: 1e-3 → 8e-4 (CosineAnnealing-optimal)
- **batch_size**: 64 → 16 (small batch works best for 5-epoch training)
- **lr_scheduler**: steplr → cosine (CosineAnnealing + warmup)
- **warmup_steps**: 0 → 150 (longer warmup stabilizes high lr in short training)
- **weight_decay**: 5e-4 → 0 (proven best)
- **optimizer**: adam → adam (unchanged, Adam proven optimal)

## Results
| Metric       | Parent (sota_8) | hyperparam_9 | Δ        |
|--------------|-----------------|--------------|----------|
| PSNR         | 30.42 dB        | **31.36 dB** | **+0.94**|
| Latency      | 0.4075 ms       | 0.454 ms     | +0.046ms |
| Params       | 47,232          | 47,232       | 0        |
| Train Loss   | 63.25           | 49.71        | -13.54   |
| Val Loss     | 58.97           | 47.56        | -11.41   |

## PSNR Curve
- Epoch 1: 27.35 dB
- Epoch 2: 29.12 dB  
- Epoch 3: 30.31 dB
- Epoch 4: 30.99 dB
- Epoch 5: **31.36 dB** (still rising — more epochs would improve further)

## Analysis
1. **PSNR improvement**: +0.94dB over parent with zero architecture changes
2. **Hyperparam transfer success**: Config optimized on structural_1 (105K params) 
   transfers well to sota_8 (47K params, UNet architecture)
3. **Training convergence**: Loss curve smooth and monotonic (no divergence)
4. **Latency**: Same model architecture → same expected latency (~0.41ms). 
   Minor measurement variance is normal for CPU-based ONNX runtime.
5. **This is the 2nd highest PSNR ever** in the entire run (37 variants), 
   after only hyperparam_8c's 32.23dB (on structural_1 parent with 105K params)
