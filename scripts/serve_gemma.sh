#!/usr/bin/env bash
# Launch Gemma-4-26B-A4B-it on vLLM with TP=4.
#
# Idempotently re-applies the gemma4.py per_layer_inputs patch (vLLM 0.20.0
# upstream bug — IntermediateTensors has no .get()) so this works after any
# `uv sync` that reinstalls vLLM.
#
# Usage: bash scripts/serve_gemma.sh [extra vllm args]
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV_PY="${VENV_PY:-$REPO_ROOT/.venv/bin/python}"
GEMMA4_PY="$REPO_ROOT/.venv/lib/python3.12/site-packages/vllm/model_executor/models/gemma4.py"

if [[ ! -x "$VENV_PY" ]]; then
    echo "ERROR: $VENV_PY not found. Run: uv sync --extra dev --extra inference-cloud --extra inference-vllm --extra inference-google --extra tools-search" >&2
    exit 1
fi

if [[ ! -f "$GEMMA4_PY" ]]; then
    echo "ERROR: $GEMMA4_PY not found. vLLM may be the wrong version (need >=0.19.1)." >&2
    exit 1
fi

if grep -q 'intermediate_tensors\.get("per_layer_inputs")' "$GEMMA4_PY"; then
    echo "[serve_gemma] applying gemma4.py per_layer_inputs patch"
    sed -i 's/intermediate_tensors\.get("per_layer_inputs")/intermediate_tensors.tensors.get("per_layer_inputs")/' "$GEMMA4_PY"
fi

export HF_HOME="${HF_HOME:-/matx/u/aspark/huggingface}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1,2,3}"

MODEL="${MODEL:-google/gemma-4-26B-A4B-it}"
PORT="${PORT:-8004}"
TP="${TP:-4}"

echo "[serve_gemma] HF_HOME=$HF_HOME CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES TP=$TP PORT=$PORT"

exec "$VENV_PY" -m vllm.entrypoints.openai.api_server \
    --model "$MODEL" --port "$PORT" \
    --tensor-parallel-size "$TP" \
    --served-model-name gemma-4-26b "$MODEL" \
    --gpu-memory-utilization 0.90 --trust-remote-code \
    --limit-mm-per-prompt '{"image":0,"audio":0,"video":0}' \
    --enable-auto-tool-choice --tool-call-parser gemma4 \
    "$@"
