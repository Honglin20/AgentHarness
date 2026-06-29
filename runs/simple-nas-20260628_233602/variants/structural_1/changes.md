# structural_1 changes

1. **U-Net skip connection**: encoder conv1 output (16ch, 16×16) concatenated to decoder after bilinear upsampling — gives decoder direct access to low-level spatial detail, the key improvement that made sota_0 (UNet) achieve +11.5dB PSNR.
2. **Replaced all 5×5 transposed convs** with bilinear upsampling + 3×3 convs — transposed convs are 2-4× slower, bilinear upsampling is near-free. Also eliminates checkerboard artifacts.
3. **Added 3rd residual block** (res_block3) in encoder for more depth and better gradient flow.
4. **All 5×5 convs → 3×3** (conv1, conv2, conv5) — same receptive field via stacking, ~36% fewer weights per layer, faster inference.
