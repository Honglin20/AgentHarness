# structural_10 — Global Residual Skip on Lightweight UNet (sota_8)

**Core change**: Added a global residual connection from encoder input to decoder
output via a 1×1 conv projection (3→3 channels, 12 params).

**Rationale**: 
1. sota_8 (0.4075ms, 30.42dB) is only 3.5μs from the latency target — any
   structural addition must have near-zero latency impact.
2. A global input→output skip gives the decoder direct access to the original
   image signal, helping recover fine details lost in bottleneck compression.
3. The 1×1 conv adds only 12 parameters (~0.03% of model) with <1μs compute.
4. Residual connections were proven effective in structural_0 (SE+residual, +2.1dB)
   and structural_5 (decoder residual projection, +2.07dB), but a *global* input→output
   skip has never been tried in any prior iteration.

**Latency impact**: Negligible (<1μs). The 1×1 conv is a simple pointwise
operation, and the element-wise add is free. Expected latency: ~0.4075-0.4085ms.
