#!/usr/bin/env python3
"""Render distilled eval configs from the matrix + a consensus_edits.json.

For every (application, experiment) pair in pipeline_matrix.toml, this writes
one TOML config to the matrix's `distilled_configs_dir`. The distilled config
is a clone of the baseline with the consensus edits applied:

  - set_agent_param(temperature)  → [defaults].temperature
  - set_agent_param(max_turns)    → recorded in the comment (applied at runtime
                                    via OPENJARVIS_CONFIG; see _eval_runner.py)
  - remove_tool_from_agent        → drop from [[benchmarks]].tools
  - add_tool_to_agent             → append to [[benchmarks]].tools

Control experiments (`is_control = true`) are written but with the consensus
edits *not* applied — so direct/coding/reasoning benchmarks act as a
no-distillation control. A consensus edit also has no effect on a non-agent
benchmark.

Inputs:
    --matrix    pipeline_matrix.toml   (default: alongside this script)
    --consensus consensus_edits.json   (default: results/.../consensus/consensus_edits.json)

Outputs:
    Distilled TOMLs written to matrix.paths.distilled_configs_dir/
    A summary printed to stdout (which configs were generated, what changed).
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
import sys
from pathlib import Path

# tomllib is stdlib on 3.11+. On older runtimes, install tomli.
try:
    import tomllib  # type: ignore[import-not-found]
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

REPO_ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
DEFAULT_MATRIX = HERE / "pipeline_matrix.toml"
DEFAULT_CONSENSUS = (
    REPO_ROOT
    / "results"
    / "neurips-2026"
    / "distillation-m2"
    / "consensus"
    / "consensus_edits.json"
)


# ── Consensus extraction helpers ─────────────────────────────────────────────


def extract_temperature(consensus: dict) -> float | None:
    """Pick the highest-voted temperature edit across set_agent_param /
    set_model_param. Different teachers use different ops with the same
    intent; we accept either."""
    candidates: list[tuple[int, float]] = []
    for e in consensus.get("scalar_edits", []):
        if e["op"] in ("set_agent_param", "set_model_param") and e[
            "target"
        ].endswith(".temperature"):
            candidates.append((int(e.get("votes", 0)), float(e["value"])))
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: -x[0])[0][1]


def extract_max_turns(consensus: dict) -> int | None:
    candidates: list[tuple[int, int]] = []
    for e in consensus.get("scalar_edits", []):
        if e["op"] in ("set_agent_param", "set_model_param") and e[
            "target"
        ].endswith(".max_turns"):
            candidates.append((int(e.get("votes", 0)), int(e["value"])))
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: -x[0])[0][1]


def extract_remove_tools(consensus: dict) -> set[str]:
    return {t["tool_name"] for t in consensus.get("remove_tools", [])}


def extract_add_tools(consensus: dict) -> set[str]:
    return {t["tool_name"] for t in consensus.get("add_tools", [])}


def extract_query_class_routing(consensus: dict) -> dict[str, str]:
    """Extract set_model_for_query_class edits → {query_class: model}."""
    routing: dict[str, tuple[int, str]] = {}
    for e in consensus.get("scalar_edits", []):
        if e["op"] != "set_model_for_query_class":
            continue
        qc = e["target"]
        votes = int(e.get("votes", 0))
        prev = routing.get(qc)
        if prev is None or votes > prev[0]:
            routing[qc] = (votes, str(e["value"]))
    return {qc: v for qc, (_, v) in routing.items()}


def _pick_highest_voted_per_target(items: list[dict]) -> dict[str, dict]:
    """For deferred-text edits, pick the highest-voted entry per target.
    Items are from consensus.deferred_to_m3.<op>; each has target/payload/votes.
    Ties broken by sample_session_ids[0] ascending for determinism."""
    by_target: dict[str, dict] = {}
    for item in items:
        target = item.get("target", "")
        votes = int(item.get("votes", 0))
        prev = by_target.get(target)
        if (
            prev is None
            or votes > int(prev.get("votes", 0))
            or (
                votes == int(prev.get("votes", 0))
                and (item.get("sample_session_ids") or [""])
                < (prev.get("sample_session_ids") or [""])
            )
        ):
            by_target[target] = item
    return by_target


def _agent_name_from_target(target: str) -> str:
    """'agents.monitor_operative.system_prompt' → 'monitor_operative'."""
    parts = target.split(".")
    if len(parts) >= 2 and parts[0] == "agents":
        return parts[1]
    return parts[0] if parts else "default"


def _tool_name_from_target(target: str) -> str:
    """'tools.web_search.description' → 'web_search'."""
    parts = target.split(".")
    if len(parts) >= 2 and parts[0] == "tools":
        return parts[1]
    return parts[0] if parts else "default"


def _items_for_op(consensus: dict, op: str) -> list[dict]:
    """Source priority for the deferred-text edit per (op, target):

    1. ``consensus.llm_synthesized[op]`` — step 4 synthesized one payload per
       target by combining recurring themes across all candidates (preferred).
    2. ``consensus.llm_selected[op]`` — step 4 picked the most representative
       existing candidate per target.
    3. ``consensus.deferred_to_m3[op]`` — raw candidate list, with step 5
       falling back to lexicographic tiebreak in
       ``_pick_highest_voted_per_target``.
    """
    synth = (consensus.get("llm_synthesized") or {}).get(op) or []
    if synth:
        return synth
    llm = (consensus.get("llm_selected") or {}).get(op) or []
    if llm:
        return llm
    return (consensus.get("deferred_to_m3") or {}).get(op) or []


def extract_system_prompts(consensus: dict) -> dict[str, str]:
    """{agent_name: new_prompt_content} from replace_system_prompt deferred edits."""
    items = _items_for_op(consensus, "replace_system_prompt")
    picked = _pick_highest_voted_per_target(items)
    out: dict[str, str] = {}
    for target, item in picked.items():
        agent = _agent_name_from_target(target)
        new_content = (item.get("payload") or {}).get("new_content")
        if isinstance(new_content, str) and new_content.strip():
            out[agent] = new_content
    return out


def extract_few_shot_exemplars(consensus: dict) -> dict[str, list]:
    """{agent_name: [exemplars...]}."""
    items = _items_for_op(consensus, "edit_few_shot_exemplars")
    picked = _pick_highest_voted_per_target(items)
    out: dict[str, list] = {}
    for target, item in picked.items():
        agent = _agent_name_from_target(target)
        exemplars = (item.get("payload") or {}).get("exemplars")
        if isinstance(exemplars, list) and exemplars:
            out[agent] = exemplars
    return out


def extract_tool_descriptions(consensus: dict) -> dict[str, str]:
    """{tool_name: new_description}."""
    items = _items_for_op(consensus, "edit_tool_description")
    picked = _pick_highest_voted_per_target(items)
    out: dict[str, str] = {}
    for target, item in picked.items():
        tool = _tool_name_from_target(target)
        payload = item.get("payload") or {}
        new_desc = payload.get("new_description") or payload.get("description")
        if isinstance(new_desc, str) and new_desc.strip():
            out[tool] = new_desc
    return out


# ── TOML rendering ───────────────────────────────────────────────────────────


def render_config(
    *,
    comment: str | list[str],
    meta_name: str,
    description: str,
    temperature: float,
    max_tokens: int,
    judge_model: str,
    judge_engine: str,
    output_dir: str,
    model_name: str,
    model_engine: str,
    num_gpus: int,
    benchmark_name: str,
    backend: str,
    agent: str | None = None,
    tools: list[str] | None = None,
    max_samples: int | None = None,
    extra_benchmark: dict | None = None,
    seed: int = 42,
    max_turns: int | None = None,
    overrides: dict | None = None,
) -> str:
    comment_lines = [comment] if isinstance(comment, str) else list(comment)
    lines: list[str] = [f"# {c}" for c in comment_lines]
    lines += [
        "[meta]",
        f'name = "{meta_name}"',
        f'description = "{description}"',
        "",
        "[defaults]",
        f"temperature = {temperature}",
        f"max_tokens = {max_tokens}",
        "",
        "[judge]",
        f'model = "{judge_model}"',
        "temperature = 0.0",
    ]
    if judge_engine:
        lines.append(f'engine = "{judge_engine}"')
    lines += [
        "max_tokens = 4096",
        "",
        "[run]",
        "max_workers = 4",
        f'output_dir = "{output_dir}"',
        f"seed = {seed}",
    ]
    if max_turns is not None:
        lines.append(f"max_turns = {int(max_turns)}")
    lines += [
        "",
        "[[models]]",
        f'name = "{model_name}"',
        f'engine = "{model_engine}"',
        f"num_gpus = {num_gpus}",
        "",
        "[[benchmarks]]",
        f'name = "{benchmark_name}"',
        f'backend = "{backend}"',
    ]
    if agent:
        lines.append(f'agent = "{agent}"')
    if max_samples:
        lines.append(f"max_samples = {max_samples}")
    if tools is not None:
        tools_str = ", ".join(f'"{t}"' for t in tools)
        lines.append(f"tools = [{tools_str}]")
    if extra_benchmark:
        for k, v in extra_benchmark.items():
            if isinstance(v, str):
                lines.append(f'{k} = "{v}"')
            elif isinstance(v, bool):
                lines.append(f"{k} = {str(v).lower()}")
            else:
                lines.append(f"{k} = {v}")

    if overrides:
        sp = overrides.get("system_prompt") or {}
        fs = overrides.get("few_shot") or {}
        td = overrides.get("tool_descriptions") or {}
        if sp:
            lines.append("")
            lines.append("[benchmarks.overrides.system_prompt]")
            for agent_name, content in sp.items():
                lines.append(f"{agent_name} = {_toml_multiline(content)}")
        if fs:
            for agent_name, exemplars in fs.items():
                for ex in exemplars:
                    lines.append("")
                    lines.append(
                        f"[[benchmarks.overrides.few_shot.{agent_name}]]"
                    )
                    lines.append(
                        f"input = {_toml_multiline(str(ex.get('input', '')))}"
                    )
                    lines.append(
                        f"output = {_toml_multiline(str(ex.get('output', '')))}"
                    )
        if td:
            lines.append("")
            lines.append("[benchmarks.overrides.tool_descriptions]")
            for tool_name, desc in td.items():
                single_line = " ".join(str(desc).split())
                escaped = single_line.replace('"', '\\"')
                lines.append(f'{tool_name} = "{escaped}"')

    lines.append("")
    return "\n".join(lines)


def _toml_multiline(s: str) -> str:
    """Render a string as a TOML literal — triple-quoted if multi-line."""
    if "\n" in s or '"' in s:
        # Triple-quoted basic string; escape backslashes and triple quotes.
        body = s.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
        return f'"""\n{body}\n"""'
    return json.dumps(s, ensure_ascii=False)


# ── Per-(app, experiment) distilled config ───────────────────────────────────


def make_distilled_config(
    *,
    app: dict,
    exp: dict,
    paths: dict,
    consensus_temp: float | None,
    consensus_max_turns: int | None,
    remove_tools: set[str],
    add_tools: set[str],
    routing: dict[str, str] | None = None,
    has_prompt_overrides: bool = False,
    has_few_shot: bool = False,
    has_tool_desc: bool = False,
    embed_overrides: dict | None = None,
    max_samples_override: int | None = None,
    output_dir_override: str | None = None,
    meta_name_override: str | None = None,
    seed: int = 42,
) -> tuple[Path, str, list[str]]:
    """Render one distilled TOML and return (path, content, change_log)."""
    bench_name = exp.get("benchmark_name", exp["name"])
    is_agent = bool(exp.get("is_agent", False))
    is_control = bool(exp.get("is_control", False))
    apply_distillation = is_agent and not is_control

    # Temperature: distilled gets consensus value if eligible, else baseline
    temperature = exp["baseline_temp"]
    if apply_distillation and consensus_temp is not None:
        temperature = consensus_temp

    # Tools: drop removed, append added
    tools: list[str] | None = list(exp.get("baseline_tools", [])) or None
    if apply_distillation and tools is not None:
        tools = [t for t in tools if t not in remove_tools]
        for t in add_tools:
            if t not in tools:
                tools.append(t)

    # Build human-readable change log
    changes: list[str] = []
    if apply_distillation:
        if consensus_temp is not None and consensus_temp != exp["baseline_temp"]:
            changes.append(f"temp {exp['baseline_temp']}→{consensus_temp}")
        baseline_tool_set = set(exp.get("baseline_tools", []))
        removed_here = baseline_tool_set & remove_tools
        if removed_here:
            changes.append(f"removed {sorted(removed_here)}")
        added_here = add_tools - baseline_tool_set
        if added_here:
            changes.append(f"added {sorted(added_here)}")
        if consensus_max_turns is not None:
            changes.append(
                f"max_turns→{consensus_max_turns} (via OPENJARVIS_CONFIG; set by run_evals)"
            )
        if routing:
            for qc, model in sorted(routing.items()):
                changes.append(f"route[{qc}]→{model}")
        if has_prompt_overrides:
            changes.append("system_prompt overrides (via $OPENJARVIS_HOME/agents/*)")
        if has_few_shot:
            changes.append("few_shot exemplars (via $OPENJARVIS_HOME/agents/*)")
        if has_tool_desc:
            changes.append("tool descriptions (via $OPENJARVIS_HOME/tools/descriptions.toml)")
    header = f"DISTILLED: {exp['name']} × {app['hf_name']}"
    bullets = changes if changes else ["CONTROL (no consensus edits applied)"]
    comment_lines = [header] + [f"  - {c}" for c in bullets]

    out_path = (
        REPO_ROOT
        / paths["distilled_configs_dir"]
        / f"{exp['name']}-{app['slug']}-distilled.toml"
    )
    output_dir = output_dir_override or (
        f"{paths['distilled_results_dir']}/{app['slug']}/{exp['name']}/"
    )
    meta_name = meta_name_override or f"{exp['name']}-{app['slug']}-distilled"
    max_samples = max_samples_override if max_samples_override is not None else (
        exp.get("max_samples") or None
    )
    content = render_config(
        comment=comment_lines,
        meta_name=meta_name,
        description=f"Distilled {exp['name']} on {app['hf_name']}",
        temperature=temperature,
        max_tokens=int(exp["max_tokens"]),
        judge_model=exp["judge_model"],
        judge_engine=exp.get("judge_engine", "cloud"),
        output_dir=output_dir,
        model_name=app["hf_name"],
        model_engine=app["engine"],
        num_gpus=int(app["num_gpus"]),
        benchmark_name=bench_name,
        backend=exp["backend"],
        agent=exp.get("agent"),
        tools=tools,
        max_samples=max_samples,
        extra_benchmark=exp.get("extra_benchmark_fields"),
        seed=seed,
        max_turns=consensus_max_turns if apply_distillation else None,
        overrides=embed_overrides if apply_distillation else None,
    )
    return out_path, content, changes


# ── Subsample gate ───────────────────────────────────────────────────────────


from dataclasses import dataclass, field  # noqa: E402
import os  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402


@dataclass
class GateCandidate:
    """One consensus edit to test in isolation against the cell's baseline."""

    id: str
    kind: str
    description: str
    consensus_temp: float | None = None
    consensus_max_turns: int | None = None
    remove_tools: set[str] = field(default_factory=set)
    add_tools: set[str] = field(default_factory=set)
    routing: dict[str, str] = field(default_factory=dict)
    embed_overrides: dict = field(default_factory=dict)


