"""Gate runner glue: builds a run_fn over a curated gate set.

The orchestrator's `CuratedScorer` calls our run_fn once per accepted edit.
Each call re-builds the eval backend so any system_prompt/tool overrides newly
written into ``$OPENJARVIS_HOME`` are picked up. Concurrency runs the gate's
N samples in parallel via the eval pipeline's `EvalRunner`.

Reuses ``openjarvis.evals.cli`` private helpers (``_build_backend`` et al.) —
those are stable enough across the codebase that importing is cheaper than
re-implementing.

Contract gotchas (paid for in blood):

1. ``EvalRunner.results`` is a ``@property`` returning a list copy — call it
   without parens.
2. The eval engine routes a model name to a backend via ``OPENJARVIS_CONFIG``.
   Without it, ``Qwen/Qwen3.5-9B`` falls through to the OpenAI cloud client
   and 400s with "invalid model ID" on every sample. Caller passes
   ``oj_config_path``; we set it on the env around the run.
3. The runner *will* write JSONL + summary + per-trace files to
   ``rc.output_path`` (or a default under ``results/``). For an ephemeral
   gate run that's destructive — it overwrites whatever the canonical
   ``output_dir`` of the cell is. We force ``output_path`` to a tempfile
   we can throw away after.
"""

from __future__ import annotations

import logging
import os
import tempfile
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterable

from openjarvis.core.config import load_config
from openjarvis.evals.cli import (
    _build_backend,
    _build_dataset,
    _build_judge_backend,
    _build_scorer,
)
from openjarvis.evals.core.config import expand_suite, load_eval_config
from openjarvis.evals.core.dataset import DatasetProvider
from openjarvis.evals.core.runner import EvalRunner

logger = logging.getLogger(__name__)


@contextmanager
def _env_override(**vars: str | None):
    """Set/clear env vars for the duration of a block, restore after."""
    before: dict[str, str | None] = {k: os.environ.get(k) for k in vars}
    try:
        for k, v in vars.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, prev in before.items():
            if prev is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = prev


class _GatedDataset(DatasetProvider):
    """Tiny dataset wrapper exposing only a fixed set of pre-loaded records."""

    def __init__(self, base: DatasetProvider, records: list) -> None:
        self.dataset_id = getattr(base, "dataset_id", "gated")
        self.dataset_name = getattr(base, "dataset_name", "gated")
        self._base = base
        self._records = records

    def load(self, *, max_samples=None, split=None, seed=None) -> None:
        # already populated at construction
        return

    def iter_records(self) -> Iterable:
        return iter(self._records)

    def size(self) -> int:
        return len(self._records)

    def create_task_env(self, record):
        # delegate so e.g. SWE-bench-style env creation still works
        if hasattr(self._base, "create_task_env"):
            return self._base.create_task_env(record)
        return None


def build_gate_run_fn(
    distilled_config_path: Path,
    concurrency: int,
    *,
    oj_config_path: Path | None = None,
) -> Callable[[list[str]], dict[str, float]]:
    """Construct a callable that scores a list of record_ids.

    Parameters
    ----------
    distilled_config_path
        Path to the cell's distilled.toml. Provides model, benchmark, agent,
        tools, judge — same fields ``_run_single`` reads.
    concurrency
        Number of samples to evaluate in parallel (gate set size).
    oj_config_path
        Path to the family's ``OPENJARVIS_CONFIG`` (e.g.
        ``oj_configs/config-9b.toml``). Required when the model is served
        via vLLM — without it the engine routes to OpenAI's cloud and 400s.

    Returns
    -------
    run_fn(record_ids) -> {record_id: score}
        score is the raw scorer score (typically 0.0-1.0). If unavailable,
        falls back to ``1.0 if is_correct else 0.0``.
    """
    suite = load_eval_config(str(distilled_config_path))
    run_configs = expand_suite(suite)
    if len(run_configs) != 1:
        raise ValueError(
            f"Expected exactly 1 run_config in {distilled_config_path}, "
            f"got {len(run_configs)} (one model × one benchmark per cell)."
        )
    base_rc = run_configs[0]
    oj_cfg = str(oj_config_path) if oj_config_path else None

    def run_fn(record_ids: list[str]) -> dict[str, float]:
        with _env_override(OPENJARVIS_CONFIG=oj_cfg), tempfile.TemporaryDirectory(
            prefix="oj-gate-", dir="/tmp"
        ) as tmp:
            tmp_path = Path(tmp)
            # Force eval output to the tempfile so we never overwrite the
            # cell's canonical results/.../distilled/<model>/<bench>/* files.
            tmp_jsonl = tmp_path / "gate.jsonl"
            # `load_config` is @lru_cache(maxsize=1). Once the teacher's
            # SystemBuilder runs (before us) and caches the no-OPENJARVIS_CONFIG
            # default, our env_override is silently ignored — the eval routes
            # to OpenAI's cloud client and 400s on every sample. Clear the
            # cache so the next load_config() re-reads our overridden env.
            load_config.cache_clear()

            dataset = _build_dataset(base_rc.benchmark)
            dataset.load(max_samples=None, split=None, seed=base_rc.seed)
            wanted = set(record_ids)
            filtered = [r for r in dataset.iter_records() if r.record_id in wanted]
            missing = wanted - {r.record_id for r in filtered}
            if missing:
                logger.warning(
                    "Gate: %d gate-set record_ids not found in dataset: %s",
                    len(missing),
                    sorted(missing)[:3],
                )
            gated = _GatedDataset(dataset, filtered)

            rc_local = replace(
                base_rc,
                max_samples=None,
                max_workers=concurrency,
                output_path=str(tmp_jsonl),
            )

            eval_backend = _build_backend(
                rc_local.backend,
                rc_local.engine_key,
                rc_local.agent_name or "orchestrator",
                rc_local.tools,
                telemetry=getattr(rc_local, "telemetry", False),
                gpu_metrics=getattr(rc_local, "gpu_metrics", False),
                model=rc_local.model,
                max_turns=getattr(rc_local, "max_turns", None),
            )
            judge_backend = _build_judge_backend(
                rc_local.judge_model,
                engine_key=getattr(rc_local, "judge_engine", "cloud") or "cloud",
            )
            scorer = _build_scorer(
                rc_local.benchmark, judge_backend, rc_local.judge_model
            )

            runner = EvalRunner(rc_local, gated, eval_backend, scorer)
            try:
                runner.run()
            finally:
                try:
                    eval_backend.close()
                except Exception:
                    pass
                if judge_backend is not None:
                    try:
                        judge_backend.close()
                    except Exception:
                        pass

            # results is a @property returning a list copy — no parens.
            scores: dict[str, float] = {}
            for r in runner.results:
                if r.score is not None:
                    scores[r.record_id] = float(r.score)
                elif r.is_correct is not None:
                    scores[r.record_id] = 1.0 if r.is_correct else 0.0
                else:
                    scores[r.record_id] = 0.0
            # Fill in any missing ids as 0 (couldn't run) — gate will see them
            # as full regression. Better than silent omission.
            for rid in record_ids:
                scores.setdefault(rid, 0.0)
            return scores

    return run_fn


__all__ = ["build_gate_run_fn"]
