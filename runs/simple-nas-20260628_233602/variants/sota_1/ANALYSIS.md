# SOTA Iter 1: DenseNet Architecture — Analysis

## Template Used
**DenseNet-style dense connectivity** (CNN variant,轮转策略 #2)

## Match Reasoning
DenseNet's dense connections maximize feature reuse — each layer gets ALL previous feature maps as input. This is fundamentally different from:
- **UNet** (tried in iter 0): Uses spatial skip connections between encoder and decoder
- **structural_0 (parent)**: Has only 2 residual blocks in encoder

## Changes Made
- Replaced encoder: initial 5×5 conv → 2× DenseBlocks (4 layers, growth=12) with transitions → bottleneck → power norm
- Replaced decoder: initial conv → 3× DenseBlocks (4/4/3 layers) with bilinear upsampling → output conv
- Removed all 5×5 transposed convs (replaced by upsample+conv)
- Preserved: Channel layer, power normalization, DeepJSCC interface

## Results vs Parent (structural_0)

| Metric | Parent (structural_0) | DenseNet (this) | Δ |
|--------|----------------------|-----------------|---|
| PSNR | 27.00 dB | **22.84 dB** | **−4.16 dB** |
| Params | 167,887 | **163,228** | −2.8% |
| Latency (CPU) | 1.40 ms | **19.79 ms** | +14× |

## Analysis

### PSNR: Worse than parent (−4.16 dB)
- The DenseNet architecture did NOT converge well. The loss curve shows instability (epoch 5 loss spiked to 827.9 from 350.2).
- Possible causes:
  1. **No BatchNorm**: Standard DenseNet uses BN before each conv. Our model lacks BN (following the original DeepJSCC design which doesn't use BN). DenseNet without BN is known to be unstable.
  2. **Learning rate mismatch**: The default lr=0.001 may be too high for this deeper architecture (20 conv layers in DenseBlocks alone).
  3. **Dense connectivity without normalization**: The concatenation of features from different layers creates covariate shift that BN normally handles.
- The training was underfitting (loss still decreasing at epoch 4), then diverged (epoch 5 spike).

### Latency: Much worse (+14×)
- DenseNet's concatenation operations create large intermediate tensors (up to 96 channels at 8×8 → concatenation of all 5 layers' outputs).
- The 5× DenseBlocks (19 conv layers total) create a very deep computation graph.
- Memory bandwidth bottleneck: The `torch.cat` operations are memory-intensive.
- CPU-only measurement may exaggerate the gap; on GPU the relative difference may be smaller.

### Parameters: Similar (−2.8%)
- Despite having 19 conv layers vs parent's ~12, the growth_rate=12 keeps individual layers narrow.
- Parameter count is comparable, but FLOPs are much higher due to concatenation-heavy operations.

## Verdict
**Dead direction (current config)** — DenseNet-style architecture without BN/ LayerNorm doesn't work well for image reconstruction at lr=0.001 with 5 epochs. The training instability and high latency make this unsuitable in its current form.

## Lessons for Future Iterations
1. If retrying DenseNet, add BN before each dense layer (standard DenseNet practice)
2. Lower learning rate (e.g., 3e-4) for deeper architectures
3. Reduce growth_rate (e.g., 8) to lower concatenation overhead
4. Consider fewer layers per block (e.g., 2 instead of 4)