@dataclass
class GateEditResult:
    candidate: GateCandidate
    acc: float
    delta: float
    kept: bool
    reason: str
    elapsed_seconds: float


@dataclass
class GateCellResult:
    cell_label: str
    app_slug: str
    exp_name: str
    baseline_acc: float
    edit_results: list[GateEditResult]


def enumerate_candidates(
    consensus: dict, app: dict, exp: dict
) -> list[GateCandidate]:
    """List every consensus edit that would actually mutate this cell."""
    out: list[GateCandidate] = []
    baseline_temp = float(exp.get("baseline_temp", 0.0))
    baseline_tools = set(exp.get("baseline_tools", []))
    agent = exp.get("agent")

    temp = extract_temperature(consensus)
    if temp is not None and temp != baseline_temp:
        out.append(
            GateCandidate(
                id="temperature",
                kind="temperature",
                description=f"temperature {baseline_temp} → {temp}",
                consensus_temp=temp,
            )
        )
    mt = extract_max_turns(consensus)
    if mt is not None:
        out.append(
            GateCandidate(
                id="max_turns",
                kind="max_turns",
                description=f"max_turns → {mt}",
                consensus_max_turns=mt,
            )
        )
    for tool in sorted(extract_remove_tools(consensus)):
        if tool in baseline_tools:
            out.append(
                GateCandidate(
                    id=f"remove_tool:{tool}",
                    kind="remove_tool",
                    description=f"remove tool '{tool}'",
                    remove_tools={tool},
                )
            )
    for tool in sorted(extract_add_tools(consensus)):
        if tool not in baseline_tools:
            out.append(
                GateCandidate(
                    id=f"add_tool:{tool}",
                    kind="add_tool",
                    description=f"add tool '{tool}'",
                    add_tools={tool},
                )
            )
    sp = extract_system_prompts(consensus)
    if agent and agent in sp:
        out.append(
            GateCandidate(
                id=f"system_prompt:{agent}",
                kind="system_prompt",
                description=f"system_prompt[{agent}] (len={len(sp[agent])})",
                embed_overrides={"system_prompt": {agent: sp[agent]}},
            )
        )
    fs = extract_few_shot_exemplars(consensus)
    if agent and agent in fs:
        out.append(
            GateCandidate(
                id=f"few_shot:{agent}",
                kind="few_shot",
                description=f"few_shot[{agent}] ({len(fs[agent])} exemplars)",
                embed_overrides={"few_shot": {agent: fs[agent]}},
            )
        )
    td = extract_tool_descriptions(consensus)
    for tool, desc in sorted(td.items()):
        if tool in baseline_tools:
            out.append(
                GateCandidate(
                    id=f"tool_desc:{tool}",
                    kind="tool_desc",
                    description=f"tool_desc[{tool}]",
                    embed_overrides={"tool_descriptions": {tool: desc}},
                )
            )
    return out


