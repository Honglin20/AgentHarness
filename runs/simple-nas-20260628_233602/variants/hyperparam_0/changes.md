# Hyperparam Mutation — iter 0

## Changes from parent (v0 baseline)

| Parameter | Parent (v0) | Ours (hyperparam_0) | Rationale |
|-----------|-------------|---------------------|-----------|
| lr | 0.001 | 0.0003 | Lower learning rate for more stable convergence; 1 order of magnitude below parent |
| batch_size | 64 | 128 | Larger batch for smoother gradient estimates, better GPU utilization |
| epochs | 5 | 5 | Fixed per setup.json; unchanged |
| optimizer | adam | adamw | AdamW decouples weight decay from gradient updates, generally more stable |
| lr_scheduler | steplr | cosine | Cosine annealing provides smooth LR decay, helps converge to better minima |
| warmup_steps | 0 (implied) | 100 | Linear warmup prevents early training instability with larger batch |
| weight_decay | 5e-4 | 1e-4 | Slightly reduced regularization; combined with AdamW this should help |

## Reasoning
- AdamW + Cosine scheduler is a modern, well-proven combination
- Lower LR + larger batch → more stable training dynamics
- Warmup helps the model adapt to the larger batch size
- Model architecture unchanged — only training hyperparams modified
