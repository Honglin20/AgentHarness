# SOTA_6 Analysis — ResNet Bottleneck Enhancement

## Template: ResNet (Bottleneck Residual Blocks)

### Results
| Metric | Parent (structural_1) | SOTA_6 | Change |
|--------|----------------------|--------|--------|
| PSNR | 29.28 dB | **30.79 dB** | **+1.51 dB (+5.2%)** |
| Latency | 0.415 ms | **0.564 ms** | +36% |
| Params | 105,236 | **54,490** | **-48.2%** |

### Assessment: Promising

**PSNR**: Strong improvement (+1.51dB, +5.2%). ResNet bottleneck blocks effectively improve
gradient flow and representation quality. The 4× bottleneck blocks (each with 1×1→3×3→1×1
structure) add more non-linearity and depth without increasing params.

**Params**: Nearly halved (54K vs 105K). The bottleneck design (channels/4 in middle layer)
is extremely parameter-efficient. This is the lowest-parameter variant so far.

**Latency**: Increased 36% (0.415→0.564ms). The BatchNorm layers in bottleneck blocks add
overhead on CPU. Each bottleneck block has 3×BN layers, and with 4 blocks that's 12×BN layers
which collectively slow down inference.

### Why this matters
- 54K params achieving 30.79 PSNR is very efficient (best PSNR/param ratio)
- The BN layers could potentially be folded during ONNX optimization (constant folding)
- Removing BN (replacing with PReLU-only like parent) would reduce latency at some PSNR cost

### Next step hint
If continuing this direction: try removing BN from bottleneck blocks (use PReLU only like
parent structural_1 does), which should reduce latency while keeping most of the PSNR gain.
Or try reducing from 4 to 2 bottleneck blocks.