def _run_subsample_eval(
    *,
    app: dict,
    exp: dict,
    paths: dict,
    candidate: GateCandidate | None,
    k_subsample: int,
    seed: int,
    runner_cfg: dict,
    work_dir: Path,
    label: str,
) -> tuple[float, int, int, float]:
    """Render a TOML applying just `candidate` (or none for baseline) and run
    a k_subsample eval. Returns (accuracy, scored, total, elapsed_seconds).
    """
    cand = candidate or GateCandidate(id="baseline", kind="baseline", description="baseline")
    out_dir = work_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    toml_path = work_dir / "config.toml"

    # Force apply_distillation=True path by passing exp as-is; if the cell is a
    # control, we skip gating entirely so this branch never runs for controls.
    _, content, _ = make_distilled_config(
        app=app,
        exp=exp,
        paths=paths,
        consensus_temp=cand.consensus_temp,
        consensus_max_turns=cand.consensus_max_turns,
        remove_tools=cand.remove_tools,
        add_tools=cand.add_tools,
        routing=cand.routing or None,
        has_prompt_overrides=bool(cand.embed_overrides.get("system_prompt")),
        has_few_shot=bool(cand.embed_overrides.get("few_shot")),
        has_tool_desc=bool(cand.embed_overrides.get("tool_descriptions")),
        embed_overrides=cand.embed_overrides or None,
        max_samples_override=k_subsample,
        output_dir_override=str(out_dir),
        meta_name_override=f"gate-{exp['name']}-{app['slug']}-{cand.id}",
        seed=seed,
    )
    toml_path.write_text(content, encoding="utf-8")

    # Per-cell OPENJARVIS_CONFIG override (same logic as _eval_runner.run_row).
    env = os.environ.copy()
    oj_dir = (runner_cfg.get("oj_config_dir") or "").strip()
    template = (runner_cfg.get("distilled_oj_template") or "").strip()
    if oj_dir and template:
        oj_path = Path(oj_dir) / template.format(size=app["size"])
        if oj_path.exists():
            env["OPENJARVIS_CONFIG"] = str(oj_path)

    # Materialize the temp $OPENJARVIS_HOME from [[benchmarks]].overrides so
    # the runtime loaders see this candidate's edits in isolation.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _overrides import prepare_override_home  # noqa: E402

    override_home = prepare_override_home(toml_path)
    if override_home is not None:
        env["OPENJARVIS_HOME"] = str(override_home)

    python_bin = runner_cfg.get("python_bin", ".venv/bin/python")
    if not Path(python_bin).exists():
        python_bin = shutil.which("python") or sys.executable
    evals_module = runner_cfg.get("evals_module", "openjarvis.evals")
    cmd = [python_bin, "-m", evals_module, "run", "-c", str(toml_path)]
    print(f"[gate]   {label}: running k={k_subsample} subsample...")
    t0 = time.time()
    try:
        try:
            proc = subprocess.run(
                cmd,
                env=env,
                cwd=str(REPO_ROOT),
                capture_output=True,
                text=True,
                timeout=7200,
            )
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            print(
                f"[gate]   {label}: TIMEOUT after {elapsed:.0f}s",
                file=sys.stderr,
            )
            return 0.0, 0, 0, elapsed
    finally:
        if override_home is not None:
            shutil.rmtree(override_home, ignore_errors=True)
    elapsed = time.time() - t0

    sums = list(out_dir.rglob("*.summary.json"))
    if proc.returncode != 0 or not sums:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        print(
            f"[gate]   {label}: FAILED rc={proc.returncode} ({elapsed:.0f}s) — {tail}",
            file=sys.stderr,
        )
        return 0.0, 0, 0, elapsed
    summary = json.loads(sums[0].read_text())
    acc = float(summary.get("accuracy", 0.0))
    scored = int(summary.get("scored_samples", 0))
    total = int(summary.get("total_samples", 0))
    return acc, scored, total, elapsed


