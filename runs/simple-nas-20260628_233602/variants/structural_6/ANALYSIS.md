# structural_6 Analysis

## What changed
| Change | Before | After |
|--------|--------|-------|
| Encoder conv1 channels | 3→16 | 3→14 |
| Decoder conv1-3 channels | 32→32→32 | 28→28→28 |
| Decoder residual | identity skip after conv3 | removed |
| conv4 input | 48ch (32+16) | 42ch (28+14) |
| **Total params** | **105,236** | **98,256 (-6.6%)** |

## Training results vs parent (structural_1)

| Metric | Parent | structural_6 | Δ |
|--------|--------|-------------|---|
| PSNR | 29.28 dB | 29.16 dB | −0.12 dB (−0.41%) |
| Val loss | 76.74 | 78.84 | +2.10 |
| Params | 105,236 | 98,256 | −6.6% |
| Latency (median) | 0.415 ms | 0.494 ms | +19% |

## Analysis
- **PSNR**: −0.12 dB (−0.41%) — within the 1% tolerance but still a slight regression. The decoder residual removal likely caused the small quality drop.
- **Latency**: Increased to 0.494ms (+19%). Despite 6.6% fewer params, the model is slower. Possible explanations:
  1. CPU measurement variance (min latency ~0.42ms close to parent's 0.415ms)
  2. The decoder conv4 at 42ch input is still a bottleneck
  3. Removing the residual doesn't help much — CPU cares more about memory bandwidth and kernel launch overhead than MAC count
- **Params**: 98,256 (−6.6%) — reduction confirmed but didn't translate to latency improvement

## Verdict
**Not promising** — latency increased (+19%) while PSNR slightly dropped. The channel reduction alone cannot shave the final 11μs off 0.415ms. Future structural attempts should consider different approaches (e.g., more aggressive channel reduction at the decoder conv4, removing SE block, or reducing residual block count from 3→2).
