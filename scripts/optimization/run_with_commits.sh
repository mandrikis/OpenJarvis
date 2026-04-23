#!/bin/bash
# Run optimization pipeline for a single model with auto-commit after each benchmark.
#
# Strategy D: commit result files to git as they land, so we never lose data
# again if the compute node migrates or /tmp/scratch is wiped.
#
# Usage:
#   bash scripts/optimization/run_with_commits.sh <phase> <model> <port>
#     phase: gepa | heldout | dspy | taubench
#     model: e.g. Qwen/Qwen3.5-9B
#     port:  e.g. 8002

set -uo pipefail
cd "$(dirname "$0")/../.."

if [ -f .env ]; then source .env; fi

PHASE="${1:?phase required}"
MODEL="${2:?model required}"
PORT="${3:?port required}"

MODEL_SLUG=$(echo "$MODEL" | tr '/' '-' | tr ':' '-')
RESULTS_BASE="results/neurips-2026/agent-optimization-v2"

# Per-benchmark sample counts (matches run_all.sh)
declare -A SAMPLES=(
  ["toolcall15"]=15 ["pinchbench"]=15 ["taubench"]=15 ["taubench:telecom"]=15
  ["gaia"]=10 ["deepresearch"]=8 ["liveresearchbench"]=10 ["livecodebench"]=15
)

commit_results() {
    local label="$1"
    # Non-interactive commit, allow nothing-to-commit
    git add "$RESULTS_BASE/" 2>/dev/null || true
    if ! git diff --cached --quiet; then
        git commit -m "results: $label [skip ci]" \
            -m "Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>" \
            > /dev/null 2>&1 || true
        echo "$(date) committed: $label"
    fi
}

run_gepa_for_bench() {
    local bench_spec="$1"
    local bench_name="${bench_spec%%:*}"
    local subset=""
    [[ "$bench_spec" == *":"* ]] && subset="${bench_spec#*:}"
    local slug=$(echo "$bench_spec" | tr ":" "_")
    local samples=${SAMPLES[$bench_spec]:-15}
    local out_dir="$RESULTS_BASE/gepa/$MODEL_SLUG/$slug/C2"

    [ -f "$out_dir/result.json" ] && { echo "[SKIP] GEPA $slug"; return 0; }

    local subset_flag=""
    [ -n "$subset" ] && subset_flag="--benchmark-subset $subset"

    echo "$(date) --- GEPA: $MODEL_SLUG x $slug (port $PORT, n=$samples) ---"
    timeout 10800 uv run python scripts/optimization/run_gepa.py \
        --model "$MODEL" --benchmark "$bench_name" $subset_flag \
        --data-config C2 --engine-key vllm --vllm-port $PORT \
        --max-metric-calls 50 --population-size 5 \
        --reflection-lm "anthropic/claude-sonnet-4-6" \
        --max-eval-samples $samples --output-dir "$out_dir" 2>&1 | tail -10
    local ec=$?
    echo "$(date) GEPA $slug exit=$ec"
    commit_results "GEPA $MODEL_SLUG x $slug"
}

run_heldout_for_bench() {
    local bench_spec="$1"
    local bench_name="${bench_spec%%:*}"
    local subset=""
    [[ "$bench_spec" == *":"* ]] && subset="${bench_spec#*:}"
    local slug=$(echo "$bench_spec" | tr ":" "_")

    local n
    case "$bench_name" in
        toolcall15) n=15 ;;
        pinchbench) n=23 ;;
        taubench) n=20 ;;
        gaia) n=50 ;;
        deepresearch) n=20 ;;
        liveresearchbench) n=20 ;;
        livecodebench) n=20 ;;
        *) n=20 ;;
    esac

    local gepa_result="$RESULTS_BASE/gepa/$MODEL_SLUG/$slug/C2/result.json"
    local heldout_file="$RESULTS_BASE/gepa/$MODEL_SLUG/$slug/C2/heldout_n${n}.json"

    [ ! -f "$gepa_result" ] && { echo "[SKIP] HELDOUT $slug: no gepa result"; return 0; }
    [ -f "$heldout_file" ] && { echo "[SKIP] HELDOUT $slug (done)"; return 0; }

    local subset_flag=""
    [ -n "$subset" ] && subset_flag="--benchmark-subset $subset"

    echo "$(date) --- HELDOUT: $MODEL_SLUG x $slug (n=$n) ---"
    timeout 7200 uv run python scripts/optimization/heldout_eval.py \
        --result-json "$gepa_result" --vllm-port $PORT \
        --max-samples $n $subset_flag --also-eval-seed 2>&1 | tail -10
    local ec=$?
    echo "$(date) HELDOUT $slug exit=$ec"
    commit_results "HELDOUT $MODEL_SLUG x $slug"
}

