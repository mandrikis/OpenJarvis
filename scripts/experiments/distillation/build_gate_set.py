#!/usr/bin/env python3
"""Build a curated gate-set for one (family, benchmark) cell.

Reads the baseline_eval JSONL, stratifies records by their baseline score, and
picks N samples (default split: half "correct", half "incorrect"). Writes a
gate_set.json that the M1 orchestrator's CuratedScorer consumes via
``3_run_teacher.py --gate-set``.

If a stratum is short (e.g. only 1 incorrect available), the picker first tops
up from the other stratum, then random-fills if still short. The intent is a
compact regression screen — stop catastrophic edits like "do not perform more
than 3 web searches" before they ship.

Usage::

    python scripts/experiments/distillation/build_gate_set.py \\
        --family qwen9b --benchmark gaia --n 6

The gate set lands at::

    /matx/u/aspark/.openjarvis/experiments/<family>/<benchmark>/gate_set.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

# Allow importing from src/ without install
REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from openjarvis.learning.distillation.gate.curated_scorer import (  # noqa: E402
    GateSample,
    save_gate_set,
)

EXPERIMENTS_ROOT = Path("/matx/u/aspark/.openjarvis/experiments")

# Map family slug → eval-pipeline model slug used in baseline filenames.
FAMILY_TO_MODEL_SLUG: dict[str, str] = {
    "qwen9b": "Qwen-Qwen3.5-9B",
    "gemma26b": "google-gemma-4-26B-A4B-it",
}


def find_baseline_jsonl(family: str, benchmark: str) -> Path:
    """Find the baseline JSONL for this cell. Errors loudly if missing."""
    cell_dir = EXPERIMENTS_ROOT / family / benchmark
    eval_dir = cell_dir / "baseline_eval"
    if not eval_dir.exists():
        raise FileNotFoundError(
            f"No baseline_eval at {eval_dir}. Run baseline first or symlink "
            f"into {cell_dir}."
        )
    candidates = list(eval_dir.glob(f"{benchmark}_*.jsonl"))
    candidates = [p for p in candidates if not p.name.endswith(".bak")]
    if not candidates:
        raise FileNotFoundError(f"No {benchmark}_*.jsonl under {eval_dir}")
    if len(candidates) > 1:
        # Prefer the one matching the family's model slug
        slug = FAMILY_TO_MODEL_SLUG.get(family)
        if slug:
            slug_match = [p for p in candidates if slug in p.name]
            if slug_match:
                return slug_match[0]
        # Fall back to most recent
        return max(candidates, key=lambda p: p.stat().st_mtime)
    return candidates[0]


def parse_records(jsonl_path: Path) -> list[dict]:
    """Pull (record_id, score, is_correct) from each line."""
    rows: list[dict] = []
    with jsonl_path.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            if "record_id" not in d:
                continue
            rows.append(
                {
                    "record_id": d["record_id"],
                    "score": float(d.get("score", 0.0) or 0.0),
                    "is_correct": bool(d.get("is_correct", False)),
                }
            )
    return rows


def stratify(rows: list[dict], correct_threshold: float = 0.5) -> tuple[list, list]:
    """Split rows into (correct, incorrect) using score ≥ threshold."""
    correct, incorrect = [], []
    for r in rows:
        if r["score"] >= correct_threshold:
            correct.append(r)
        else:
            incorrect.append(r)
    return correct, incorrect


def pick(
    rows: list[dict],
    n_correct: int,
    n_incorrect: int,
    seed: int,
) -> list[GateSample]:
    """Stratified pick with graceful fallback when a stratum is short.

    Order of fallback: target → other-stratum top-up → random from leftovers.
    """
    rng = random.Random(seed)
    correct, incorrect = stratify(rows)
    rng.shuffle(correct)
    rng.shuffle(incorrect)

    picked_correct = correct[:n_correct]
    picked_incorrect = incorrect[:n_incorrect]

    # Top up shortfalls from the other stratum
    short_correct = n_correct - len(picked_correct)
    short_incorrect = n_incorrect - len(picked_incorrect)

    leftover_correct = correct[len(picked_correct) :]
    leftover_incorrect = incorrect[len(picked_incorrect) :]

    if short_correct > 0:
        topup = leftover_incorrect[:short_correct]
        picked_correct.extend(topup)
        leftover_incorrect = leftover_incorrect[short_correct:]
    if short_incorrect > 0:
        topup = leftover_correct[:short_incorrect]
        picked_incorrect.extend(topup)
        leftover_correct = leftover_correct[short_incorrect:]

    samples: list[GateSample] = []
    for r in picked_correct:
        stratum = "correct" if r["score"] >= 0.5 else "incorrect"
        samples.append(
            GateSample(
                record_id=r["record_id"],
                baseline_score=r["score"],
                stratum=stratum,
            )
        )
    for r in picked_incorrect:
        stratum = "correct" if r["score"] >= 0.5 else "incorrect"
        samples.append(
            GateSample(
                record_id=r["record_id"],
                baseline_score=r["score"],
                stratum=stratum,
            )
        )
    return samples


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--family",
        required=True,
        choices=sorted(FAMILY_TO_MODEL_SLUG.keys()),
    )
    ap.add_argument("--benchmark", required=True)
    ap.add_argument("--n", type=int, default=6, help="Total samples (default 6)")
    ap.add_argument(
        "--n-correct",
        type=int,
        default=None,
        help="Override correct-stratum size (default ceil(n/2))",
    )
    ap.add_argument(
        "--n-incorrect",
        type=int,
        default=None,
        help="Override incorrect-stratum size (default floor(n/2))",
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output path (default: experiments/<family>/<bench>/gate_set.json)",
    )
    args = ap.parse_args()

    n = args.n
    n_correct = args.n_correct if args.n_correct is not None else (n + 1) // 2
    n_incorrect = args.n_incorrect if args.n_incorrect is not None else n // 2
    if n_correct + n_incorrect != n and (
        args.n_correct is None and args.n_incorrect is None
    ):
        n_incorrect = n - n_correct

    jsonl_path = find_baseline_jsonl(args.family, args.benchmark)
    print(f"[gate-set] reading {jsonl_path}")
    rows = parse_records(jsonl_path)
    correct, incorrect = stratify(rows)
    print(
        f"[gate-set] baseline rows: {len(rows)} "
        f"({len(correct)} correct, {len(incorrect)} incorrect)"
    )

    samples = pick(rows, n_correct, n_incorrect, args.seed)
    n_pick_correct = sum(1 for s in samples if s.stratum == "correct")
    n_pick_incorrect = sum(1 for s in samples if s.stratum == "incorrect")
    print(
        f"[gate-set] picked {len(samples)} "
        f"({n_pick_correct} correct, {n_pick_incorrect} incorrect)"
    )

    out = args.out or (
        EXPERIMENTS_ROOT / args.family / args.benchmark / "gate_set.json"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    save_gate_set(
        out,
        family=args.family,
        benchmark=args.benchmark,
        samples=samples,
        extra={
            "source_jsonl": str(jsonl_path),
            "seed": args.seed,
            "requested_n": n,
            "requested_n_correct": n_correct,
            "requested_n_incorrect": n_incorrect,
        },
    )
    print(f"[gate-set] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
