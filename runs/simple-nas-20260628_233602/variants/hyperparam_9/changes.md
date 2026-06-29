# hyperparam_9: Apply best-ever hyperparams to sota_8 (Lightweight UNet)

## Parent: sota_8
- Lightweight UNet (3-level, channels 8→16→32, 47K params)
- PSNR=30.42, latency=0.4075ms (only 3.5μs from target 0.404ms!)
- Built on structural_1 backbone + UNet architecture with channel reduction

## What changed (hyperparams)
- **lr**: 1e-3 → 8e-4 (proven best by hyperparam_8c, which achieved PSNR=32.23 on structural_1 parent)
- **batch_size**: 64 (initial) → 16 (proven best for 5-epoch training)
- **optimizer**: adam → adam (unchanged, Adam confirmed best in 6+ trials)
- **lr_scheduler**: steplr → cosine (CosineAnnealing with warmup was the #1 best config)
- **warmup_steps**: 0 → 150 (longer warmup allows slightly higher lr to converge in 5 epochs)
- **weight_decay**: 5e-4 → 0 (wd=0 was best across multiple hyperparam trials)
- **epochs**: 5 (unchanged, fixed by setup.json)

## Strategy rationale
- This is the first time we apply the hyperparam_8c record-breaking hyperparams 
  (CosineAnnealing + lr=8e-4 + warmup=150 + batch=16) to a non-structural_1 parent
- sota_8 has only 47K params vs structural_1's 105K → different dynamics expected
- The UNet architecture with skip connections may respond differently to lr scheduling
- Model.py is **unchanged** (direct copy of sota_8)
