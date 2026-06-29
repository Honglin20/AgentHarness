# Hyperparameter Changes — Adam + batch=16 + lr=5e-4

| Parameter | Structural 1 (Parent) | Hyperparam 7b (Ours) | Rationale |
|-----------|----------------------|---------------------|-----------|
| optimizer | SGD | Adam | Adam provides adaptive per-parameter learning rates, often more stable and faster convergence for vision tasks. |
| batch_size | 32 | 16 | Halving batch size doubles gradient updates per epoch, allowing more frequent weight updates and better generalization. |
| lr | 1e-3 | 5e-4 | Moderate reduction to compensate for Adam's adaptive nature and the smaller batch size (which increases update frequency). |
| warmup_steps | 0 | 100 | Gradual warmup over 100 steps helps stabilize Adam's adaptive moment estimates early in training. |
| weight_decay | 0 | 1e-5 | Minimal L2 regularization to prevent overfitting on small datasets without overwhelming the loss. |
| lr_scheduler | — | StepLR | StepLR scheduler has proven best on this parent architecture, reducing LR at fixed intervals for steady convergence. |
| momentum | 0.9 | 0.9 | Retained same momentum (used by Adam internally as beta1). |
