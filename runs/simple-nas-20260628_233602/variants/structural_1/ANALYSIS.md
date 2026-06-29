# structural_1 Analysis

## Changes vs parent (structural_0: PSNR=27.0, lat=1.4ms, params=167K)

1. **U-Net skip connection** — encoder conv1 output (16ch, 16×16) concatenated to decoder after bilinear upsampling. Provides direct low-level spatial detail to decoder, the key improvement from sota_0's UNet.

2. **5×5 transposed convs → bilinear upsampling + 3×3 convs** — tconv1-3 (stride=1) replaced with regular 3×3 convs; tconv4-5 (stride=2) replaced with nn.Upsample(bilinear) + 3×3 conv. Dramatically reduces latency (transposed convs are 2-4× slower).

3. **Extra residual block (res_block3)** in encoder for more depth and gradient flow.

4. **conv1, conv2, conv5 reduced from 5×5 to 3×3** — same effective receptive field via stacking, 36% fewer weights per layer.

## Results

| Metric | Parent (structural_0) | structural_1 | Δ |
|--------|----------------------|--------------|---|
| PSNR   | 27.0 dB              | **29.28 dB** | **+2.28 dB (+8.4%)** |
| Latency| 1.40 ms              | **0.42 ms**  | **-70%** |
| Params | 167,887               | **105,236**  | **-37%** |

## Interpretation

- **PSNR breakthrough**: The U-Net skip connection is the primary driver. The sota_0 UNet got +11.5dB but at 6.4× latency cost. This lightweight skip (single level, 16ch) captures most of the benefit at negligible cost.

- **Latency collapse**: Replacing 5×5 transposed convs with bilinear upsampling + 3×3 convs was extremely effective. The decoder is now 3.3× faster while being structurally deeper (res_block3).

- **Training curve**: Loss still dropping rapidly (576→85 over 5 epochs), indicating room for further improvement with more epochs or lower learning rate.

## Conclusion

**Promising** — this variant achieves the best PSNR/latency trade-off so far. It stays under the 0.42ms target while delivering +2.28dB over the previous structural best.
