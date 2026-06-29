# sota_9 Analysis

## Template Used
**UNet variant** with wider channels (10→20→40) — building on sota_8's lightweight UNet (8→16→32)

## Results vs Parent (sota_8)

| Metric | sota_8 (parent) | sota_9 (this) | Change |
|--------|----------------|---------------|--------|
| PSNR | 30.42 dB | 29.55 dB | -0.87 dB |
| Latency | 0.4075 ms | 0.4267 ms | +4.7% |
| Params | 47,232 | 69,036 | +46.2% |

## Analysis

**PSNR decreased** despite wider channels. This likely reflects:
1. **More params need more epochs**: The +46% wider channels give more capacity but the fixed 5-epoch training doesn't let the model converge with the extra parameters
2. **Loss trend**: At epoch 5, train_loss=77.57 is still dropping — the model is underfitting, not overfitting
3. **Parent sota_8 had a near-optimal channel balance**: The 8→16→32 configuration achieved the best efficiency-quality trade-off for 5-epoch training

**Latency stayed close**: Only +4.7% (0.4075→0.4267ms) despite +46% params, likely because:
- The bottleneck (2c=32 channels) and spatial dimensions (8×8) stayed the same
- Most latency is in the upsample/conv at higher resolutions (16×16, 32×32) which changed less dramatically
- ONNX runtime handles the extra channels efficiently

## SOTA Direction Status
- This is the 9th iteration of sota direction
- UNet variants: sota_0 (20→40→80, PSNR=36.4, lat=9.99ms), sota_8 (8→16→32, PSNR=30.42, lat=0.4075ms), sota_9 (10→20→40, PSNR=29.55, lat=0.4267ms)
- The 8→16→32 configuration (sota_8) remains the best UNet variant and the closest to target latency
- sota_8's parent (structural_1) continues to be a strong foundation at PSNR=29.28, lat=0.415ms
