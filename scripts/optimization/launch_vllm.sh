#!/bin/bash
# Launch all 5 vLLM servers for the agent optimization v2 experiment.
#
# GPU allocation (8x H100 80GB total):
#   GPU 0:    Qwen3.5-2B   (port 8001)
#   GPU 1:    Qwen3.5-9B   (port 8002)
#   GPU 2-3:  Qwen3.5-27B-FP8 TP=2  (port 8003)
#   GPU 4:    Gemma4-E4B   (port 8004)
#   GPU 5:    Gemma4-26B   (port 8005)
#   GPU 6-7:  Free buffer
#
# Usage:
#   bash scripts/optimization/launch_vllm.sh [--wait]
#     --wait: poll until all servers respond (up to 15 minutes)

set -euo pipefail
cd "$(dirname "$0")/../.."

if [ -f .env ]; then
    source .env
fi

WAIT=false
SKIP_GEMMA4=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --wait) WAIT=true; shift ;;
        --skip-gemma4) SKIP_GEMMA4=true; shift ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

mkdir -p /tmp/vllm-logs

# Helper: launch a model in the background
launch() {
    local name="$1"
    local model="$2"
    local port="$3"
    local cuda="$4"
    shift 4
    local extra_flags="$@"

    local log="/tmp/vllm-logs/${name}.log"
    echo "Launching $name on GPU $cuda port $port -> $log"

    CUDA_VISIBLE_DEVICES="$cuda" \
        nohup uv run vllm serve "$model" --port "$port" \
        --max-model-len 32768 \
        --gpu-memory-utilization 0.9 \
        $extra_flags \
        > "$log" 2>&1 &

    echo "  PID: $!"
}

# ---- Launch all servers ----
echo "=========================================="
echo "  Launching 5 vLLM servers"
echo "=========================================="

launch "qwen-2b"     "Qwen/Qwen3.5-2B"           8001 "0"   --enable-auto-tool-choice --tool-call-parser qwen3_coder
launch "qwen-9b"     "Qwen/Qwen3.5-9B"           8002 "1"   --enable-auto-tool-choice --tool-call-parser qwen3_coder
launch "qwen-27b"    "Qwen/Qwen3.5-27B-FP8"      8003 "2,3" --enable-auto-tool-choice --tool-call-parser qwen3_coder --tensor-parallel-size 2
if ! $SKIP_GEMMA4; then
    launch "gemma4-e4b"  "google/gemma-4-E4B-it"     8004 "4"   --enable-auto-tool-choice --tool-call-parser gemma4
    launch "gemma4-26b"  "google/gemma-4-26B-A4B-it" 8005 "5"   --enable-auto-tool-choice --tool-call-parser gemma4
fi

echo ""
echo "All launches initiated. Logs in /tmp/vllm-logs/"
echo ""

# ---- Optional health check loop ----
if $WAIT; then
    echo "=========================================="
    echo "  Waiting for servers to come up..."
    echo "=========================================="
    declare -A SERVERS
    SERVERS["qwen-2b"]=8001
    SERVERS["qwen-9b"]=8002
    SERVERS["qwen-27b"]=8003
    if ! $SKIP_GEMMA4; then
        SERVERS["gemma4-e4b"]=8004
        SERVERS["gemma4-26b"]=8005
    fi

    if $SKIP_GEMMA4; then
        SERVER_NAMES="qwen-2b qwen-9b qwen-27b"
    else
        SERVER_NAMES="qwen-2b qwen-9b qwen-27b gemma4-e4b gemma4-26b"
    fi

    max_iters=60   # 60 * 15s = 15 min
    for i in $(seq 1 $max_iters); do
        all_ready=true
        line=""
        for name in $SERVER_NAMES; do
            port=${SERVERS[$name]}
            if curl -s --max-time 2 "http://localhost:$port/v1/models" 2>/dev/null | grep -q '"id"'; then
                line+="${name}=READY  "
            else
                line+="${name}=loading  "
                all_ready=false
            fi
        done
        echo "[$i/$max_iters] $line"
        if $all_ready; then
            echo ""
            echo "=========================================="
            echo "  ALL SERVERS READY"
            echo "=========================================="
            exit 0
        fi
        sleep 15
    done
    echo "TIMEOUT: not all servers ready after 15 min. Check logs."
    exit 1
fi

echo "Tip: rerun with --wait to poll until ready"
