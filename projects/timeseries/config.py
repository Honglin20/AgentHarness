"""Hardcoded hyperparameters for time series forecasting.

No CLI args, no yaml config — pure Python constants. Edit this file to change.
"""

EPOCHS = 10
BATCH_SIZE = 32
LR = 0.005

# Model
HIDDEN_DIM = 64
N_LAYERS = 2
N_FEATURES = 3       # input feature dim
SEQ_LEN = 16         # lookback window

# Data
N_TRAIN = 800
N_EVAL = 200
SINE_FREQS = [0.1, 0.3, 0.05]   # per-feature sine frequencies
NOISE_STD = 0.05

# Output
CHECKPOINT_PATH = "checkpoints/forecaster.pt"
