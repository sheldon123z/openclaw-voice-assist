#!/bin/bash
CONDA_BASE="$HOME/miniconda3"
ENV_NAME="qwen3-tts"
SERVER_DIR="$HOME/exps/qwen3-dashboard"

source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

cd "$SERVER_DIR"
exec python server.py
