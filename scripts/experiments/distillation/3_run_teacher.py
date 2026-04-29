#!/usr/bin/env python3
"""Step 3 — Run the M1 teacher on scored traces to produce plan.json files.

Wires DistillationOrchestrator directly with production deps (CloudEngine
teacher, VLLMStudentRunner student, TraceJudge judge). The previous
implementation shelled out to ``jarvis learning run``, which is a CLI stub
and never actually constructed the orchestrator. The orchestrator wiring
copied here is the same block used by ``ablation/run_ablations.sh``.

Reads scored traces from --traces-db (or $TRACES_DB, or
$OPENJARVIS_HOME/traces.db) and writes one plan.json per session to
$OPENJARVIS_HOME/learning/sessions/<session_id>/plan.json. Step 4 walks
those plan.json files to compute consensus edits.

With --n-sessions N>1, fans out N sessions in parallel, each in its own
isolated home (`<base_home>-<idx>/`) so git/SQLite locks don't race. Each
child gets a fresh copy of the parent's traces.db and its own
CheckpointStore. Step 4 can then walk all child homes' session dirs.

Usage:
    # one session
    python 3_run_teacher.py \\
        --student-hf Qwen/Qwen3.5-9B \\
        --vllm-host http://localhost:8001

    # ensemble of 5 parallel sessions
    python 3_run_teacher.py --n-sessions 5
"""

from __future__ import annotations


# distill-streaming-fix
import logging as _logging
import sys as _sys
try:
    _sys.stdout.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
    _sys.stderr.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
except AttributeError:
    pass
