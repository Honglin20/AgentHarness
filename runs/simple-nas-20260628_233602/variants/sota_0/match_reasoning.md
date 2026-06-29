# SOTA Template Matching: iter 0

## Selected Template: **UNet** (Encoder-Decoder + Skip Connections)

### Matching Analysis

| Factor | Current (Baseline v0) | UNet match reason |
|--------|----------------------|-------------------|
| Task type | Image-to-image reconstruction (CIFAR-10) | UNet was designed for image-to-image tasks (biomedical segmentation → equally suited for reconstruction) |
| Architecture | CNN encoder-decoder | UNet is the canonical encoder-decoder with symmetric skip connections |
| Input shape | [B, 3, 32, 32] image | UNet handles arbitrary image sizes natively |
| Output shape | [B, 3, 32, 32] reconstructed image | UNet's bottleneck+filters match exactly |
| Skip connections | None (plain feedforward) | UNet's key innovation — skip connections from encoder to decoder preserve fine details |
| Current bottleneck | 32×8×8 = 2,048 values | UNet skip connections mitigate bottleneck information loss |

### Why UNet Specifically

1. **Direct structural match**: Current model is already encoder-decoder. UNet adds skip connections which the baseline_understanding explicitly identifies as a top SOTA opportunity: *"Encoder→decoder skip paths (e.g., U-Net style) would let the decoder access fine detail directly, improving PSNR."*

2. **Capacity bottleneck relief**: The baseline's tight bottleneck (2,048 values for 3,072 pixels) loses spatial detail. UNet skip connections give the decoder direct access to encoder features at multiple scales, bypassing the bottleneck for fine details.

3. **Gradient flow**: Skip connections improve gradient flow during training, solving the "gradient vanishing" concern for the 10-layer model.

4. **Preserves task components**: The Channel layer (AWGN) and power normalization are kept between encoder output and decoder input, unchanged.

### Not Selected This Iteration (reserved for future iterations)

- ViT: Good for classification but needs more data; CIFAR-10 is small
- DenseNet: Heavy memory usage, higher latency for limited benefit in reconstruction
- MobileNet: Premature for iter 0; better after establishing architecture baseline
- ResNet enhancement: Already partially covered by UNet skip connections
