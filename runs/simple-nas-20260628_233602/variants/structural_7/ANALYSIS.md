# Analysis: structural_7

## Mutation
Decoder channel reduction 32→26 + 1×1 residual projection.

## Results vs Parent (structural_1)

| Metric | Parent | structural_7 | Δ |
|--------|--------|-------------|---|
| PSNR | 29.28 dB | **29.61 dB** | **+0.33 dB** (+1.1%) |
| Latency | 0.415 ms | **0.564 ms** | **+35.8%** |
| Params | 105,236 | **97,220** | **−7.6%** |
| Val Loss | 76.74 | **71.12** | **−7.3%** |
| Train Loss | 85.20 | **76.39** | **−10.3%** |

## Comparison with structural_5 (best structural variant, 31.35dB)

| Metric | structural_5 | structural_7 | Δ |
|--------|-------------|-------------|---|
| PSNR | 31.35 dB | 29.61 dB | −1.74 dB |
| Latency | 0.511 ms | 0.564 ms | +10.4% |
| Params | 100,100 | 97,220 | −2.9% |

## Assessment: Neutral

- PSNR gain is modest (+0.33dB) — far less than structural_5's +2.07dB gain
- Latency increased significantly (+36%) — the 1×1 projection conv offsets the channel reduction benefit
- Params reduction is modest (−7.6%)
- The 1×1 projection (2c→26) adds non-negligible compute: 32*26*8*8 = 53K MACs per forward pass
- In hindsight, the residual projection in structural_5 used a 1×1 conv too (2c→28). With 32→26 being more aggressive, the projection is similar cost but PSNR gain is much lower. Possible reasons:
  - More aggressive channel reduction (26 vs 28) loses too much decoder capacity
  - The SE attention + wider bottleneck in structural_5's config was crucial
  
**Key takeaway**: Decoder channel reduction is effective for latency/params but needs careful tuning — too aggressive (32→26) trades quality for marginal compute savings. The sweet spot seems to be 32→28 (structural_5) with the right residual projection.