run_taubench_for_subset() {
    local subset_name="$1"   # "airline,retail" or "telecom"
    local slug="$2"          # "taubench" or "taubench_telecom"
    local out_file="$RESULTS_BASE/gepa/$MODEL_SLUG/$slug/C2/heldout_tau2_seed_n20.json"

    [ -f "$out_file" ] && { echo "[SKIP] TauBench $slug (done)"; return 0; }
    mkdir -p "$(dirname "$out_file")"

    echo "$(date) --- TAU2: $MODEL_SLUG x $slug (seed, n=20) ---"
    timeout 7200 uv run python scripts/optimization/taubench_heldout.py \
        --model "$MODEL" --vllm-port $PORT \
        --subset "$subset_name" --max-samples 20 \
        --output-json "$out_file" 2>&1 | tail -10
    echo "$(date) TAU2 $slug exit=$?"
    commit_results "TAU2 $MODEL_SLUG x $slug"
}

run_dspy_for_bench() {
    local bench_spec="$1"
    local bench_name="${bench_spec%%:*}"
    local subset=""
    [[ "$bench_spec" == *":"* ]] && subset="${bench_spec#*:}"
    local slug=$(echo "$bench_spec" | tr ":" "_")
    local samples=${SAMPLES[$bench_spec]:-15}
    local out_dir="$RESULTS_BASE/dspy/simba/$MODEL_SLUG/$slug/C2"

    [ -f "$out_dir/result.json" ] && { echo "[SKIP] DSPy $slug"; return 0; }

    local subset_flag=""
    [ -n "$subset" ] && subset_flag="--benchmark-subset $subset"

    echo "$(date) --- DSPy SIMBA: $MODEL_SLUG x $slug (port $PORT, n=$samples) ---"
    timeout 7200 uv run python scripts/optimization/run_dspy.py \
        --model "$MODEL" --benchmark "$bench_name" $subset_flag \
        --data-config C2 --method simba --engine-key vllm --vllm-port $PORT \
        --max-eval-samples $samples \
        --max-bootstrapped-demos 4 --max-labeled-demos 4 \
        --num-candidate-programs 5 \
        --teacher-lm "anthropic/claude-sonnet-4-6" \
        --output-dir "$out_dir" 2>&1 | tail -10
    echo "$(date) DSPy $slug exit=$?"
    commit_results "DSPy-SIMBA $MODEL_SLUG x $slug"
}

echo "=========================================="
echo "  Phase: $PHASE | Model: $MODEL | Port: $PORT"
echo "=========================================="

BENCHMARKS=(toolcall15 pinchbench "taubench:airline,retail-proxy" gaia deepresearch liveresearchbench livecodebench)
# Note: I'm excluding the problematic TC15×26B cell handling here; the 26B×TC15 hang is a known issue we'll accept

case "$PHASE" in
    gepa)
        # 7 benchmarks via LiveEvaluator (TauBench handled separately via tau2)
        for bench in toolcall15 pinchbench gaia deepresearch liveresearchbench livecodebench; do
            # Skip TC15 on 26B (known hang)
            if [ "$bench" = "toolcall15" ] && [[ "$MODEL" == *"gemma-4-26B"* ]]; then
                echo "[SKIP-KNOWN-HANG] GEPA $bench on $MODEL"
                continue
            fi
            run_gepa_for_bench "$bench"
        done
        ;;
    heldout)
        for bench in toolcall15 pinchbench gaia deepresearch liveresearchbench livecodebench; do
            if [ "$bench" = "toolcall15" ] && [[ "$MODEL" == *"gemma-4-26B"* ]]; then continue; fi
            run_heldout_for_bench "$bench"
        done
        ;;
    taubench)
        # TauBench proper multi-turn eval, seed config only (Scope A)
        run_taubench_for_subset "airline,retail" "taubench"
        run_taubench_for_subset "telecom" "taubench_telecom"
        ;;
    dspy)
        # DSPy SIMBA, all 6 benchmarks (skip tau2 variants; they would also be 0-demo)
        for bench in toolcall15 pinchbench gaia deepresearch liveresearchbench livecodebench; do
            run_dspy_for_bench "$bench"
        done
        ;;
    *)
        echo "Unknown phase: $PHASE"
        exit 1
        ;;
esac

echo "=========================================="
echo "  Phase $PHASE for $MODEL_SLUG DONE"
echo "=========================================="
