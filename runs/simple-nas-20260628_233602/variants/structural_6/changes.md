# structural_6 changes

## What changed
1. **Encoder conv1 channels: 3→16→14** — reduced first-layer width, smaller skip features (14ch instead of 16ch)
2. **Decoder conv1-3 channels: 32→28** — internal decoder capacity reduction (proven by structural_5)
3. **Decoder residual removed** — structural_5's 1×1 projection added latency (+23%), so removed entirely
4. **conv4 input channels adjusted: 48→42** (28 decoder + 14 skip instead of 32+16)

## Why
Parent structural_1 (PSNR=29.28, latency=0.415ms) is closest to 0.404ms target (11μs away). Channel reduction lowers params naturally → lower latency. Removing decoder residual avoids the 1×1 projection overhead that plagued structural_5.

## Parameters
structural_6: 98,256 params (vs parent 105,236 — 6.6% reduction)
