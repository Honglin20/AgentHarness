# structural_2 Changes

## What changed

1. **Kernel operator replacement**: All regular 3×3 convolutions → Depthwise Separable (DSConv2d: depthwise 3×3 + pointwise 1×1 + PReLU each). Saves ~7× params and ~8× FLOPs per conv layer while maintaining representational power.

2. **Channel dimension increase**: conv1 3→20 (was 3→16, +25%), conv2 20→40 (was 16→32, +25%), res_blocks 40ch (was 32ch, +25%) — wider front-end captures more spatial detail before aggressive stride-2 pooling.

3. **Attention module swap**: SE (Squeeze-Excitation) → ECA (Efficient Channel Attention) in bottleneck. ECA uses 1D conv (k=3, kernel adapted per channel count) instead of FC layers — ~10 params vs ~200, negligible overhead with comparable channel recalibration.

4. **Decoder-side attention added**: ECA block inserted after decoder conv3 for decoder-side channel recalibration — complements the encoder bottleneck attention.

## Rationale

Parent structural_1 already achieves target latency (0.415ms vs 0.404ms target, only 11μs off). The remaining gap is representational capacity. DSConv frees enough compute budget to widen channels by 25% AND add decoder-side attention without increasing latency. ECA is chosen over SE for its extreme efficiency (no params bottleneck from reduction ratio).
