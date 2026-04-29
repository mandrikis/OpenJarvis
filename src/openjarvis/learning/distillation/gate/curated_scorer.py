"""CuratedScorer: gate scorer over a small curated per-cell sample set.

Decouples from the eval pipeline by accepting a ``run_fn`` callback that maps
record_ids to fresh scores. The first call (orchestrator's "before" snapshot)
returns cached baseline scores without running inference; subsequent calls
("after" each accepted edit) invoke run_fn.

See `gate/benchmark_gate.py` for the gate decision logic that consumes the
``BenchmarkSnapshot`` we return.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from openjarvis.learning.distillation.models import BenchmarkSnapshot

logger = logging.getLogger(__name__)


@dataclass
class GateSample:
    """One curated gate sample with its baseline score."""

    record_id: str
    baseline_score: float
    stratum: str  # "correct" | "incorrect"


# run_fn(record_ids) -> {record_id: score}
RunFn = Callable[[list[str]], dict[str, float]]


def load_gate_set(path: Path) -> tuple[dict, list[GateSample]]:
    """Load a gate_set.json. Returns (header_meta, samples)."""
    data = json.loads(Path(path).read_text())
    samples = [GateSample(**s) for s in data["samples"]]
    meta = {k: v for k, v in data.items() if k != "samples"}
    return meta, samples


def save_gate_set(
    path: Path,
    family: str,
    benchmark: str,
    samples: list[GateSample],
    extra: dict | None = None,
) -> None:
    """Write a gate_set.json."""
    payload = {
        "family": family,
        "benchmark": benchmark,
        "n_samples": len(samples),
        "samples": [asdict(s) for s in samples],
    }
    if extra:
        payload.update(extra)
    Path(path).write_text(json.dumps(payload, indent=2))


class CuratedScorer:
    """Score a small curated gate set for the BenchmarkGate.

    First call returns the cached baseline snapshot — no inference run. Every
    subsequent call invokes ``run_fn`` over the gate-set record_ids and builds
    a fresh snapshot. Each task becomes its own cluster (``task_<record_id>``)
    so the gate's regression check can fail on any single-task drop.

    Parameters
    ----------
    gate_set
        Curated samples (record_id + cached baseline_score).
    run_fn
        Callable that takes a list of record_ids and returns
        ``{record_id: score}``. Score 1.0 = resolved/correct, 0.0 = unresolved.
        run_fn is responsible for running the agent concurrently and judging.
    benchmark_version
        Tag to embed in the snapshot (default ``"curated_v1"``).
    """

    def __init__(
        self,
        *,
        gate_set: list[GateSample],
        run_fn: RunFn,
        benchmark_version: str = "curated_v1",
    ) -> None:
        if not gate_set:
            raise ValueError("CuratedScorer requires a non-empty gate_set")
        self._gate_set = gate_set
        self._run_fn = run_fn
        self._benchmark_version = benchmark_version
        self._before_returned = False

    def __call__(
        self,
        *,
        benchmark_version: str | None = None,  # ignored — we own ours
        subsample_size: int | None = None,  # ignored — gate-set size is fixed
        seed: int | None = None,  # ignored — gate-set is curated
        **_: object,
    ) -> BenchmarkSnapshot:
        if not self._before_returned:
            self._before_returned = True
            scores = {s.record_id: s.baseline_score for s in self._gate_set}
            elapsed = 0.0
            logger.info(
                "Gate before-snapshot served from cache (n=%d, mean=%.3f)",
                len(scores),
                sum(scores.values()) / len(scores),
            )
        else:
            ids = [s.record_id for s in self._gate_set]
            t0 = time.time()
            scores = self._run_fn(ids)
            elapsed = time.time() - t0
            logger.info(
                "Gate after-snapshot ran in %.1fs (n=%d, mean=%.3f)",
                elapsed,
                len(scores),
                (sum(scores.values()) / len(scores)) if scores else 0.0,
            )

        cluster_scores = {f"task_{rid}": score for rid, score in scores.items()}
        overall = sum(scores.values()) / len(scores) if scores else 0.0

        return BenchmarkSnapshot(
            benchmark_version=self._benchmark_version,
            overall_score=overall,
            cluster_scores=cluster_scores,
            task_count=len(scores),
            elapsed_seconds=elapsed,
        )


__all__ = ["GateSample", "CuratedScorer", "load_gate_set", "save_gate_set"]
