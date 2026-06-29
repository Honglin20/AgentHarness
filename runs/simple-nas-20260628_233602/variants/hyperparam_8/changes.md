# hyperparam_8 - Hyperparam Mutation

## Parent: structural_1 (psnr=29.28, latency=0.415ms, params=105K)

### What changed
Based on hyperparam history analysis:
- **hyperparam_7** (best=31.45, lat=0.449ms) used Adam+batch=16+lr=5e-4+StepLR
- Going smaller batch (8) for more gradient updates per epoch
- lr scaled proportionally: 5e-4 * (8/16) = 2.5e-4, rounded to 3e-4
- warmup=50 (less needed since fewer total steps per epoch with batch=8)
- Keeping StepLR (proven best scheduler), wd=1e-5, Adam optimizer

### Rationale
Smaller batch sizes have shown consistent improvement in this 5-epoch regime:
batch 128→64→32→16 each improved PSNR (21.79→28.59→31.16→31.45)
Testing whether batch=8 with proportionally scaled lr continues this trend.
