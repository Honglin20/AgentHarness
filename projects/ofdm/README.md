# OFDM Signal Detector

Wireless OFDM signal detection with deep learning. Synthetic data (no external dataset).

## Task
- Receive OFDM signal distorted by flat-fading channel + AWGN noise
- Classify QPSK symbols per subcarrier (4 classes per subcarrier × 64 subcarriers)
- Domain: wireless communications (4G/5G OFDM)

## Architecture
- 2-layer MLP
- Input: `(B, 64, 2)` — 64 subcarriers × 2 (real, imaginary)
- Output: `(B, 64, 4)` — QPSK class logits per subcarrier

## Files
- `data.py` — synthetic OFDM data generator (channel + noise + QPSK)
- `model.py` — `OFDMDetector(nn.Module)` with `dummy_inputs()`
- `train.py` — argparse + yaml config training
- `eval.py` — load checkpoint + evaluate on eval set
- `config.yaml` — training/model/data params

## Run
```bash
python train.py --config config.yaml --epochs 5
python eval.py --checkpoint checkpoints/ofdm.pt
```

## Configurable dimensions
- `--epochs N` (argparse, overrides config.training.epochs)
- `--config path` (argparse, points to yaml file)
- model.hidden_dim / model.n_layers / model.activation (config yaml only, no CLI)

Typical baseline: ~85% symbol accuracy at 20 dB SNR.
