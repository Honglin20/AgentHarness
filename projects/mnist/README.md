# MNIST Test Project for NAS Workflow

A minimal PyTorch MLP project on sklearn digits (no internet/data download needed) for validating the NAS workflow.

## Why sklearn digits?
- 1797 samples, 64 features (8x8 images), 10 classes — small enough to train in seconds on CPU
- Built into scikit-learn, no download
- Real data (not random) — accuracy differences are meaningful

## Configurable Architecture
The model (`model.py:ConfigurableMLP`) supports:
- `hidden_dim`: 32 / 64 / 128 / ...
- `num_layers`: 1 / 2 / 3 / ...
- `activation`: relu / tanh / gelu / silu
- `use_batchnorm`: true / false

NAS agents can modify `model.py` to explore these dimensions.

## Usage

```bash
# Train baseline (5 epochs, full data)
python train.py --epochs 5 --out baseline.pt

# Benchmark
python eval.py --checkpoint baseline.pt

# Tier-fast train (1/3 data, 1 epoch)
python train.py --epochs 1 --data-ratio 0.33 --out fast.pt
```

## Metrics
- `acc`: test accuracy (higher better)
- `latency_ms`: per-sample inference latency in ms (lower better)
- `params`: total parameter count
- `loss_curve`: per-epoch training loss

## Typical baseline numbers
- `acc` ≈ 0.95
- `latency_ms` ≈ 0.01 (very small model on CPU)
- `params` ≈ 4-5K (2 layers, hidden=64)
