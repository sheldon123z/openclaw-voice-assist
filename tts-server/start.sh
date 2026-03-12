#!/bin/bash
# Qwen3-TTS Multi-Backend Server Startup Script

CONDA_BASE="$HOME/miniconda3"
ENV_NAME="qwen3-tts"
SERVER_DIR="$HOME/exps/qwen3-tts-server"

# Model paths
QWEN3_MODEL="$HOME/exps/models/Qwen3-TTS-12Hz-1.7B-CustomVoice"
COSYVOICE3_MODEL="$HOME/exps/models/CosyVoice3-0.5B"

# CosyVoice source (for imports)
export PYTHONPATH="$HOME/exps/CosyVoice:$HOME/exps/CosyVoice/third_party/Matcha-TTS:$PYTHONPATH"

HOST="0.0.0.0"
PORT=58201
DEFAULT_VOICE="Serena"

source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

cd "$SERVER_DIR"

exec python server.py \
    --host "$HOST" \
    --port "$PORT" \
    --model "$QWEN3_MODEL" \
    --cosyvoice3-model "$COSYVOICE3_MODEL" \
    --voice "$DEFAULT_VOICE"
