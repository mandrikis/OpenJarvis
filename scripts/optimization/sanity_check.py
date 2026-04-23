"""Sanity-check the optimization pipeline across 5 models x 8 benchmarks.

Runs 1 evaluation per (model, benchmark) pair with the seed config and reports
pass/fail. Catches issues like:
- Gemma4 tool calling failures
- TauBench Telecom subset loading
- DeepResearchBench external repo clone
- LiveResearchBench HuggingFace access
- LiveCodeBench sandbox setup

Usage:
    uv run python scripts/optimization/sanity_check.py [--model MODEL] [--bench BENCH]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from pathlib import Path

logger = logging.getLogger("sanity_check")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


MODEL_PORTS = {
    "Qwen/Qwen3.5-2B": 8001,
    "Qwen/Qwen3.5-9B": 8002,
    "Qwen/Qwen3.5-27B-FP8": 8003,
    "google/gemma-4-E4B-it": 8004,
    "google/gemma-4-26B-A4B-it": 8005,
}

# Benchmark specs: (benchmark_name, subset_or_none)
BENCHMARKS = [
    ("toolcall15", None),
    ("pinchbench", None),
    ("taubench", None),
    ("taubench", "telecom"),
    ("gaia", None),
    ("deepresearch", None),
    ("liveresearchbench", None),
    ("livecodebench", None),
]

SEED_CONFIG = {
    "system_prompt": "You are a precise AI agent that completes tasks by executing tools and verifying results.",
    "temperature": 0.3,
    "max_tokens": 4096,
    "top_p": 0.9,
    "agent_type": "monitor_operative",
    "max_turns": 25,
    "tool_set": "think,calculator,code_interpreter,web_search,file_read,file_write,shell_exec,http_request,apply_patch,llm",
    "tool_choice": "auto",
}


def check_pair(model: str, port: int, benchmark: str, subset: str | None, timeout_s: int = 300) -> dict:
    """Run 1 eval for this (model, benchmark) pair and return status."""
    sys.path.insert(0, str(Path(__file__).parent))
    from evaluator import LiveEvaluator

    bench_label = benchmark if subset is None else f"{benchmark}:{subset}"
    status = {
        "model": model,
        "benchmark": bench_label,
        "port": port,
        "status": "unknown",
        "accuracy": None,
        "elapsed_s": None,
        "error": None,
    }

    t0 = time.time()
    evaluator = None
    try:
        evaluator = LiveEvaluator(
            model=model,
            benchmark=benchmark,
            benchmark_subset=subset,
            engine_key="vllm",
            max_samples=1,  # Just 1 task to verify pipeline works
            vllm_port=port,
        )
        acc = evaluator.evaluate(dict(SEED_CONFIG))
        status["status"] = "pass"
        status["accuracy"] = acc
    except Exception as exc:
        status["status"] = "fail"
        status["error"] = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "FAIL: %s x %s: %s",
            model, bench_label, status["error"],
        )
        traceback.print_exc(limit=5)
    finally:
        if evaluator is not None:
            try:
                evaluator.close()
            except Exception:
                pass
        status["elapsed_s"] = time.time() - t0

    return status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=None, help="Filter to models matching this substring")
    parser.add_argument("--bench", default=None, help="Filter to benchmarks matching this substring")
    parser.add_argument("--output", default="results/neurips-2026/agent-optimization-v2/sanity_check.json")
    args = parser.parse_args()

    # Filter
    models = list(MODEL_PORTS.items())
    if args.model:
        models = [(m, p) for m, p in models if args.model in m]
    benchmarks = BENCHMARKS
    if args.bench:
        benchmarks = [(b, s) for b, s in benchmarks if args.bench in b]

    logger.info("Sanity check: %d models x %d benchmarks = %d checks",
                len(models), len(benchmarks), len(models) * len(benchmarks))

    results = []
    for model, port in models:
        for bench, subset in benchmarks:
            bench_label = bench if subset is None else f"{bench}:{subset}"
            logger.info("Checking %s x %s (port %d)...", model, bench_label, port)
            r = check_pair(model, port, bench, subset)
            results.append(r)
            icon = "OK" if r["status"] == "pass" else "FAIL"
            logger.info("[%s] %s x %s in %.1fs (acc=%s, error=%s)",
                        icon, model, bench_label, r["elapsed_s"],
                        r["accuracy"], r["error"])

    # Save
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))

    # Summary table
    print()
    print("=" * 80)
    print(f"{'Model':<30} {'Benchmark':<25} {'Status':<8} {'Time':<8}")
    print("=" * 80)
    for r in results:
        model_short = r["model"].split("/")[-1][:28]
        bench_short = r["benchmark"][:23]
        time_str = f"{r['elapsed_s']:.1f}s" if r['elapsed_s'] else "-"
        print(f"{model_short:<30} {bench_short:<25} {r['status']:<8} {time_str:<8}")

    passes = sum(1 for r in results if r["status"] == "pass")
    print()
    print(f"Total: {passes}/{len(results)} passed")
    print(f"Saved: {out_path}")

    if passes < len(results):
        sys.exit(1)


if __name__ == "__main__":
    main()