def gate_cell(
    *,
    app: dict,
    exp: dict,
    paths: dict,
    consensus: dict,
    k_subsample: int,
    tolerance: float,
    seed: int,
    runner_cfg: dict,
    gate_root: Path,
) -> GateCellResult:
    """Run the subsample gate for one (app, exp) cell."""
    cell_label = f"{exp['name']}-{app['slug']}"
    cell_root = gate_root / cell_label
    cell_root.mkdir(parents=True, exist_ok=True)

    print(f"[gate] {cell_label}: enumerating candidates...")
    candidates = enumerate_candidates(consensus, app, exp)
    if not candidates:
        print(f"[gate] {cell_label}: no applicable candidate edits, skipping.")
        return GateCellResult(
            cell_label=cell_label,
            app_slug=app["slug"],
            exp_name=exp["name"],
            baseline_acc=0.0,
            edit_results=[],
        )
    print(f"[gate] {cell_label}: {len(candidates)} candidate edit(s) to test")
    for c in candidates:
        print(f"[gate]   - {c.id}: {c.description}")

    baseline_acc, bl_scored, bl_total, bl_elapsed = _run_subsample_eval(
        app=app,
        exp=exp,
        paths=paths,
        candidate=None,
        k_subsample=k_subsample,
        seed=seed,
        runner_cfg=runner_cfg,
        work_dir=cell_root / "_baseline",
        label="baseline",
    )
    print(
        f"[gate] {cell_label}: baseline acc={baseline_acc:.4f} "
        f"({bl_scored}/{bl_total} scored, {bl_elapsed:.0f}s)"
    )

    edit_results: list[GateEditResult] = []
    for cand in candidates:
        acc, scored, total, elapsed = _run_subsample_eval(
            app=app,
            exp=exp,
            paths=paths,
            candidate=cand,
            k_subsample=k_subsample,
            seed=seed,
            runner_cfg=runner_cfg,
            work_dir=cell_root / cand.id.replace(":", "_").replace("/", "_"),
            label=cand.id,
        )
        delta = acc - baseline_acc
        kept = delta >= -tolerance
        if scored == 0 and total == 0:
            kept = False
            reason = f"eval failed (no summary); rejecting to be safe"
        elif kept:
            reason = f"Δ={delta:+.4f} ≥ -{tolerance}"
        else:
            reason = f"Δ={delta:+.4f} < -{tolerance}"
        edit_results.append(
            GateEditResult(
                candidate=cand,
                acc=acc,
                delta=delta,
                kept=kept,
                reason=reason,
                elapsed_seconds=elapsed,
            )
        )
        verdict = "KEEP" if kept else "DROP"
        print(
            f"[gate] {cell_label}: {cand.id:30} acc={acc:.4f} Δ={delta:+.4f} "
            f"({scored}/{total}, {elapsed:.0f}s) → {verdict}"
        )

    return GateCellResult(
        cell_label=cell_label,
        app_slug=app["slug"],
        exp_name=exp["name"],
        baseline_acc=baseline_acc,
        edit_results=edit_results,
    )


