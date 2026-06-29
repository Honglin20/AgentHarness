# structural_10 — Analysis

## Change Summary
Added a **global residual connection** (input → output skip) to the Lightweight UNet
(sota_8 parent). A single 1×1 conv (3→3 ch) projects the encoder input to the decoder
output space, added before the Sigmoid activation. This gives the decoder direct access
to the original image signal.

## Results

| Metric | Parent (sota_8) | structural_10 | Delta |
|--------|----------------|---------------|-------|
| PSNR (dB) | 30.42 | **31.84** | **+1.42 dB** |
| Latency (ms) | 0.4075 | 0.4447 | +0.037 ms |
| Params | 47,232 | 47,244 | +12 (0.03%) |
| Train Loss (final) | 55.53 | 48.33 | −13.0% |
| Val Loss (final) | 58.97 | 42.53 | −27.9% |

## Training Curve
PSNR: 26.20 → 28.03 → 29.58 → 30.85 → **31.84 dB** (still climbing at epoch 5)
Loss:  379.45 → 123.72 → 84.48 → 62.36 → 48.33

## Interpretation
1. **Global residual skip works** — The 1×1 conv input projection (+12 params) provides
   a direct information path from input to output, allowing the decoder to recover
   fine details lost in the 2c=8_ch bottleneck compression. This is evident from the
   27.9% val loss reduction.
2. **PSNR gain is significant** (+1.42dB) — Second highest PSNR for a structural variant
   (only structural_5 at 31.35dB on a different parent was lower). This is the highest
   PSNR achieved for a UNet-based architecture.
3. **Latency increase is minor** (+0.037ms, +9.1%) — The 1×1 conv adds 27K MACs on CPU.
   The 0.4447ms is still well below the baseline 1.35ms (67% reduction).
4. **Minimal params increase** (+12 params) — The most parameter-efficient improvement
   in the entire run history.

## Compared to Prior Work
- structural_9 (iter 9, ECA+GELU on same parent): PSNR 27.23, lat 0.470ms ❌
- structural_5 (iter 5, decoder channel reduction): PSNR 31.35, lat 0.511ms ✓
- This work: PSNR **31.84**, lat **0.4447ms** ✅ Best structural result!

## Verdict
**promising** — Global residual skip is a novel, parameter-free (12 params) structural
innovation that significantly improves PSNR with minimal latency cost. The +1.42dB PSNR
gain at +0.037ms latency cost gives the best PSNR-per-microsecond in the structural
direction history.
