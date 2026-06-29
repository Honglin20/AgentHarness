# Hyperparam Combination A — Analysis

## Summary
- **Optimizer**: RMSProp (lr=0.001, momentum=0.0, weight_decay=0)
- **Scheduler**: StepLR (batch_size=32)
- **PSNR**: 31.34 dB
- **Latency**: 0.54 ms (median)
- **Params**: 105,236
- **Epochs**: 5

## Observations
- RMSProp achieves PSNR=31.34 dB, competitive with SGD-based runs.
- Latency is excellent at ~0.54 ms (same model architecture as structural_1).
- Training loss dropped from 296.4 → 51.7, indicating good convergence.
- No warmup and no weight_decay kept training simple.
- StepLR scheduler continues to work well across optimizer choices.

## Verdict
RMSProp is a viable alternative to SGD/Adam for this architecture. The PSNR of 31.34 is solid, and the latency remains low.
