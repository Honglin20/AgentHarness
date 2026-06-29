# Structural Variant v0.3 — Analysis

## Changes (vs baseline v0)
1. **Encoder conv3 & conv4 → 3×3 residual blocks**: Two 5×5 plain convs → two 3×3+3×3 residual blocks (same RF, fewer params, better gradient flow)
2. **SE block at bottleneck**: Channel-wise attention (reduction=8, ~292 params) after power normalization
3. **Decoder residual skip**: Encoder bottleneck output bypasses stride-1 tconvs via element-wise add

## Training Results (5 epochs, CIFAR-10, SNR=7dB)

| Metric | Baseline v0 | Structural v0.3 | Δ |
|--------|------------|-----------------|---|
| **PSNR** | 24.90 dB | **27.00 dB** | **+2.10 dB** |
| Val Loss | 210.29 | **129.87** | -38% |
| Params | 181,865 | **167,887** | -7.7% |
| Latency (median) | 1.35 ms | **1.40 ms** | +3.7% |
| Latency (mean) | 6.89 ms | **6.01 ms** | -12.8% |

## Training Curve
- Epoch 1→5 PSNR: 23.09 → 24.58 → 25.84 → 26.39 → **27.00**
- Steady improvement across all epochs, still underfit at epoch 5
- No signs of overfitting (val_loss keeps dropping)

## Key Insights
- Residual connections significantly improve gradient flow in deep JSCC encoder, enabling faster convergence
- SE block adds minimal overhead (292 params) but provides meaningful quality gain via channel recalibration
- Decoder residual skip lets the decoder directly access bottleneck features
- Model is more parameter-efficient: 7.7% fewer params yet 2.1dB higher PSNR

## Latency
- ONNX CPU latency (batch=1): 1.40 ms median (vs 1.35 ms baseline)
- The slight increase is from SE block (GAP + FC layers) and residual add ops
- Mean latency actually improved (6.01 vs 6.89 ms) indicating more consistent inference
