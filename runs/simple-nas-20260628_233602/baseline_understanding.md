# Baseline v0 Understanding

## Model Overview

**Architecture**: DeepJSCC — a convolutional encoder-decoder for joint source-channel coding.

| Component | Layers | I/O Channels | Kernel | Params |
|-----------|--------|-------------|--------|--------|
| Encoder | 5× Conv2D + PReLU | 3→16→32→32→32→2c | all 5×5 | ~91K |
| Normalization | Power norm (reshape + bmm) | — | — | 0 |
| Channel | AWGN noise (SNR=7.0) | — | — | 0 |
| Decoder | 5× ConvTranspose2D + PReLU/Sigmoid | 2c→32→32→32→16→3 | all 5×5 | ~91K |
| **Total** | | | | **181,865** |

- **c=16** (computed by `ratio2filtersize` with ratio=1/6, ×2.0 multiplier → c=16)
- **Bottleneck**: encoder output has **2c=32 channels** of 8×8 spatial feature maps
- **Metric**: PSNR=24.90 dB after 5 epochs (still improving — not converged)

## Capacity Bottlenecks

1. **Encoder output (bottleneck layer)** — `_Encoder.conv5` reduces to `2*c` channels. With c=16, the encoded representation is only 32×8×8 = 2,048 values for a 3×32×32 = 3,072-pixel input. This tight bottleneck is the primary capacity constraint. Increasing c directly improves representational power.

2. **No residual connections** — The model is a plain feedforward stack. Neither encoder nor decoder has skip connections, limiting gradient flow and making deeper variants harder to train.

3. **Single-scale processing** — All convs are 5×5 with stride 1 or 2. No multi-scale (inception-style) or dilated conv processing, so fine-grained spatial details may be lost.

## Computation Hotspots

1. **5×5 convolutions** — Every conv layer uses kernel_size=5. For the same parameter budget, two 3×3 convs are cheaper and deeper. The first conv (3→16, 5×5 stride 2) is the most expensive per-channel.

2. **Transposed convolutions** — The decoder has 5 transposed conv layers, all 5×5. Transposed convs are typically 2-4× slower than equivalent regular convs due to the "scatter" memory access pattern. tconv5 (16→3, stride 2) and tconv4 (32→16, stride 2) are the most expensive.

3. **Normalization layer** — Uses `torch.bmm` inside `_normlizationLayer` (reshape to B×1×1×K, then batch matmul). For batch_size=64, this is a small overhead but does involve a large intermediate tensor (64×1×2048×2048).

4. **Channel simulation** — The `Channel` module (AWGN) is near-zero cost; it just adds Gaussian noise.

## SOTA Opportunities

### Structural improvements (for `mutator_structural`)
- **Replace 5×5 convs with 3×3 + 3×3 stacks**: Each 5×5 conv has 25 weights vs 9+9=18 for two 3×3 convs. Saves ~28% FLOPs with same receptive field.
- **Add residual/skip connections**: Encoder→decoder skip paths (e.g., U-Net style) would let the decoder access fine detail directly, improving PSNR.
- **Depthwise separable convs**: Replace regular convs with depthwise + pointwise to reduce FLOPs by 4-8× with small quality loss.
- **Replace transposed convs with interpolation + conv**: `nn.Upsample` (nearest/bilinear) followed by 3×3 conv is often faster and reduces checkerboard artifacts.

### Hyperparameter tuning (for `mutator_hyperparam`)
- **Learning rate**: Current lr=1e-3 with no scheduler. Adding cosine decay or step-LR may improve convergence.
- **Bottleneck multiplier**: The current 2.0× multiplier gives c=16. Reducing to 1.0× would cut params significantly but may drop PSNR.
- **Ratio**: The `ratio` parameter (currently 1/6) controls bottleneck size directly. Increasing to 1/4 would give a larger bottleneck and higher PSNR but also more params.

### Advanced techniques (for `mutator_sota`)
- **Attention in bottleneck**: Insert a lightweight self-attention (e.g., ECA, SE-block, or Axial Attention) at the encoder output to improve compression efficiency.
- **Quantization-aware training**: QAT can reduce model size 4× with <0.5 dB PSNR drop, directly reducing latency.
- **Knowledge distillation**: Train a smaller student model using baseline v0 as teacher.
- **Mixed-precision / INT8 inference**: ONNX+ORT already supports this for 2-4× speedup.
- **Different normalization**: Replace the custom power norm with LayerNorm or BatchNorm for better training stability and possible ONNX simplification.

## Training Trajectory

| Epoch | Train Loss | Val Loss | PSNR (dB) |
|-------|-----------|---------|-----------|
| 1 | 783.63 | 441.23 | 21.68 |
| 2 | 368.81 | 309.21 | 23.23 |
| 3 | 287.33 | 261.51 | 23.96 |
| 4 | 248.54 | 242.84 | 24.28 |
| 5 | 221.72 | 210.29 | 24.90 |

- Loss is still dropping rapidly at epoch 5 → model is **underfit**, not overfit.
- More epochs would improve PSNR, but for NAS comparison the relative ranking between variants is already meaningful.
- Latency: **1.35 ms** (ONNX, CPUExecutionProvider, batch=1, 100 runs)
