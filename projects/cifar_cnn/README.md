# Small CNN Image Classification (Synthetic)

Tiny CNN for image classification on synthetic data (no torchvision dependency).
Clean PyTorch project with argparse. Domain: computer vision (image classification).

## Task
- Synthetic 3-channel images (32x32), 5 classes
- Random pixel patterns + class-dependent color bias
- Domain: CV / image classification

## Architecture
- 2 conv blocks (Conv2d → ReLU → MaxPool) + FC head
- Input: `(B, 3, 32, 32)`
- Output: `(B, 5)` class logits

## Files
- `data.py` — synthetic image data generator
- `model.py` — `SmallCNN(nn.Module)` with `dummy_inputs()`
- `train.py` — argparse-based training entry
- `evaluate.py` — argparse-based evaluation entry

## Run
```bash
python train.py --epochs 5 --output checkpoints/cnn.pt
python evaluate.py --checkpoint checkpoints/cnn.pt
```

## Configurable dimensions
- `--epochs N` (argparse, default 5)
- `--batch-size N` (argparse, default 64)
- `--lr F` (argparse, default 0.001)

Typical baseline: ~70% accuracy on synthetic 5-class task.
