# List-Input Test Project (forward([x1, x2, x3]))

Stress-tests the NAS workflow's handling of **list-of-tensors forward** signatures.

## Why this project?
- Real models (multi-sensor fusion, Set-Transformer, DeepSets) take Python lists of tensors.
- The list semantics (`List[Tensor]`, dynamic length or fixed N) is hard for tools that assume `model(x)` with one tensor.
- This project's `ListInputMLP.forward(x_list)` takes a list of 3 tensors.

## Data
Synthetic 3-channel signal detection:
- 3 channels, each (16,) window of i.i.d. Gaussian noise
- For each sample, a constant signal (+3.0) is added to one channel's first element
- Label = which channel carries the signal (3-class)

Trivially solvable but exercises the list-input path meaningfully.

## Configurable architecture
- `hidden_dim`: 32 / 64 / 128
- `num_layers`: 1 / 2 / 3
- `activation`: relu / tanh / gelu / silu
- `aggregation`: mean / max / sum / concat
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
- `acc` ≈ 0.95+ (signal is strong)
- `params` ≈ 3-6K
