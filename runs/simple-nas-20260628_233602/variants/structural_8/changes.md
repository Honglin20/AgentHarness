# structural_8 — Balanced capacity redistribution

**Changes from structural_1 (parent, PSNR=29.28, latency=0.415ms, params=105K):**

1. **Decoder channels 32→28 + 1×1 residual projection** — structural_5 proved this achieves +2.07dB PSNR (31.35dB) by reducing decoder redundancy while adding a projection for channel-aligned residual. Latency increased 23% in structural_5 (0.415→0.511ms).

2. **Encoder conv1 16→14** — balanced capacity redistribution to offset the decoder projection's latency impact. Reduces first-layer FLOPs (~12.5%) while keeping deep encoder capacity (3 res_blocks, SE bottleneck) intact.

3. **Adjusted skip connection** — conv1 output 14ch (was 16ch). Decoder conv4 input: 28+14=42ch→14ch output (was 48→16). Final conv5: 14→3 (was 16→3).

**Why**: structural_5's decoder reduction achieved the highest structural PSNR ever (31.35dB) but added 23% latency (0.511ms). By pairing it with a mild encoder first-layer channel reduction (16→14), we aim to keep latency closer to 0.415ms while capturing most of the PSNR benefit. The deep encoder (res_blocks, bottleneck SE) is untouched to maintain representational power.
