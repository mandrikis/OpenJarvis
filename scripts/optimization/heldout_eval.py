"""Held-out evaluation for completed optimizer runs.

Loads a result.json from a completed GEPA/DSPy optimization run, extracts the
best_candidate config, and runs the same agent through the FULL benchmark
(not just the optimizer's training mini-batch). Compares against the Step 1
baseline to confirm whether the optimization actually generalizes.

Usage:
    uv run python scripts/optimization/heldout_eval.py \\
        --result-json results/neurips-2026/agent-optimization/gepa/.../result.json \\
        --vllm-port 8000 \\
        --max-samples 30

For DSPy results that don't have a `best_candidate` (only demos), the script
falls back to the seed config + applies any optimized_instructions if present.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

logger = logging.getLogger("heldout_eval")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


# Same default seed candidate that GEPA / DSPy bootstrap from
DEFAULT_SEED = {
    "system_prompt": (
        "You are a precise AI agent that completes tasks by executing tools "
        "and verifying results."
    ),
    "temperature": 0.3,
    "max_tokens": 4096,
    "top_p": 0.9,
    "agent_type": "monitor_operative",
    "max_turns": 25,
    "tool_set": "think,calculator,code_interpreter,web_search,file_read,file_write,shell_exec,http_request,apply_patch,llm",
    "tool_choice": "auto",
}


def extract_best_candidate(result_json_path: Path) -> dict:
    """Extract the best candidate config from a result.json.

    Returns the seed config if no best_candidate is present (e.g., DSPy
    results that only contain demos).
    """
    r = json.loads(result_json_path.read_text())
    bc = r.get("best_candidate")
    if bc:
        # Merge with seed defaults to ensure all keys are present
        candidate = dict(DEFAULT_SEED)
        candidate.update(bc)
        return candidate
    # Fall back to seed config (DSPy bootstrap/simba/mipro keep demos separately)
    return dict(DEFAULT_SEED)


def main() -> None:
    parser = argparse.ArgumentParser(description="Held-out eval for optimizer runs")
    parser.add_argument("--result-json", required=True, type=Path)
    parser.add_argument("--model", default=None,
                        help="Override model (otherwise read from result.json)")
    parser.add_argument("--benchmark", default=None,
                        help="Override benchmark (otherwise read from result.json)")
    parser.add_argument("--vllm-port", type=int, default=8000)
    parser.add_argument("--engine-key", default="vllm")
    parser.add_argument("--max-samples", type=int, default=30,
                        help="Number of held-out examples (default 30)")
    parser.add_argument("--judge-model", default="gpt-5-mini-2025-08-07")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--also-eval-seed", action="store_true",
                        help="Also evaluate the seed config for direct comparison")
    parser.add_argument("--benchmark-subset", default=None,
                        help="Benchmark subset (e.g. telecom for taubench)")
    parser.add_argument("--output-suffix", default="heldout",
                        help="Suffix for output JSON file")
    args = parser.parse_args()

    if not args.result_json.exists():
        logger.error("Result file not found: %s", args.result_json)
        sys.exit(1)

    # Load result.json
    result = json.loads(args.result_json.read_text())
    model = args.model or result.get("model")
    benchmark = args.benchmark or result.get("benchmark")
    optimizer = result.get("optimizer", "?")

    if not model or not benchmark:
        logger.error("Missing model/benchmark — pass --model and --benchmark")
        sys.exit(1)

    candidate = extract_best_candidate(args.result_json)

    logger.info("Held-out eval: %s × %s × %s", optimizer, model, benchmark)
    logger.info("Vllm port: %d, max_samples: %d", args.vllm_port, args.max_samples)
    logger.info("Best candidate temperature: %s, max_turns: %s",
                candidate.get("temperature"), candidate.get("max_turns"))

    # Late import (after argparse, so --help is fast)
    sys.path.insert(0, str(Path(__file__).parent))
    from evaluator import LiveEvaluator

    evaluator = LiveEvaluator(
        model=model,
        benchmark=benchmark,
        engine_key=args.engine_key,
        max_samples=args.max_samples,
        judge_model=args.judge_model,
        seed=args.seed,
        vllm_port=args.vllm_port,
        benchmark_subset=args.benchmark_subset,
    )

    output = {
        "result_json": str(args.result_json),
        "optimizer": optimizer,
        "model": model,
        "benchmark": benchmark,
        "max_samples": args.max_samples,
        "judge_model": args.judge_model,
        "seed": args.seed,
    }

    # Eval the optimized candidate
    t0 = time.monotonic()
    optimized_acc = evaluator.evaluate(candidate)
    optimized_time = time.monotonic() - t0
    logger.info("OPTIMIZED accuracy: %.1f%% (%.1fs)",
                optimized_acc * 100, optimized_time)
    output["optimized_accuracy"] = optimized_acc
    output["optimized_elapsed_seconds"] = optimized_time

    # Optionally eval the seed config for direct A/B
    if args.also_eval_seed:
        t1 = time.monotonic()
        seed_acc = evaluator.evaluate(dict(DEFAULT_SEED))
        seed_time = time.monotonic() - t1
        logger.info("SEED accuracy:      %.1f%% (%.1fs)",
                    seed_acc * 100, seed_time)
        logger.info("LIFT: %+.1fpp",
                    (optimized_acc - seed_acc) * 100)
        output["seed_accuracy"] = seed_acc
        output["seed_elapsed_seconds"] = seed_time
        output["lift_pp"] = (optimized_acc - seed_acc) * 100

    evaluator.close()

    # Save output next to the result.json
    out_path = args.result_json.parent / f"{args.output_suffix}_n{args.max_samples}.json"
    out_path.write_text(json.dumps(output, indent=2))
    logger.info("Saved: %s", out_path)


if __name__ == "__main__":
    main()
