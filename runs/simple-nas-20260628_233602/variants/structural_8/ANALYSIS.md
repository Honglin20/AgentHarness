# structural_8 — Training Result Analysis

## Changes Applied
1. **Decoder channels 32→28 + 1×1 residual projection** (structural_5's proven PSNR booster)
2. **Encoder conv1 16→14** (capacity redistribution to offset latency)
3. Adjusted skip connection channels and decoder conv4 accordingly

## Results vs Parent (structural_1)
| Metric | Parent | structural_8 | Change |
|--------|--------|-------------|--------|
| PSNR | 29.28 dB | 29.25 dB | −0.03 dB (within 1% tolerance) |
| Latency | 0.415 ms | 0.486 ms | +17% |
| Params | 105,236 | 98,368 | −6.5% |

## Training Curve
- Epoch 1→5 loss: 523→83 (steady convergence, no divergence)
- PSNR progression: 24.98→26.99→27.93→28.56→29.25 (still improving)

## Analysis
- PSNR essentially unchanged from parent (−0.03dB, well within 1% tolerance)
- Latency increased 17% (0.415→0.486ms), moving further from target 0.404ms
- Encoder conv1 reduction (16→14) did NOT offset the decoder projection overhead as hoped
- Compared to structural_5 (same decoder change, parent structural_1): structural_5 got 31.35dB at 0.511ms, while structural_8 got 29.25dB at 0.486ms. The encoder conv1 reduction hurt PSNR significantly more than expected
- **Lesson**: The encoder conv1 skip features (16ch) are important for PSNR quality. Reducing them to 14ch cost ~2dB without commensurate latency benefit

## Conclusion
Not promising — PSNR flat but latency regressed. The capacity redistribution (encoder conv1 16→14) degraded PSNR without enough latency compensation. The structural_5 approach (decoder 32→28 with encoder untouched, PSNR 31.35) remains the best structural variant on this parent.
