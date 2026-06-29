# Hyperparam Variant: CosineAnnealing with higher lr + extended warmup

This variant tests **CosineAnnealing** learning rate scheduler with:
- **lr**: 8.0e-4 (between 5e-4 and 1e-3 — a moderate-to-high learning rate)
- **warmup_steps**: 150 (extended warmup to stabilize training before cosine decay kicks in)
- **optimizer**: Adam (with momentum=0.9, weight_decay=1e-5)
- **batch_size**: 16, **epochs**: 5

The idea is that a higher learning rate paired with a longer warmup and cosine annealing may allow the model to converge faster and avoid getting stuck in sharp minima early on.
