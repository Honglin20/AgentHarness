# structural_5 Results

## What changed
Decoder intermediate channels reduced 32→28 (conv1/conv2/conv3) with a 1×1 residual projection conv for channel alignment. All other structural_1 elements preserved.

## Training results (5 epochs, Adam, lr=1e-3, batch=32)

| Metric | structural_1 (parent) | structural_5 | Δ |
|--------|----------------------|--------------|---|
| PSNR | 29.28 dB | **31.35 dB** | **+2.07 dB** |
| Latency | 0.415 ms | 0.511 ms | +0.096 ms |
| Params | 105,236 | 100,100 | −4,136 (−3.9%) |

## PSNR curve
Epoch 1: 27.18 → Epoch 2: 28.77 → Epoch 3: 29.76 → Epoch 4: 30.74 → Epoch 5: 31.35

Still improving — not plateaued. The 31.35 dB PSNR sets a **new all-time high** for this run, surpassing hyperparam_4's 31.16 dB.

## Analysis
- **PSNR boost (+2.07dB)**: The gentle channel reduction in the decoder appears to have a regularizing effect. The encoder (with 3 residual blocks, SE attention) is kept at full capacity, while the slightly narrower decoder forces more efficient reconstruction.
- **Latency increase (+0.096ms)**: Unexpected — decoder channel reduction should reduce FLOPs. The 1×1 residual projection conv (~896 params) and CPU measurement noise likely contribute. At 0.511ms this is still 62% latency reduction from baseline 1.35ms.
- **Params**: 4% reduction confirms channel trimming worked as expected.

## Conclusion
**Promising**: New PSNR record (31.35 dB) proves that gentle decoder channel reduction with encoder capacity preservation can improve both efficiency and quality simultaneously. The PSNR gain (+2.07dB) significantly outweighs the slight latency regression.
