# SOTA Variant Analysis — sota_10 (Ultra-Lightweight UNet 6→12→24)

## Template
**UNet variant — Narrower channels (6→12→24)**

All 9 major SOTA templates exhausted across 10 iterations. Per instructions, returning to best-performing UNet template for channel variants. sota_9 tried wider (10→20→40) → failed. sota_10 tries narrower (6→12→24) to push latency under 0.404ms.

## Results vs Parent (sota_8, Lightweight UNet 8→16→32)

| Metric | Parent (sota_8) | sota_10 | Δ |
|--------|----------------|---------|------|
| PSNR | 30.42 dB | **29.70 dB** | -0.72 dB |
| Latency | 0.4075 ms | **0.4478 ms** | +0.0403 ms (+9.9%) |
| Params | 47,232 | **29,460** | -17,772 (-37.6%) |
| Training time | 117.7s | 119.5s | ~same |

## Assessment: Not promising for latency target

Despite 37.6% fewer parameters, latency **increased** from 0.4075ms to 0.4478ms:
- Smaller tensors → reduced CPU parallelization efficiency → higher relative overhead
- The bottleneck (2c=16 channels at 8×8) stayed the same size, so the main computation didn't shrink proportionally
- The 0.404ms target was not met (currently 0.4478ms, gap of 43.8μs)

PSNR dropped moderately (-0.72dB) to 29.70dB, still well above tolerance (24.65dB) with 5.05dB headroom.

## Key Insight
Channel narrowing in UNet architecture on CPU doesn't proportionally reduce latency due to:
1. Fixed bottleneck size (2c=16 channels at 8×8) dominating computation
2. Smaller intermediate tensors reducing CPU SIMD efficiency
3. Overhead of skip connections and upsampling becoming proportionally larger

## Recommendations
- sota_8 (8→16→32, 0.4075ms) remains the best latency-optimized UNet configuration
- Further latency gains likely need different approach: grouped convolutions, or structural changes to the bottleneck itself
