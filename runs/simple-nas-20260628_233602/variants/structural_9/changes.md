# structural_9: Changes from parent sota_8

## 1. ECA at decoder output before final conv
**What**: Added Efficient Channel Attention (_ECABlock) after upsample and before the final conv layer in the decoder.
**Why**: ECA is lighter than SE — uses a 1D conv (k=3, adaptive) + sigmoid instead of FC layers. Provides channel recalibration at the decoder output where fine spatial detail reconstruction matters most. Near-zero latency overhead.

## 2. Feature-level residual within decoder level 3
**What**: Added a 1×1 conv projection from conv_d3a output → added to conv_d3b output (within same 8×8 spatial resolution).
**Why**: Improves gradient flow within the decoder without bypassing the encoder or channel noise. The residual operates at the same feature level (inside the decoder path), helping optimization while still requiring the model to learn meaningful compression. Near-zero latency cost (1 addition + 1×1 conv).

## 3. GELU activation in _ResidualBlock
**What**: Replaced PReLU with GELU in the encoder residual block.
**Why**: GELU provides smoother gradient flow and often gives slightly better quality for vision tasks, at identical compute cost at inference.