_logging.basicConfig(
    level=_logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=_sys.stdout,
    force=True,
)

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--student-hf",
        default="Qwen/Qwen3.5-9B",
        help="HuggingFace ID the vLLM server is serving (e.g. Qwen/Qwen3.5-9B).",
    )
    parser.add_argument(
        "--vllm-host",
        default=os.environ.get("VLLM_HOST", "http://localhost:8001"),
        help="vLLM OpenAI-compatible endpoint for the student.",
    )
    parser.add_argument(
        "--traces-db",
        type=Path,
        default=None,
        help=(
            "Path to a traces.db with feedback already seeded by step 2. "
            "Falls back to $TRACES_DB, then $OPENJARVIS_HOME/traces.db, "
            "then ~/.openjarvis/traces.db."
        ),
    )
    parser.add_argument(
        "--teacher-model",
        default="claude-opus-4-6",
        help="Teacher model passed to CloudEngine (Anthropic/OpenAI/Gemini).",
    )
    parser.add_argument(
        "--judge-model",
        default="gpt-5-mini-2025-08-07",
        help="Judge model used by the orchestrator's TraceJudge.",
    )
    parser.add_argument(
        "--autonomy",
        choices=["auto", "tiered", "manual"],
        default="auto",
        help="Autonomy mode for edit application.",
    )
    parser.add_argument("--max-cost-usd", type=float, default=5.0)
    parser.add_argument("--max-tool-calls", type=int, default=30)
    parser.add_argument("--min-traces", type=int, default=10)
    parser.add_argument("--subsample-size", type=int, default=50)
    parser.add_argument(
        "--config-name",
        default="qwen-9b",
        help="Slug used in session dir name (<home>/learning/sessions/<slug>__...).",
    )
    parser.add_argument(
        "--experiment",
        default="m1",
        help="Experiment slug used in session dir name.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional path to write a result.json summary.",
    )
    parser.add_argument(
        "--n-sessions",
        type=int,
        default=50,
        help=(
            "Number of parallel sessions to run. Each gets its own isolated "
            "home under --ensemble-dir (001/, 002/, ...)."
        ),
    )
    parser.add_argument(
        "--ensemble-dir",
        type=Path,
        default=None,
        help=(
            "Container directory for an ensemble run. Required when "
            "--n-sessions > 1. Layout: "
            "<ensemble-dir>/{traces.db, summary.json, logs/, runs/NNN/, "
            "sessions/NNN -> runs/NNN/learning/sessions/<id>/}. "
            "Default if omitted: <parent_home>/ensembles/<UTC-timestamp>/."
        ),
    )
    parser.add_argument(
        "--max-parallel",
        type=int,
        default=None,
        help=(
            "Cap concurrent child processes when --n-sessions > 1. "
            "Default: all run at once."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve config and exit without invoking the orchestrator.",
    )
    parser.add_argument(
        "--config-only",
        action="store_true",
        help=(
            "Restrict the teacher to OpenJarvis-config edits only. Skips any "
            "proposed system-prompt or few-shot exemplar edits (PATCH_SYSTEM_"
            "PROMPT, REPLACE_SYSTEM_PROMPT, EDIT_FEW_SHOT_EXEMPLARS). The "
            "teacher may still emit them in the plan — they just never apply."
        ),
    )
    # ── Gate (optional) ──────────────────────────────────────────────────
    parser.add_argument(
        "--family",
        default=None,
        help=(
            "Family slug (e.g. qwen9b, gemma26b). When set with --benchmark, "
            "auto-resolves --gate-set and --gate-config from "
            "~/.openjarvis/experiments/<family>/<benchmark>/."
        ),
    )
    parser.add_argument(
        "--benchmark",
        default=None,
        help="Benchmark slug (e.g. gaia, liveresearch). See --family.",
    )
    parser.add_argument(
        "--gate-set",
        type=Path,
        default=None,
        help=(
            "Path to gate_set.json. If --family + --benchmark are given, "
            "defaults to ~/.openjarvis/experiments/<family>/<benchmark>/gate_set.json."
        ),
    )
    parser.add_argument(
        "--gate-config",
        type=Path,
        default=None,
        help=(
            "Path to distilled.toml driving the gate eval. If --family + "
            "--benchmark are given, defaults to "
            "~/.openjarvis/experiments/<family>/<benchmark>/new_configs/distilled.toml."
        ),
    )
    parser.add_argument(
        "--gate-min-improvement",
        type=float,
        default=0.0,
        help="BenchmarkGate min_improvement (default 0.0 — accept any non-regression).",
    )
    parser.add_argument(
        "--gate-max-regression",
        type=float,
        default=0.2,
        help="BenchmarkGate max_regression per task-cluster (default 0.2).",
    )
    return parser


_FAMILY_TO_OJ_CONFIG = {
    "qwen9b": "/matx/u/aspark/.openjarvis/oj_configs/config-9b.toml",
    "gemma26b": "/matx/u/aspark/.openjarvis/oj_configs/config-26b.toml",
}


def _resolve_gate_paths(
    args: argparse.Namespace,
) -> tuple[Path | None, Path | None, Path | None]:
    """Compute (gate_set_path, gate_config_path, oj_config_path)."""
    gate_set = args.gate_set
    gate_config = args.gate_config
    oj_config: Path | None = None
    if args.family:
        cand = Path(_FAMILY_TO_OJ_CONFIG.get(args.family, ""))
        if cand and cand.exists():
            oj_config = cand
    if (gate_set is None or gate_config is None) and args.family and args.benchmark:
        cell = (
            Path("/matx/u/aspark/.openjarvis/experiments")
            / args.family
            / args.benchmark
        )
        if gate_set is None:
            cand = cell / "gate_set.json"
            if cand.exists():
                gate_set = cand
        if gate_config is None:
            cand = cell / "new_configs" / "distilled.toml"
            if cand.exists():
                gate_config = cand
    return gate_set, gate_config, oj_config


def setup_isolated_home(parent_traces_db: Path, child_home: Path) -> None:
    """Provision a fresh isolated $OPENJARVIS_HOME from a parent traces.db."""
    from openjarvis.learning.distillation.checkpoint.store import CheckpointStore
    from openjarvis.learning.distillation.storage.paths import (
        ensure_distillation_dirs,
    )

    child_home.mkdir(parents=True, exist_ok=True)
    dst_db = child_home / "traces.db"
    if not dst_db.exists():
        shutil.copy(parent_traces_db, dst_db)

    prev = os.environ.get("OPENJARVIS_HOME")
    os.environ["OPENJARVIS_HOME"] = str(child_home)
    try:
        ensure_distillation_dirs()
        CheckpointStore(child_home).init()
    finally:
        if prev is None:
            os.environ.pop("OPENJARVIS_HOME", None)
        else:
            os.environ["OPENJARVIS_HOME"] = prev


def run_one_session(args: argparse.Namespace, home: Path, traces_db: Path) -> dict:
    """Construct the orchestrator and run a single session. Returns a result dict."""
    from openjarvis.engine.cloud import CloudEngine
    from openjarvis.evals.backends.jarvis_direct import JarvisDirectBackend
    from openjarvis.learning.distillation.checkpoint.store import CheckpointStore
    from openjarvis.learning.distillation.models import AutonomyMode
    from openjarvis.learning.distillation.orchestrator import (
        DistillationOrchestrator,
    )
    from openjarvis.learning.distillation.storage.session_store import SessionStore
    from openjarvis.learning.distillation.student_runner import (
        VLLMStudentRunner,
        build_benchmark_samples_from_traces,
    )
    from openjarvis.learning.distillation.triggers import OnDemandTrigger
    from openjarvis.learning.optimize.feedback.judge import TraceJudge
    from openjarvis.traces.store import TraceStore

    student_runner = VLLMStudentRunner(host=args.vllm_host, model=args.student_hf)
    cloud_engine = CloudEngine()
    judge_backend = JarvisDirectBackend(engine_key="cloud")
    judge = TraceJudge(backend=judge_backend, model=args.judge_model)

    trace_store = TraceStore(traces_db)
    benchmark_samples = build_benchmark_samples_from_traces(
        trace_store, limit=args.subsample_size
    )
    print(f"[step3] benchmark_samples built: {len(benchmark_samples)}")

    autonomy = AutonomyMode(args.autonomy)

    # Build CuratedScorer if a gate set is available for this cell.
    scorer = None
    gate_set_path, gate_config_path, oj_config_path = _resolve_gate_paths(args)
    if gate_set_path is not None and gate_config_path is not None:
        from openjarvis.learning.distillation.gate.curated_scorer import (
            CuratedScorer,
            load_gate_set,
        )

        # Local import keeps eval-pipeline deps out of paths that don't gate.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _gate_runner import build_gate_run_fn  # type: ignore

        meta, samples = load_gate_set(gate_set_path)
        if oj_config_path is None:
            print(
                "[step3] WARNING: --family did not resolve an OPENJARVIS_CONFIG; "
                "the gate eval may route to OpenAI cloud and 400 on every sample."
            )
        run_fn = build_gate_run_fn(
            distilled_config_path=gate_config_path,
            concurrency=len(samples),
            oj_config_path=oj_config_path,
        )
        scorer = CuratedScorer(gate_set=samples, run_fn=run_fn)
        if autonomy == AutonomyMode.AUTO:
            print(
                f"[step3] gate enabled (n={len(samples)}); "
                f"upgrading autonomy auto -> tiered so the gate actually runs"
            )
            autonomy = AutonomyMode.TIERED
        else:
            print(f"[step3] gate enabled (n={len(samples)}, autonomy={autonomy.value})")
        print(f"[step3] gate oj_config = {oj_config_path}")
    elif gate_set_path is not None or gate_config_path is not None:
        print(
            f"[step3] gate partial config — gate_set={gate_set_path}, "
            f"gate_config={gate_config_path}; both required, skipping gate"
        )

    orch = DistillationOrchestrator(
        teacher_engine=cloud_engine,
        teacher_model=args.teacher_model,
        trace_store=trace_store,
        benchmark_samples=benchmark_samples,
        student_runner=student_runner,
        judge=judge,
        session_store=SessionStore(home / "learning" / "learning.db"),
        checkpoint_store=CheckpointStore(home),
        openjarvis_home=home,
        autonomy_mode=autonomy,
        scorer=scorer,
        min_traces=args.min_traces,
        max_cost_usd=args.max_cost_usd,
        max_tool_calls=args.max_tool_calls,
        subsample_size=args.subsample_size,
        min_improvement=args.gate_min_improvement,
        max_regression=args.gate_max_regression,
        config_only=args.config_only,
    )

    session = orch.run(
        OnDemandTrigger(
            metadata={
                "config_name": args.config_name,
                "experiment": args.experiment,
                "traces_db": str(traces_db),
            }
        )
    )

    return {
        "session_id": session.id,
        "status": session.status.value,
        "cost_usd": session.teacher_cost_usd,
        "edits_total": len(session.edit_outcomes),
        "edits_applied": len(
            [o for o in session.edit_outcomes if o.status == "applied"]
        ),
        "edits_rejected": len(
            [o for o in session.edit_outcomes if o.status == "rejected_by_gate"]
        ),
        "error": session.error,
        "session_dir": str(home / "learning" / "sessions" / session.id),
    }


def fanout_main(args: argparse.Namespace, parent_home: Path, traces_db: Path) -> int:
    """Launch N child invocations of this script in parallel under --ensemble-dir.

    Layout::

        <ensemble-dir>/
          traces.db                        # canonical source (copied)
          summary.json                     # aggregate result
          logs/session_NNN.{log,json}      # per-child stdout + result JSON
          runs/NNN/                        # full $OPENJARVIS_HOME for child
            traces.db, .git/, learning/sessions/<id>/
          sessions/NNN -> ../runs/NNN/learning/sessions/<id>/   (symlinks)
    """
    from datetime import datetime, timezone

    n = args.n_sessions
    cap = args.max_parallel or n

    ensemble_dir = args.ensemble_dir
    if ensemble_dir is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        ensemble_dir = parent_home / "ensembles" / ts
    ensemble_dir = ensemble_dir.resolve()
    ensemble_dir.mkdir(parents=True, exist_ok=True)

    runs_dir = ensemble_dir / "runs"
    log_dir = ensemble_dir / "logs"
    sessions_dir = ensemble_dir / "sessions"
    runs_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)

    canonical_db = ensemble_dir / "traces.db"
    if not canonical_db.exists():
        shutil.copy(traces_db, canonical_db)

    children: list[tuple[int, Path, subprocess.Popen, Path]] = []
    results: list[dict] = []
    failed: list[tuple[int, int]] = []

    print(f"[step3] fan-out: {n} sessions, max_parallel={cap}")
    print(f"[step3] ensemble_dir = {ensemble_dir}")
    print(f"[step3] traces_db    = {canonical_db}")

    script = Path(__file__).resolve()

    started = 0
    finished = 0
    while finished < n:
        # launch up to cap concurrently
        while started < n and (started - finished) < cap:
            idx = started + 1
            child_home = runs_dir / f"{idx:03d}"
            print(f"[step3] launching session {idx}/{n} → {child_home}")
            try:
                setup_isolated_home(canonical_db, child_home)
            except Exception as e:
                print(f"[step3] setup failed for session {idx}: {e}", file=sys.stderr)
                failed.append((idx, -1))
                started += 1
                finished += 1
                continue

            child_log = log_dir / f"session_{idx:03d}.log"
            child_out = log_dir / f"session_{idx:03d}.json"
            child_env = os.environ.copy()
            child_env["OPENJARVIS_HOME"] = str(child_home)

            cmd = [
                sys.executable,
                str(script),
                "--n-sessions", "1",
                "--student-hf", args.student_hf,
                "--vllm-host", args.vllm_host,
                "--teacher-model", args.teacher_model,
                "--judge-model", args.judge_model,
                "--autonomy", args.autonomy,
                "--max-cost-usd", str(args.max_cost_usd),
                "--max-tool-calls", str(args.max_tool_calls),
                "--min-traces", str(args.min_traces),
                "--subsample-size", str(args.subsample_size),
                "--config-name", f"{args.config_name}-{idx:03d}",
                "--experiment", args.experiment,
                "--out", str(child_out),
            ]
            if args.config_only:
                cmd.append("--config-only")
            log_fp = open(child_log, "w")
            proc = subprocess.Popen(
                cmd, env=child_env, stdout=log_fp, stderr=subprocess.STDOUT
            )
            children.append((idx, child_home, proc, child_out))
            started += 1

        # poll
        time.sleep(2.0)
        still_running = []
        for idx, ch_home, proc, out_path in children:
            rc = proc.poll()
            if rc is None:
                still_running.append((idx, ch_home, proc, out_path))
                continue
            finished += 1
            if rc == 0 and out_path.exists():
                try:
                    res = json.loads(out_path.read_text())
                    res["_session_idx"] = idx
                    res["_home"] = str(ch_home)
                    results.append(res)
                    print(
                        f"[step3] session {idx}/{n} done: "
                        f"status={res['status']} "
                        f"cost=${res['cost_usd']:.2f} "
                        f"edits={res['edits_applied']}/{res['edits_total']}"
                    )
                except Exception as e:
                    print(f"[step3] session {idx} parse error: {e}", file=sys.stderr)
                    failed.append((idx, rc))
            else:
                print(
                    f"[step3] session {idx}/{n} FAILED rc={rc} "
                    f"(see {log_dir}/session_{idx:03d}.log)",
                    file=sys.stderr,
                )
                failed.append((idx, rc))
        children = still_running

    # Symlink each child's session dir into <ensemble-dir>/sessions/NNN
    # so step 4 can walk one tidy directory.
    for r in results:
        idx = r["_session_idx"]
        src = Path(r["session_dir"])
        link = sessions_dir / f"{idx:03d}"
        if link.exists() or link.is_symlink():
            link.unlink()
        try:
            link.symlink_to(src)
        except OSError as e:
            print(f"[step3] symlink failed for {idx}: {e}", file=sys.stderr)

    summary = {
        "ensemble_dir": str(ensemble_dir),
        "traces_db": str(canonical_db),
        "n_sessions_requested": n,
        "n_sessions_succeeded": len(results),
        "n_sessions_failed": len(failed),
        "total_cost_usd": sum(r.get("cost_usd", 0.0) for r in results),
        "total_edits_applied": sum(r.get("edits_applied", 0) for r in results),
        "sessions": results,
        "failed": [{"idx": i, "rc": rc} for i, rc in failed],
    }
    summary_path = ensemble_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))

    print()
    print("════════════════════════════════════════════════════════")
    print(f"  ENSEMBLE SUMMARY  ({len(results)}/{n} succeeded)")
    print("════════════════════════════════════════════════════════")
    print(f"  ensemble_dir    : {ensemble_dir}")
    print(f"  total cost      : ${summary['total_cost_usd']:.2f}")
    print(f"  total edits     : {summary['total_edits_applied']} applied")
    for r in results:
        print(
            f"  [{r['_session_idx']:03d}] {r['status']} "
            f"${r['cost_usd']:.2f} "
            f"{r['edits_applied']}/{r['edits_total']}  "
            f"{r['session_dir']}"
        )
    if failed:
        print(f"  failed sessions : {[i for i, _ in failed]}")
    print(f"  → walk for step 4: {sessions_dir}/")
    print(f"  → wrote {summary_path}")

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(summary, indent=2))
        print(f"[step3] wrote {args.out}")

    return 0 if not failed else 2


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    home = Path(
        os.environ.get("OPENJARVIS_HOME", str(Path.home() / ".openjarvis"))
    )

    traces_db = (
        args.traces_db
        or (Path(os.environ["TRACES_DB"]) if os.environ.get("TRACES_DB") else None)
        or home / "traces.db"
    )

    if not traces_db.exists():
        print(f"ERROR: traces db not found: {traces_db}", file=sys.stderr)
        return 1

    if not os.environ.get("ANTHROPIC_API_KEY") and args.teacher_model.startswith(
        "claude-"
    ):
        print(
            "ERROR: ANTHROPIC_API_KEY not set; required for Claude teacher.",
            file=sys.stderr,
        )
        return 1

    print(f"[step3] home         = {home}")
    print(f"[step3] traces_db    = {traces_db}")
    print(f"[step3] teacher      = {args.teacher_model}")
    print(f"[step3] judge        = {args.judge_model}")
    print(f"[step3] student_hf   = {args.student_hf}")
    print(f"[step3] vllm_host    = {args.vllm_host}")
    print(f"[step3] autonomy     = {args.autonomy}")
    print(f"[step3] max_cost_usd = {args.max_cost_usd}")
    print(f"[step3] max_tools    = {args.max_tool_calls}")
    print(f"[step3] min_traces   = {args.min_traces}")
    print(f"[step3] n_sessions   = {args.n_sessions}")
    print(f"[step3] config_only  = {args.config_only}")
    gate_set_path, gate_config_path, oj_config_path = _resolve_gate_paths(args)
    print(f"[step3] gate_set     = {gate_set_path or '(none — gate disabled)'}")
    print(f"[step3] gate_config  = {gate_config_path or '(none)'}")
    print(f"[step3] oj_config    = {oj_config_path or '(none)'}")

    if args.dry_run:
        return 0

    if args.n_sessions > 1:
        return fanout_main(args, home, traces_db)

    result = run_one_session(args, home, traces_db)
    print(json.dumps(result, indent=2))

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2))
        print(f"[step3] wrote {args.out}")

    return 0 if result["error"] is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
