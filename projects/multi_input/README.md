# Multi-Input Test Project (forward(x1, x2))

Stress-tests the NAS workflow's handling of **multi-argument forward** signatures.

## Why this project?
- The workflow helpers default to single-tensor `model(x)` contracts.
- This project's `MultiInputMLP.forward(x_a, x_b)` takes **two separate tensors**.
- Tests: how the workflow's train/eval/benchmark commands and (eventually) ONNX export handle multiple inputs.

## Data
sklearn digits (1797 samples, 64 features, 10 classes). Each sample's 64 features are split into two halves:
- `x_a`: first 32 features
- `x_b`: last 32 features

Each branch processes one half; outputs are fused via concat / sum / mul.

## Configurable architecture
- `hidden_dim`: 32 / 64 / 128
- `num_layers`: 1 / 2 / 3
- `activation`: relu / tanh / gelu / silu
- `fusion`: concat / sum / mul
- `use_batchnorm`: true / false

## Usage
```bash
python train.py --epochs 5 --out baseline.pt
python eval.py --checkpoint baseline.pt
python train.py --epochs 1 --data-ratio 0.33 --out fast.pt
```

## Metrics
- `acc`: test accuracy (higher better)
- `latency_ms`: per-sample inference latency (lower better)
- `params`: total parameter count

## Typical baseline
- `acc` ≈ 0.90 (each half has less info than full 64-dim input)
- `params` ≈ 6-8K
