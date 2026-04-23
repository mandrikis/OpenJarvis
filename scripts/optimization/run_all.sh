#!/bin/bash
# Run the full Step 2a optimization experiment matrix.
#
# Prerequisite: vLLM servers running on the expected ports.
# Use scripts/optimization/launch_vllm.sh to start all servers.
#
# 5 models x 8 benchmarks x GEPA = 40 runs (primary)
# + optional DSPy SIMBA comparison on top-performing pairs
#
# Usage:
#   bash scripts/optimization/run_all.sh [--dry-run] [--phase PHASE] [--model MODEL]
#   Phases: gepa, dspy, heldout, all (default: gepa)
#   Model filter: e.g. --model "Qwen/Qwen3.5-9B" (runs only that model)

set -euo pipefail
cd "$(dirname "$0")/../.."

# Source API keys
if [ -f .env ]; then
    source .env
fi

# ---- Config ----
RESULTS_BASE="results/neurips-2026/agent-optimization-v2"

ALL_MODELS=(
    "Qwen/Qwen3.5-2B"
    "Qwen/Qwen3.5-9B"
    "Qwen/Qwen3.5-27B-FP8"
    "google/gemma-4-E4B-it"
    "google/gemma-4-26B-A4B-it"
)

# Benchmarks: name[:subset] — subset is passed via --benchmark-subset
ALL_BENCHMARKS=(
    "toolcall15"
    "pinchbench"
    "taubench"
    "taubench:telecom"
    "gaia"
    "deepresearch"
    "liveresearchbench"
    "livecodebench"
)

# Port mapping per model (matches currently-running servers)
declare -A MODEL_PORTS
MODEL_PORTS["Qwen/Qwen3.5-2B"]=8000
MODEL_PORTS["Qwen/Qwen3.5-9B"]=8001
MODEL_PORTS["Qwen/Qwen3.5-27B-FP8"]=8002
MODEL_PORTS["google/gemma-4-E4B-it"]=8004
MODEL_PORTS["google/gemma-4-26B-A4B-it"]=8005

# Per-benchmark max_eval_samples (smaller for slow benchmarks)
declare -A BENCH_SAMPLES
BENCH_SAMPLES["toolcall15"]=15
BENCH_SAMPLES["pinchbench"]=15
BENCH_SAMPLES["taubench"]=15
BENCH_SAMPLES["taubench:telecom"]=15
BENCH_SAMPLES["gaia"]=10
BENCH_SAMPLES["deepresearch"]=8
BENCH_SAMPLES["liveresearchbench"]=10
BENCH_SAMPLES["livecodebench"]=15

# GEPA params
MAX_METRIC_CALLS=50
POPULATION_SIZE=5
REFLECTION_LM="anthropic/claude-sonnet-4-6"

# DSPy params
DSPY_METHODS=("simba")
NUM_CANDIDATE_PROGRAMS=5
TEACHER_LM="anthropic/claude-sonnet-4-6"

# ---- CLI args ----
DRY_RUN=false
PHASE="gepa"
MODEL_FILTER=""
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run) DRY_RUN=true; shift ;;
        --phase) PHASE="$2"; shift 2 ;;
        --model) MODEL_FILTER="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Apply model filter
