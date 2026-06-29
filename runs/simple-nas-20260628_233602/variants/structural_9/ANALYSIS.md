# structural_9 Analysis

## Changes
1. **ECA at decoder output** — lightweight Efficient Channel Attention before final conv
2. **Feature-level residual in decoder level 3** — 1×1 conv projection + addition within decoder
3. **GELU in encoder _ResidualBlock** — replacing PReLU

## Training
- Best PSNR: 27.23 dB (vs parent sota_8: 30.42 dB)
- Params: 47,489 (vs parent: 47,232 — slightly more due to ECA + residual projection)
- Loss still dropping at epoch 5 (not converged)
- CosineAnnealing scheduler with lr=8e-4, warmup=150, batch=16

## Latency
- Median: 0.470 ms (vs parent: 0.4075 ms)
- Target: 0.404 ms
- Delta from target: +0.066 ms (+16.3%)

## Assessment
PSNR drop (-3.19 dB) and latency increase (+15%) compared to parent. The structural changes (ECA, feature-level residual, GELU) did not improve over the parent sota_8's baseline. Possible reasons:
1. The parent sota_8 is already very optimized (47K params, 0.4075ms) — further architectural modifications add compute without quality gain
2. ECA on a 16-channel feature map may not provide meaningful recalibration (too few channels)
3. Feature-level residual within decoder may compete with existing UNet skip connections
4. CosineAnnealing with lr=8e-4 may not be optimal for this architecture
