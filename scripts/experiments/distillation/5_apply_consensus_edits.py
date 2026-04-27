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


def extract_system_prompts(consensus: dict) -> dict[str, str]:
    """{agent_name: new_prompt_content} from replace_system_prompt deferred edits."""
    deferred = consensus.get("deferred_to_m3", {})
    items = deferred.get("replace_system_prompt", [])
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
    deferred = consensus.get("deferred_to_m3", {})
    items = deferred.get("edit_few_shot_exemplars", [])
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
    deferred = consensus.get("deferred_to_m3", {})
    items = deferred.get("edit_tool_description", [])
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
    lines.append("")
    return "\n".join(lines)


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
    output_dir = f"{paths['distilled_results_dir']}/{app['slug']}/{exp['name']}/"
    content = render_config(
        comment=comment_lines,
        meta_name=f"{exp['name']}-{app['slug']}-distilled",
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
        max_samples=exp.get("max_samples") or None,
        extra_benchmark=exp.get("extra_benchmark_fields"),
    )
    return out_path, content, changes


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
            "$OPENJARVIS_HOME/tools/descriptions.toml."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching disk.",
    )
    args = p.parse_args(argv)

    if not args.matrix.exists():
        print(f"ERROR: matrix file not found: {args.matrix}", file=sys.stderr)
        return 1
    if not args.consensus.exists():
        print(f"ERROR: consensus file not found: {args.consensus}", file=sys.stderr)
        print("       Run 4_gather_consensus_edits.py first.", file=sys.stderr)
        return 1

    matrix = tomllib.loads(args.matrix.read_text())
    consensus_doc = json.loads(args.consensus.read_text())
    consensus = consensus_doc.get("consensus", consensus_doc)

    paths = matrix["paths"]
    apps = matrix["applications"]
    exps = matrix["experiments"]

    consensus_temp = extract_temperature(consensus)
    consensus_max_turns = extract_max_turns(consensus)
    remove_tools = extract_remove_tools(consensus)
    add_tools = extract_add_tools(consensus)
    routing = extract_query_class_routing(consensus)
    system_prompts = extract_system_prompts(consensus)
    few_shot = extract_few_shot_exemplars(consensus)
    tool_descs = extract_tool_descriptions(consensus)

    print("Consensus edits being applied:")
    print(f"  temperature → {consensus_temp}")
    print(f"  max_turns   → {consensus_max_turns}")
    print(f"  remove_tools → {sorted(remove_tools) or '—'}")
    print(f"  add_tools    → {sorted(add_tools) or '—'}")
    print(f"  routing      → {routing or '—'}")
    print(f"  prompt overrides : {sorted(system_prompts) or '—'}")
    print(f"  few-shot agents  : {sorted(few_shot) or '—'}")
    print(f"  tool desc edits  : {sorted(tool_descs) or '—'}")
    print()

    out_dir = REPO_ROOT / paths["distilled_configs_dir"]
    if not args.dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    n_written = 0
    print(f"{'experiment':22} {'application':12} {'changes':80}")
    print("-" * 120)
    for app in apps:
        for exp in exps:
            out_path, content, changes = make_distilled_config(
                app=app,
                exp=exp,
                paths=paths,
                consensus_temp=consensus_temp,
                consensus_max_turns=consensus_max_turns,
                remove_tools=remove_tools,
                add_tools=add_tools,
                routing=routing,
                has_prompt_overrides=bool(system_prompts),
                has_few_shot=bool(few_shot),
                has_tool_desc=bool(tool_descs),
            )
            if not args.dry_run:
                out_path.write_text(content)
                n_written += 1
            change_str = "; ".join(changes) if changes else "(control)"
            print(f"{exp['name']:22} {app['slug']:12} {change_str:80}")

    print()
    print(f"Wrote {n_written} configs → {out_dir}/")

    # Write deferred edits to OPENJARVIS_HOME if requested
    if args.openjarvis_home and (system_prompts or few_shot or tool_descs):
        print()
        print(f"Deferred edits → {args.openjarvis_home}/")
        written = write_deferred_edits_to_home(
            args.openjarvis_home,
            system_prompts=system_prompts,
            few_shot=few_shot,
            tool_descriptions=tool_descs,
            dry_run=args.dry_run,
        )
        for path in written:
            print(f"  {path}")
    elif (system_prompts or few_shot or tool_descs) and not args.openjarvis_home:
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
