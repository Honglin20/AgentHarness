# Dict-Input Test Project (forward({"user": u, "item": i}))

Stress-tests the NAS workflow's handling of **dict-of-tensors forward** signatures.

## Why this project?
- Many real models (HuggingFace, multimodal, recommendation) take named-field dicts.
- Dicts with named keys are not autograd-traceable as a single tensor — ONNX export and shape inference must handle multiple named inputs.
- This project's `DictInputMLP.forward(inputs)` expects a dict with keys `"user"` and `"item"`.

## Data
Synthetic user × item engagement classification:
- `user`: (8,) Gaussian features
- `item`: (8,) Gaussian features
- Label: bucket(dot(user, item)) → 3 classes (low/mid/high engagement)

## Configurable architecture
- `hidden_dim`: 32 / 64 / 128
- `num_layers`: 1 / 2 / 3
- `activation`: relu / tanh / gelu / silu
- `fusion`: concat / sum / mul / hadamard_dot
- `use_batchnorm`: true / false

## Usage
```bash
python train.py --epochs 5 --use-batchnorm --out baseline.pt
python eval.py --checkpoint baseline.pt
python train.py --epochs 1 --steps-per-epoch 20 --out fast.pt
```

## Metrics
- `acc`: 3-class accuracy (higher better)
- `latency_ms`: per-sample inference latency (lower better)
- `params`: total parameter count

## Typical baseline
- `acc` ≈ 0.70-0.85 (3-class with overlap is harder than MNIST)
- `params` ≈ 6-10K