def build_per_cell_consensus(
    base_consensus: dict, kept_edit_ids: set[str]
) -> dict:
    """Filter `base_consensus` down to only the edits whose ids are in
    `kept_edit_ids`. Edit ids match enumerate_candidates' ids."""
    out: dict = {
        "scalar_edits": [],
        "remove_tools": [],
        "add_tools": [],
        "deferred_to_m3": {
            "patch_system_prompt": [],
            "replace_system_prompt": [],
            "edit_few_shot_exemplars": [],
            "edit_tool_description": [],
        },
        "llm_selected": {
            "patch_system_prompt": [],
            "replace_system_prompt": [],
            "edit_few_shot_exemplars": [],
            "edit_tool_description": [],
        },
        "llm_synthesized": {
            "patch_system_prompt": [],
            "replace_system_prompt": [],
            "edit_few_shot_exemplars": [],
            "edit_tool_description": [],
        },
    }

    keep_temperature = "temperature" in kept_edit_ids
    keep_max_turns = "max_turns" in kept_edit_ids

    for e in base_consensus.get("scalar_edits", []):
        op = e.get("op", "")
        target = e.get("target", "")
        if target.endswith(".temperature") and keep_temperature:
            out["scalar_edits"].append(e)
        elif target.endswith(".max_turns") and keep_max_turns:
            out["scalar_edits"].append(e)
        # Other scalar ops (routing) — pass through unchanged; not gated yet.
        elif op == "set_model_for_query_class":
            out["scalar_edits"].append(e)

    for t in base_consensus.get("remove_tools", []):
        if f"remove_tool:{t['tool_name']}" in kept_edit_ids:
            out["remove_tools"].append(t)
    for t in base_consensus.get("add_tools", []):
        if f"add_tool:{t['tool_name']}" in kept_edit_ids:
            out["add_tools"].append(t)

    # Deferred-text: keep only if its agent/tool id was kept.
    src_synth = base_consensus.get("llm_synthesized") or {}
    src_llm = base_consensus.get("llm_selected") or {}
    src_def = base_consensus.get("deferred_to_m3") or {}
    # Source priority matches _items_for_op: synthesized > selected > deferred.
    for op, dst_key in [
        ("replace_system_prompt", "system_prompt"),
        ("edit_few_shot_exemplars", "few_shot"),
        ("edit_tool_description", "tool_desc"),
    ]:
        items = src_synth.get(op) or src_llm.get(op) or src_def.get(op) or []
        # Track which source we read from so we can mirror it back into the
        # right key on `out` (preserving _items_for_op's priority).
        is_synth = bool(src_synth.get(op))
        is_llm = (not is_synth) and bool(src_llm.get(op))
        for item in items:
            target = item.get("target", "")
            if op == "edit_tool_description":
                name = _tool_name_from_target(target)
                gate_id = f"tool_desc:{name}"
            else:
                name = _agent_name_from_target(target)
                gate_id = f"{dst_key}:{name}"
            if gate_id in kept_edit_ids:
                out["deferred_to_m3"][op].append(item)
                if is_synth:
                    out["llm_synthesized"][op].append(item)
                elif is_llm:
                    out["llm_selected"][op].append(item)

    # Patch system prompt edits aren't enumerated yet — preserve them as-is so
    # step 5 still sees them. (M2 currently uses replace_system_prompt mostly.)
    for op in ("patch_system_prompt",):
        for item in (
            src_synth.get(op) or src_llm.get(op) or src_def.get(op) or []
        ):
            out["deferred_to_m3"][op].append(item)
            out["llm_selected"][op].append(item)

    return out