MODELS=()
if [ -n "$MODEL_FILTER" ]; then
    for m in "${ALL_MODELS[@]}"; do
        [[ "$m" == *"$MODEL_FILTER"* ]] && MODELS+=("$m")
    done
    [ ${#MODELS[@]} -eq 0 ] && echo "No models match filter: $MODEL_FILTER" && exit 1
else
    MODELS=("${ALL_MODELS[@]}")
fi

# ---- Helpers ----
run_or_print() {
    if $DRY_RUN; then
        echo "[DRY RUN] $*"
    else
        echo "$(date '+%H:%M:%S') Running: $*"
        eval "$@"
    fi
}

# Parse benchmark:subset notation
parse_bench() {
    local spec="$1"
    BENCH_NAME="${spec%%:*}"
    if [[ "$spec" == *":"* ]]; then
        BENCH_SUBSET="${spec#*:}"
    else
        BENCH_SUBSET=""
    fi
}

# Build output directory slug from benchmark spec
bench_slug() {
    local spec="$1"
    echo "$spec" | tr ':' '_'
}

echo "============================================="
echo "  Step 2a: Agent Optimization (v2)"
echo "  Phase: $PHASE"
echo "============================================="
echo "Models:     ${MODELS[*]}"
echo "Benchmarks: ${ALL_BENCHMARKS[*]}"
echo "Dry run:    $DRY_RUN"
echo ""

total_runs=0
skip_runs=0

# ---- GEPA runs ----
if [[ "$PHASE" == "all" || "$PHASE" == "gepa" ]]; then
    echo "===== GEPA Optimization ====="
    for model in "${MODELS[@]}"; do
        model_slug=$(echo "$model" | tr '/' '-' | tr ':' '-')
        port=${MODEL_PORTS[$model]:-8000}
        for bench_spec in "${ALL_BENCHMARKS[@]}"; do
            parse_bench "$bench_spec"
            slug=$(bench_slug "$bench_spec")
            samples=${BENCH_SAMPLES[$bench_spec]:-15}
            out_dir="$RESULTS_BASE/gepa/$model_slug/$slug/C2"
            total_runs=$((total_runs + 1))

            if [ -f "$out_dir/result.json" ]; then
                echo "  [SKIP] GEPA $model_slug x $slug (done)"
                skip_runs=$((skip_runs + 1))
                continue
            fi

            subset_flag=""
            [ -n "$BENCH_SUBSET" ] && subset_flag="--benchmark-subset $BENCH_SUBSET"

            echo ""
            echo "--- GEPA: $model_slug x $slug (port $port, n=$samples) ---"
            run_or_print uv run python scripts/optimization/run_gepa.py \
                --model "$model" \
                --benchmark "$BENCH_NAME" \
                $subset_flag \
                --data-config C2 \
                --engine-key vllm \
                --vllm-port "$port" \
                --max-metric-calls "$MAX_METRIC_CALLS" \
                --population-size "$POPULATION_SIZE" \
                --reflection-lm "$REFLECTION_LM" \
                --max-eval-samples "$samples" \
                --output-dir "$out_dir"
        done
    done
fi

# ---- DSPy runs ----
if [[ "$PHASE" == "all" || "$PHASE" == "dspy" ]]; then
    echo ""
    echo "===== DSPy Optimization (SIMBA only) ====="
    for model in "${MODELS[@]}"; do
        model_slug=$(echo "$model" | tr '/' '-' | tr ':' '-')
        port=${MODEL_PORTS[$model]:-8000}
        for bench_spec in "${ALL_BENCHMARKS[@]}"; do
            parse_bench "$bench_spec"
            slug=$(bench_slug "$bench_spec")
            samples=${BENCH_SAMPLES[$bench_spec]:-15}
            for method in "${DSPY_METHODS[@]}"; do
                out_dir="$RESULTS_BASE/dspy/$method/$model_slug/$slug/C2"
                total_runs=$((total_runs + 1))

                if [ -f "$out_dir/result.json" ]; then
                    echo "  [SKIP] DSPy $method $model_slug x $slug (done)"
                    skip_runs=$((skip_runs + 1))
                    continue
                fi

                subset_flag=""
                [ -n "$BENCH_SUBSET" ] && subset_flag="--benchmark-subset $BENCH_SUBSET"

                echo ""
                echo "--- DSPy $method: $model_slug x $slug (port $port, n=$samples) ---"
                run_or_print uv run python scripts/optimization/run_dspy.py \
                    --model "$model" \
                    --benchmark "$BENCH_NAME" \
                    $subset_flag \
                    --data-config C2 \
                    --method "$method" \
                    --engine-key vllm \
                    --vllm-port "$port" \
                    --max-eval-samples "$samples" \
                    --max-bootstrapped-demos 4 \
                    --max-labeled-demos 4 \
                    --num-candidate-programs "$NUM_CANDIDATE_PROGRAMS" \
                    --teacher-lm "$TEACHER_LM" \
                    --output-dir "$out_dir"
            done
        done
    done
fi

# ---- Held-out evaluation ----
if [[ "$PHASE" == "heldout" ]]; then
    echo ""
    echo "===== Held-Out Evaluation ====="
    for model in "${MODELS[@]}"; do
        model_slug=$(echo "$model" | tr '/' '-' | tr ':' '-')
        port=${MODEL_PORTS[$model]:-8000}
        for bench_spec in "${ALL_BENCHMARKS[@]}"; do
            parse_bench "$bench_spec"
            slug=$(bench_slug "$bench_spec")

            # Full sample count for held-out (not the reduced optimization count)
            case "$BENCH_NAME" in
                toolcall15) n=15 ;;
                pinchbench) n=23 ;;
                taubench) n=20 ;;
                gaia) n=50 ;;
                deepresearch) n=20 ;;
                liveresearchbench) n=20 ;;
                livecodebench) n=20 ;;
                *) n=20 ;;
            esac

            subset_flag=""
            [ -n "$BENCH_SUBSET" ] && subset_flag="--benchmark-subset $BENCH_SUBSET"

            # Eval GEPA result
            gepa_result="$RESULTS_BASE/gepa/$model_slug/$slug/C2/result.json"
            if [ -f "$gepa_result" ]; then
                heldout_file="$RESULTS_BASE/gepa/$model_slug/$slug/C2/heldout_n${n}.json"
                if [ ! -f "$heldout_file" ]; then
                    total_runs=$((total_runs + 1))
                    echo ""
                    echo "--- HELDOUT: GEPA $model_slug x $slug (n=$n) ---"
                    run_or_print uv run python scripts/optimization/heldout_eval.py \
                        --result-json "$gepa_result" \
                        --vllm-port "$port" \
                        --max-samples "$n" \
                        $subset_flag \
                        --also-eval-seed
                else
                    echo "  [SKIP] HELDOUT GEPA $model_slug x $slug (done)"
                    skip_runs=$((skip_runs + 1))
                fi
            fi
        done
    done
fi

echo ""
echo "============================================="
echo "  Total: $total_runs runs ($skip_runs skipped)"
echo "============================================="
