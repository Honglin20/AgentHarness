# structural_4 — Analysis

## Summary
Wider encoder input stage (conv1: 3→20, conv4: 52→20, conv5: 20→3) for capacity
redistribution toward early feature extraction.

## Results
| Metric | structural_4 | structural_1 (parent) | Δ |
|--------|-------------|----------------------|---|
| PSNR | 29.15 dB | 29.28 dB | -0.13 dB (-0.44%) |
| Val Loss | 78.99 | 76.74 | +2.9% |
| Train Loss | 81.26 | N/A | - |
| Params | 109,060 | 105,236 | +3,824 (+3.6%) |
| Latency (median) | 0.475 ms | 0.415 ms | +14.5% |

## Interpretation
- PSNR closest to parent among all structural_4 attempts (GELU: 28.96, SE+residual: 29.00, identity_only: 28.82, wider_encoder: 29.15)
- Wider encoder provides more capacity at input stage (+25% channels on first conv) and wider skip pathway
- Loss curve still dropping at epoch 5 — underfit, not overfit. More epochs would push PSNR higher
- Latency increase (+14.5%) from extra channels propagating through downstream layers

## Next Steps for Selector
- Consider structural_4 as parent for next iteration with hyperparam tuning (lower LR, cosine scheduler)
- The wider encoder + wider skip pathway could be combined with channel pruning at residual blocks to recover latency
- GELU activation showed promise (28.96) but caused excessive ONNX CPU latency — may be viable on GPU
