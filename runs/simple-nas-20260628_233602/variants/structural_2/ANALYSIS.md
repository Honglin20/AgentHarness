# structural_2 Analysis

## What Changed
1. **DSConv2d**: All regular 3×3 → depthwise separable (depthwise 3×3 + pointwise 1×1)
2. **Wider channels**: 3→20→40 (was 3→16→32), +25% capacity
3. **ECA attention**: Replaced SE with lighter ECA; added decoder-side ECA

## Training Results
| Metric | Parent (structural_1) | structural_2 | Δ |
|--------|----------------------|--------------|---|
| PSNR | 29.28 dB | 26.91 dB | −2.37 dB |
| Latency | 0.415 ms | 0.807 ms | +0.392 ms (+94%) |
| Params | 105,236 | 23,191 | −78% |

## Analysis
- **PSNR dropped 2.37 dB**: DSConv with only 23K params lacks representational capacity compared to parent's 105K regular convs. Even though channel widths increased by 25%, the depthwise+pointwise decomposition is less expressive per-param than full 3×3 convs.
- **Latency increased 94%**: Contrary to expectation, DSConv is **slower on CPU**. Depthwise convs are memory-bandwidth bound and don't benefit from MKL's optimized GEMM kernels for regular convs. The per-channel processing pattern is cache-unfriendly.
- **ECA overhead**: The adaptive_avg_pool2d + 1D conv adds ~10-20μs.

## Lesson
On CPU-ONNX (macOS), regular 3×3 convs with moderate channel counts outperform depthwise separable variants due to highly optimized MKL/DNNL kernels. DSConv is better suited for mobile/ARM or very high channel counts where the FLOP savings outweigh the memory-bandwidth bottleneck.
