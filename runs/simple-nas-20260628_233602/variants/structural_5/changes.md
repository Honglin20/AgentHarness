# structural_5 — Gentle decoder channel reduction

**Change**: Decoder intermediate channels reduced 32→28 (conv1/conv2/conv3). Decoder conv4 input adjusted from 48ch→44ch (28+16 skip). All other structural_1 elements unchanged.

**Why**: structural_1 (PSNR=29.28, latency=0.415ms) is only 11µs from the 0.404ms target. Previous structural variants (DSConv, ECA, wider encoder) all regressed. The safest path is gentle decoder FLOP reduction (~12.5% in conv1-3) to shave the last microseconds without degrading PSNR. Encoder capacity (3 res_blocks, SE attention) is preserved to maintain representational power.