def write_gate_report(
    report_path: Path,
    *,
    cell_results: list[GateCellResult],
    k_subsample: int,
    tolerance: float,
    seed: int,
) -> None:
    rows: list[dict] = []
    for cell in cell_results:
        for r in cell.edit_results:
            rows.append(
                {
                    "cell": cell.cell_label,
                    "app": cell.app_slug,
                    "exp": cell.exp_name,
                    "edit_id": r.candidate.id,
                    "edit_kind": r.candidate.kind,
                    "edit_description": r.candidate.description,
                    "baseline_acc": cell.baseline_acc,
                    "edit_acc": r.acc,
                    "delta": r.delta,
                    "kept": r.kept,
                    "reason": r.reason,
                    "elapsed_seconds": r.elapsed_seconds,
                }
            )
    doc = {
        "k_subsample": k_subsample,
        "tolerance": tolerance,
        "seed": seed,
        "cells": [
            {
                "cell": c.cell_label,
                "baseline_acc": c.baseline_acc,
                "n_candidates": len(c.edit_results),
                "n_kept": sum(1 for r in c.edit_results if r.kept),
                "n_rejected": sum(1 for r in c.edit_results if not r.kept),
            }
            for c in cell_results
        ],
        "edits": rows,
    }
    report_path.write_text(json.dumps(doc, indent=2))


# ── Entry point ──────────────────────────────────────────────────────────────


