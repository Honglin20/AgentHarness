#!/usr/bin/env bash
# cloud_setup.sh — provision AutoDL instance for ASI NAS project.
#
# Run on the REMOTE AutoDL box (after SSH'ing in). Idempotent: safe to re-run.
#
# Installs:
#   - conda env `asi` with Python 3.10
#   - PyTorch with CUDA 11.8
#   - transformers, datasets
#   - flash-linear-attention (real ASI deps) — needs triton
#   - clones AgentHarness repo to /root/autodl-tmp/AgentHarness
#   - pre-downloads wikitext-2 + GPT-2 tokenizer

set -euo pipefail

PROJECT_ROOT="/root/autodl-tmp/AgentHarness"
DATA_DIR="/root/autodl-tmp/data"
ENV_NAME="asi"

# AutoDL miniconda paths (multiple known locations)
for CONDA_INIT in /root/miniconda3/etc/profile.d/conda.sh /opt/conda/etc/profile.d/conda.sh; do
    if [ -f "$CONDA_INIT" ]; then
        source "$CONDA_INIT"
        break
    fi
done
# Fall back to PATH discovery
which conda >/dev/null 2>&1 || export PATH="/root/miniconda3/bin:$PATH"

echo "[1/6] check CUDA"
# pipefail + head closing stdin can SIGPIPE nvidia-smi → use explicit redirect
nvidia-smi > /tmp/nvidia_smi.txt 2>&1 || { echo "no GPU found"; exit 1; }
head -10 /tmp/nvidia_smi.txt

echo "[2/6] conda env: $ENV_NAME"
if ! conda env list | grep -q "^$ENV_NAME "; then
    conda create -y -n "$ENV_NAME" python=3.10
fi
conda activate "$ENV_NAME"
echo "python: $(which python)"

echo "[3/6] install PyTorch + transformers + datasets"
python -c "import torch" 2>/dev/null || \
    pip install torch==2.4.0 --index-url https://download.pytorch.org/whl/cu118
python -c "import transformers" 2>/dev/null || pip install transformers>=4.30
python -c "import datasets" 2>/dev/null || pip install datasets>=2.10

echo "[4/6] install flash-linear-attention (real ASI model)"
python -c "import fla" 2>/dev/null || \
    pip install -U triton flash-linear-attention || \
    echo "WARN: fla install failed; fallback to CPU mode"

echo "[5/6] clone / pull AgentHarness"
mkdir -p "$(dirname "$PROJECT_ROOT")"
if [ ! -d "$PROJECT_ROOT/.git" ]; then
    # Adjust URL if you forked
    git clone https://github.com/mozzielol/AgentHarness.git "$PROJECT_ROOT" || \
    echo "WARN: clone failed — please clone manually"
fi
cd "$PROJECT_ROOT"
git pull --rebase || true
echo "repo at: $(pwd)"

echo "[6/6] pre-download wikitext-2 + tokenizer"
mkdir -p "$DATA_DIR"
cd "$PROJECT_ROOT/projects/asi"
ASI_DATA_DIR="$DATA_DIR" python -c "
from pathlib import Path
import sys; sys.path.insert(0, '.')
from train import get_tokenizer, load_wikitext_tokenized
data_dir = Path('$DATA_DIR')
tok = get_tokenizer(data_dir)
train, val = load_wikitext_tokenized(data_dir, 256, tok)
print(f'train chunks: {len(train)}, val chunks: {len(val)}')
" || echo "WARN: data preload failed (will lazy-load on first run)"

echo ""
echo "✅ setup done"
echo "Test training:"
echo "  cd $PROJECT_ROOT/projects/asi"
echo "  ASI_DATA_DIR=$DATA_DIR python train.py --steps 50 --out_dir /tmp/test"
