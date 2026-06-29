# Changes: SOTA Variant iter 0 — UNet Architecture

## What Changed

### Architecture: Plain CNN Encoder-Decoder → UNet (Encoder-Decoder + Skip Connections)

**Old (baseline v0):**
- Encoder: 5× Conv2D (5×5, stride 1 or 2), no skip connections
- Decoder: 5× ConvTranspose2D (5×5, stride 1 or 2)
- Power normalization at encoder output
- Channel layer between encoder and decoder

**New (UNet):**
- Encoder: 6 conv blocks (3×3) at 3 spatial scales (32→16→8)
  - conv1 (3→20, stride 1) → down1 (20→40, stride 2) → conv2 (40→40) → down2 (40→80, stride 2) → conv3 (80→80) → bottleneck (80→2c)
  - Store skip connections: s1 (level 0), s2 (level 1)
- Decoder: Upsample by 2× with bilinear interpolation + conv, then fuse with skip
  - up2 (2c→40) → cat(s2) → fuse(80→40) → up1 (40→20) → cat(s1) → fuse(40→20) → out (20→3, sigmoid)

**Preserved (unchanged):** Channel layer, power normalization, input/output interface, loss function

## Rationale

1. **Skip connections let the decoder access fine spatial detail directly**, bypassing the tight bottleneck (2c=32 channels at 8×8). The baseline_understanding explicitly identified this as the primary capacity bottleneck.

2. **3×3 convs replace 5×5 convs** — for the same receptive field, two 3×3 stacks cost fewer params and FLOPs.

3. **Interpolation + conv replaces transposed conv** — avoids checkerboard artifacts and is generally faster (noted as a computation hotspot in baseline_understanding).

4. **Channel counts [20, 40, 80]** keep total params close to baseline (~182K) while enabling deeper feature extraction.

## Expected Benefits
- Higher PSNR from better feature reuse via skip connections
- Better gradient flow during training
- Comparable or lower latency (3×3 convs instead of 5×5, interpolation instead of transposed conv)
