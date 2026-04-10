#!/bin/bash
# Script to run all Qwen benchmarks (27B and 9B, excluding 397B)
# Benchmarks: PinchBench, TauBench, GAIA, TerminalBench

set -e

# Configuration
QWEN9B_POD="qwen35-9b-master-0"
QWEN27B_POD="qwen35-27b-master-0"
OPENJARVIS_DIR="/tmp/OpenJarvis"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

copy_files_to_pod() {
    local POD=$1
    log_info "Copying OpenJarvis files to $POD"

    # Sync the configs
    oc exec $POD -- mkdir -p $OPENJARVIS_DIR/src/openjarvis/evals/configs
    for config in pinchbench taubench gaia; do
        log_info "Copying ${config}-qwen-*-pod.toml configs"
        oc cp src/openjarvis/evals/configs/${config}-qwen-9b-pod.toml $POD:$OPENJARVIS_DIR/src/openjarvis/evals/configs/ 2>/dev/null || true
        oc cp src/openjarvis/evals/configs/${config}-qwen-27b-pod.toml $POD:$OPENJARVIS_DIR/src/openjarvis/evals/configs/ 2>/dev/null || true
    done
}

run_benchmark_in_pod() {
    local POD=$1
    local CONFIG=$2
    local BENCHMARK_NAME=$3
    local MODEL_NAME=$4

    log_info "Running $BENCHMARK_NAME on $MODEL_NAME in pod $POD"
    log_info "Config: $CONFIG"

    # Install OpenJarvis if not already installed
    log_info "Ensuring OpenJarvis is installed..."
    oc exec $POD -- bash -c "cd $OPENJARVIS_DIR && pip install -e . --quiet 2>&1 | tail -5" &

    sleep 2

    # Run the benchmark
    local LOG_FILE="/tmp/${BENCHMARK_NAME}-${MODEL_NAME}-$(date +%Y%m%d-%H%M%S).log"
    oc exec $POD -- bash -c "cd $OPENJARVIS_DIR && \
        export PYTHONPATH=/tmp/.local/lib/python3.12/site-packages:\$PYTHONPATH && \
        export HF_HOME=/tmp/.cache/huggingface && \
        nohup python3 -m openjarvis.cli eval run -c src/openjarvis/evals/configs/$CONFIG > $LOG_FILE 2>&1 &"

    if [ $? -eq 0 ]; then
        log_info "Started $BENCHMARK_NAME for $MODEL_NAME successfully (log: $LOG_FILE)"
    else
        log_error "Failed to start $BENCHMARK_NAME for $MODEL_NAME"
        return 1
    fi

    sleep 3
}

# Main execution
log_info "===== Starting Qwen Benchmark Runs ====="
log_info "Models: Qwen-27B, Qwen-9B (excluding Qwen-397B)"
log_info "Benchmarks: PinchBench, TauBench, GAIA"
log_info "Note: TerminalBench-Native requires Docker and will be skipped"

# Copy config files to pods
log_info "\n===== Copying config files to pods ====="
copy_files_to_pod "$QWEN9B_POD"
copy_files_to_pod "$QWEN27B_POD"

# Qwen-9B Benchmarks
log_info "\n===== Qwen-9B Benchmarks ====="
run_benchmark_in_pod "$QWEN9B_POD" "pinchbench-qwen-9b-pod.toml" "pinchbench" "qwen9b"
run_benchmark_in_pod "$QWEN9B_POD" "taubench-qwen-9b-pod.toml" "taubench" "qwen9b"
run_benchmark_in_pod "$QWEN9B_POD" "gaia-qwen-9b-pod.toml" "gaia" "qwen9b"

# Qwen-27B Benchmarks
log_info "\n===== Qwen-27B Benchmarks ====="
run_benchmark_in_pod "$QWEN27B_POD" "pinchbench-qwen-27b-pod.toml" "pinchbench" "qwen27b"
run_benchmark_in_pod "$QWEN27B_POD" "taubench-qwen-27b-pod.toml" "taubench" "qwen27b"
run_benchmark_in_pod "$QWEN27B_POD" "gaia-qwen-27b-pod.toml" "gaia" "qwen27b"

log_info "\n===== All benchmarks started ====="
log_info "Check logs in the pods under /tmp/*-qwen*-*.log"
log_info "\nTo check running processes:"
log_info "  oc exec $QWEN9B_POD -- ps aux | grep 'jarvis eval'"
log_info "  oc exec $QWEN27B_POD -- ps aux | grep 'jarvis eval'"
log_info "\nTo view logs:"
log_info "  oc exec $QWEN9B_POD -- tail -f /tmp/pinchbench-qwen9b-*.log"
log_info "  oc exec $QWEN27B_POD -- tail -f /tmp/pinchbench-qwen27b-*.log"
