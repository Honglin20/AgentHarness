# structural_3 — ECA attention + compressed skip + decoder ECA

Changes from structural_1 (parent, PSNR=29.28, lat=0.415ms, params=105K):
1. **SEBlock → ECABlock** at encoder bottleneck: two FC layers replaced by a 1D conv (k=3 for 2c=32). ~64 fewer params, O(C) vs O(C²/8) complexity.
2. **Compressed U-Net skip**: Added 1×1 conv (16→8chn) to compress skip features before decoder concatenation. conv4 input 48→40chn, reducing decoder computation ~17%.
3. **Decoder ECA**: Added lightweight ECA after decoder conv3 residual connection for better feature refinement during reconstruction.

Expected: maintained/improved PSNR, slightly lower latency (0.40-0.41ms vs parent 0.415ms).
Params: 103,926 (-1,310, -1.2% vs parent)
