# structural_7 changes

1. **Decoder channel reduction 32→26**: Decoder conv1/conv2/conv3 channels reduced from 32 to 26 (18.75% reduction). conv4 input channels reduced from 48→42 (26+16). This directly reduces decoder computation while preserving encoder quality.
2. **1×1 projection conv for residual matching**: Added lightweight 1×1 conv (858 params, 32→26 channels) to project the decoder residual identity to matching channel count. Fixes shape mismatch when decoder channels differ from bottleneck channels.
3. **All residual blocks kept**: res_block1/2/3 retained — critical for gradient flow in 5-epoch training.
4. **SE attention at bottleneck kept**: Already present in parent — lightweight channel recalibration.

Rationale: structural_5 proved decoder channel reduction (+1×1 projection) works (+2.07dB PSNR). By reducing channels more aggressively (32→26 vs 32→28) we aim for similar PSNR gain with lower compute.