def write_deferred_edits_to_home(
    home: Path,
    *,
    system_prompts: dict[str, str],
    few_shot: dict[str, list],
    tool_descriptions: dict[str, str],
    dry_run: bool,
) -> list[str]:
    """Write deferred-text edits to $OPENJARVIS_HOME so the eval runtime
    picks them up via the agent/tool override hooks. Returns a list of paths
    written (or that would be written, for dry-run)."""
    written: list[str] = []
    agents_dir = home / "agents"
    tools_dir = home / "tools"

    for agent, content in system_prompts.items():
        path = agents_dir / agent / "system_prompt.md"
        written.append(str(path))
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

    for agent, exemplars in few_shot.items():
        path = agents_dir / agent / "few_shot.json"
        written.append(str(path))
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(exemplars, indent=2), encoding="utf-8")

    if tool_descriptions:
        path = tools_dir / "descriptions.toml"
        written.append(str(path))
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            lines = ["# Tool description overrides written by step 5"]
            for tool, desc in sorted(tool_descriptions.items()):
                lines.append("")
                lines.append(f"[{tool}]")
                escaped = desc.replace('"""', '\\"\\"\\"')
                lines.append(f'description = """{escaped}"""')
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return written


def _print_consensus_summary(consensus: dict, label: str) -> None:
    print(f"{label}:")
    print(f"  temperature → {extract_temperature(consensus)}")
    print(f"  max_turns   → {extract_max_turns(consensus)}")
    print(f"  remove_tools → {sorted(extract_remove_tools(consensus)) or '—'}")
    print(f"  add_tools    → {sorted(extract_add_tools(consensus)) or '—'}")
    print(f"  routing      → {extract_query_class_routing(consensus) or '—'}")
    print(f"  prompt overrides : {sorted(extract_system_prompts(consensus)) or '—'}")
    print(f"  few-shot agents  : {sorted(extract_few_shot_exemplars(consensus)) or '—'}")
    print(f"  tool desc edits  : {sorted(extract_tool_descriptions(consensus)) or '—'}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    p.add_argument("--consensus", type=Path, default=DEFAULT_CONSENSUS)
    p.add_argument(
        "--openjarvis-home",
        type=Path,
        default=None,
        help=(
            "If set, write deferred edits (system prompts, few-shot, tool "
            "descriptions) into this directory so the eval runtime picks "
            "them up via $OPENJARVIS_HOME/agents/* and "
            "$OPENJARVIS_HOME/tools/descriptions.toml. With --gate this is "
            "skipped per-cell — only edits that pass the gate are embedded "
            "in each cell's distilled TOML."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching disk.",
    )
    p.add_argument(
        "--gate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Run a per-cell subsample gate: for each cell, eval baseline + "
            "each consensus edit in isolation, drop edits where Δ < "
            "-tolerance. Default on; pass --no-gate to skip."
        ),
    )
    p.add_argument(
        "--k-subsample",
        type=int,
        default=10,
        help="Samples per gate run (baseline + one per candidate edit).",
    )
    p.add_argument(
        "--tolerance",
        type=float,
        default=0.0,
        help="Allowed regression in accuracy: keep edit if Δ ≥ -tolerance.",
    )
    p.add_argument(
        "--gate-seed",
        type=int,
        default=42,
        help="Deterministic subsample seed (same for baseline and each edit).",
    )
    p.add_argument(
        "--gate-work-dir",
        type=Path,
        default=None,
        help=(
            "Where to write per-cell gate work dirs and temp evals. Default "
            "is a new tempfile.mkdtemp."
        ),
    )
    p.add_argument(
        "--gate-report",
        type=Path,
        default=None,
        help=(
            "Where to write gate_report.json. Default: alongside "
            "consensus_edits.json (same dir, gate_report.json)."
        ),
    )
    p.add_argument(
        "--apps",
        default="all",
        help="Comma-separated app sizes/slugs to write+gate, or 'all'.",
    )
    p.add_argument(
        "--experiments",
        default="all",
        help="Comma-separated experiment names to write+gate, or 'all'.",
    )
    args = p.parse_args(argv)

    def _parse_filter(s: str) -> set[str] | None:
        if not s or s.lower() == "all":
            return None
        return {p.strip() for p in s.split(",") if p.strip()}

    app_filter = _parse_filter(args.apps)
    exp_filter = _parse_filter(args.experiments)

    if not args.matrix.exists():
        print(f"ERROR: matrix file not found: {args.matrix}", file=sys.stderr)
        return 1
    if not args.consensus.exists():
        print(f"ERROR: consensus file not found: {args.consensus}", file=sys.stderr)
        print("       Run 4_gather_consensus_edits.py first.", file=sys.stderr)
        return 1

    matrix = tomllib.loads(args.matrix.read_text())
    consensus_doc = json.loads(args.consensus.read_text())
    base_consensus = consensus_doc.get("consensus", consensus_doc)
    runner_cfg = matrix.get("runner", {})

    paths = matrix["paths"]
    apps = [
        a for a in matrix["applications"]
        if app_filter is None
        or a["size"] in app_filter
        or a["slug"] in app_filter
    ]
    exps = [
        e for e in matrix["experiments"]
        if exp_filter is None or e["name"] in exp_filter
    ]
    if not apps or not exps:
        print(
            f"ERROR: empty plan after filters apps={args.apps} experiments={args.experiments}",
            file=sys.stderr,
        )
        return 1

    _print_consensus_summary(base_consensus, "Consensus edits (pre-gate)")
    print()

    # ── Run the gate (or skip) ───────────────────────────────────────────────
    cell_consensus: dict[tuple[str, str], dict] = {}
    cell_results: list[GateCellResult] = []
    if args.gate and not args.dry_run:
        gate_root = args.gate_work_dir or Path(
            tempfile.mkdtemp(prefix="oj-gate-")
        )
        gate_root.mkdir(parents=True, exist_ok=True)
        print(f"[gate] work dir: {gate_root}")
        print(
            f"[gate] k_subsample={args.k_subsample} tolerance={args.tolerance} "
            f"seed={args.gate_seed}"
        )
        for app in apps:
            for exp in exps:
                if not bool(exp.get("is_agent", False)) or bool(
                    exp.get("is_control", False)
                ):
                    continue
                cell_res = gate_cell(
                    app=app,
                    exp=exp,
                    paths=paths,
                    consensus=base_consensus,
                    k_subsample=args.k_subsample,
                    tolerance=args.tolerance,
                    seed=args.gate_seed,
                    runner_cfg=runner_cfg,
                    gate_root=gate_root,
                )
                cell_results.append(cell_res)
                kept_ids = {r.candidate.id for r in cell_res.edit_results if r.kept}
                cell_consensus[(app["slug"], exp["name"])] = (
                    build_per_cell_consensus(base_consensus, kept_ids)
                )

        report_path = args.gate_report or args.consensus.parent / "gate_report.json"
        write_gate_report(
            report_path,
            cell_results=cell_results,
            k_subsample=args.k_subsample,
            tolerance=args.tolerance,
            seed=args.gate_seed,
        )
        print(f"\n[gate] report → {report_path}")
    elif args.gate and args.dry_run:
        print("[gate] --dry-run set; skipping gate eval (no temp work).")

    # ── Render distilled configs (per cell, using gated or raw consensus) ────
    out_dir = REPO_ROOT / paths["distilled_configs_dir"]
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    n_written = 0
    print()
    print(f"{'experiment':22} {'application':12} {'changes':80}")
    print("-" * 120)
    for app in apps:
        for exp in exps:
            cell_key = (app["slug"], exp["name"])
            cons = cell_consensus.get(cell_key, base_consensus)

            cell_temp = extract_temperature(cons)
            cell_max_turns = extract_max_turns(cons)
            cell_remove = extract_remove_tools(cons)
            cell_add = extract_add_tools(cons)
            cell_routing = extract_query_class_routing(cons)
            cell_sp = extract_system_prompts(cons)
            cell_fs = extract_few_shot_exemplars(cons)
            cell_td = extract_tool_descriptions(cons)

            agent = exp.get("agent")
            embed: dict = {}
            if agent and agent in cell_sp:
                embed.setdefault("system_prompt", {})[agent] = cell_sp[agent]
            if agent and agent in cell_fs:
                embed.setdefault("few_shot", {})[agent] = cell_fs[agent]
            baseline_tool_set = set(exp.get("baseline_tools", []))
            relevant_td = {
                tool: desc
                for tool, desc in cell_td.items()
                if tool in baseline_tool_set
            }
            if relevant_td:
                embed["tool_descriptions"] = relevant_td

            out_path, content, changes = make_distilled_config(
                app=app,
                exp=exp,
                paths=paths,
                consensus_temp=cell_temp,
                consensus_max_turns=cell_max_turns,
                remove_tools=cell_remove,
                add_tools=cell_add,
                routing=cell_routing,
                has_prompt_overrides=bool(embed.get("system_prompt")),
                has_few_shot=bool(embed.get("few_shot")),
                has_tool_desc=bool(embed.get("tool_descriptions")),
                embed_overrides=embed or None,
            )
            if not args.dry_run:
                out_path.write_text(content)
                n_written += 1
            change_str = "; ".join(changes) if changes else "(control)"
            print(f"{exp['name']:22} {app['slug']:12} {change_str:80}")

    print()
    print(f"Wrote {n_written} configs → {out_dir}/")

    # Legacy --openjarvis-home: write the *raw* (un-gated) deferred edits to a
    # global home. Only used when --no-gate or no per-cell embedding was done.
    raw_sp = extract_system_prompts(base_consensus)
    raw_fs = extract_few_shot_exemplars(base_consensus)
    raw_td = extract_tool_descriptions(base_consensus)
    if args.openjarvis_home and (raw_sp or raw_fs or raw_td) and not args.gate:
        print()
        print(f"Deferred edits → {args.openjarvis_home}/")
        written = write_deferred_edits_to_home(
            args.openjarvis_home,
            system_prompts=raw_sp,
            few_shot=raw_fs,
            tool_descriptions=raw_td,
            dry_run=args.dry_run,
        )
        for path in written:
            print(f"  {path}")
    elif args.gate:
        print()
        print(
            "NOTE: deferred edits embedded per-cell in distilled TOMLs; "
            "the runtime picks them up via [benchmarks.overrides.*]."
        )
    elif (raw_sp or raw_fs or raw_td) and not args.openjarvis_home:
        print()
        print(
            "NOTE: skipped deferred edits (system prompts / few-shot / tool "
            "descriptions) — pass --openjarvis-home DIR to write them."
        )

    if args.dry_run:
        print("(dry-run: no files written)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
