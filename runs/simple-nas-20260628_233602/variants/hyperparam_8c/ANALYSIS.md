# hyperparam_8 — Hyperparameter Mutation

## Parent: structural_1 (PSNR=29.28, latency=0.415ms, params=105K)

## Configurations Tested

### Main: hyperparam_8 (batch=8, lr=3e-4, Adam, StepLR)
- PSNR=31.81 (+2.53dB vs parent)
- Latency: similar to parent structural_1 (~0.5ms)
- Analysis: Smaller batch (8) with proportionally scaled lr (3e-4) gives solid improvement (31.81). 
  More gradient updates per epoch benefit the 5-epoch regime. #2 best in this round.

### Sub-agent 1: hyperparam_8b (RMSProp, batch=16, lr=5e-4, StepLR)
- PSNR=31.14 (+1.86dB vs parent)
- Analysis: RMSProp works and converges well, PSNR matches the Adam+StepLR plateau (~31.15-31.20).
  First successful RMSProp trial in the experiment. Not better than Adam though.

### Sub-agent 2: hyperparam_8c (Adam, batch=16, lr=8e-4, CosineAnnealing, warmup=150) — BEST
- PSNR=32.23 (+2.95dB vs parent) — **NEW ALL-TIME RECORD**
- Latency=0.5045ms (consistent with structural_1's architecture, hyperparams don't affect latency)
- Analysis: CosineAnnealing scheduler with lr=8e-4 + extended warmup=150 produces the best 
  result ever seen in this NAS experiment (32.23dB). The key insight is that CosineAnnealing
  with proper warmup allows higher lr (8e-4 vs 5e-4) without divergence, reaching lower 
  final loss. The warmup=150 steps smooths the initial learning phase.

## Key Takeaway
CosineAnnealing + warmup=150 + lr=8e-4 is the superior hyperparam configuration for 
structural_1, beating all previous StepLR/ReduceLROnPlateau/OneCycle attempts. 
This confirms that scheduler choice matters significantly even in 5-epoch training.
