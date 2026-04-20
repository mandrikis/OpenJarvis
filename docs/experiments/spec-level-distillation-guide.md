# Spec-Level Distillation: Experiment Guide

## What is spec-level distillation?

A frontier "teacher" model examines the runtime behavior of a smaller "student" model inside OpenJarvis and proposes **config-level edits** — changes to agent parameters, tool selection, temperature, and routing — that improve the student without changing its weights.

"Spec-level" = we edit the **system specification** (OpenJarvis config), not the model.

---

## Milestones

### M1 — trace-only teacher ablation

A 7-axis ablation (teacher, budget, student, data-config, gate, autonomy, iterative-sessions) where a teacher reads student traces from `~/.openjarvis/traces.db` and proposes edits. In the M1 skeleton, the orchestrator used a `MagicMock` student runner and judge — no actual outcome feedback.

### M2 — apply consensus edits, measure impact

Extract consensus edits from M1's plan.json outputs, apply them as a global config, and run the 3-student × 8-benchmark matrix against reproducible-today baselines.

### M3 — per-cell hill-climb with empirical verification

Replace "aggregate consensus → apply globally" with a closed optimization loop per (student, benchmark, agent):

```
For each target cell:
    baseline_score = measure_today(baseline_config, k=k_final)
    current_config = baseline_config
    for round in 1..N:
        edit = teacher.propose_one(
            current_config,
            edit_history_with_measured_deltas,  # ← the key thing M1 lacked
            benchmark_metadata,
        )
        score_new = eval_subsample(apply(edit, current_config), k=k_subsample)
        if score_new > current_score: accept
    final_score = eval_full(current_config, k_final)
```

Every proposal is empirically tested before the next is proposed. The teacher sees measured deltas (not just traces) when picking its next edit.

---

## Key design decisions

**Auto-measure baseline per cell.** Agent-benchmark baselines from earlier setups may not reproduce in the current environment (infrastructure drift from vLLM versions, tool-call parsing, agent code). M3 measures today's baseline at `k=k_final` before starting the hill-climb, which prevents anchoring to unreproducible reference numbers.

**Subsample rounds, full final eval.** Each round runs `k_subsample` samples (cheap, noisy). The final eval runs `k_final` samples (expensive, reliable). Accept/reject decisions during hill-climb use subsample deltas; the reported delta uses final evals.

**Resumable state.** Each run writes `state.json` in the output dir after every round. A crashed or killed run resumes exactly where it stopped.

**Tolerant edit parser.** Accepts both flat (`{"op":"set_temperature","value":0.3}`) and nested (`{"op":"set_temperature","params":{"value":0.3}}`) forms that proposers may emit.

**Exploration bias in proposer prompt.** Without a nudge, LLM proposers default to repeatedly tuning numeric hyperparameters (temperature, max_turns) before exploring the tool list. The prompt explicitly lists 5 axes and encourages diversifying across them.

**Self-correcting feedback loop.** When a proposed edit regresses subsample accuracy, the loop reverts to the previous config. The rejected edit is recorded in history so the proposer won't re-propose it.

---

## Models & benchmarks

### Students (vLLM, one per H100)

| Model | HuggingFace ID | Port |
|---|---|---:|
| Qwen3.5-2B | `Qwen/Qwen3.5-2B` | 8000 |
| Qwen3.5-9B | `Qwen/Qwen3.5-9B` | 8001 |
| Qwen3.5-27B-FP8 | `Qwen/Qwen3.5-27B-FP8` | 8002 |

vLLM startup flags required for Qwen3.5 hybrid attention: `--gdn-prefill-backend triton --trust-remote-code --gpu-memory-utilization 0.90`

### Teachers (cloud API)

| Role | Model |
|---|---|
| Hill-climb proposer (default) | `claude-sonnet-4-6` |
| M1 diagnose teacher | `claude-opus-4-6`, `gpt-5.4`, `gemini-3.1-pro-preview` |
| Judge (eval scorer) | `gpt-5-mini-2025-08-07`, `claude-opus-4-5` (per-benchmark default) |

### Benchmarks

| Benchmark | CLI name | Backend | Agent |
|---|---|---|---|
| ToolCall-15 | `toolcall15` | jarvis-direct | — |
| PinchBench | `pinchbench` | jarvis-agent | `native_openhands` |
| TauBench V2 | `taubench` (split=airline,retail) | jarvis-direct | — |
| TauBench V2 Telecom | `taubench` (split=telecom) | jarvis-direct | — |
| GAIA | `gaia` | jarvis-agent | `monitor_operative` |
| DeepResearchBench | `liveresearch` / `deepresearch` | jarvis-agent | `monitor_operative` |
| LiveResearchBench (Salesforce) | `liveresearchbench` | jarvis-direct | — |
| LiveCodeBench | `livecodebench` | jarvis-direct | — |

**Distillation implication:** edits applied to `[agent]` config or the agent's tool list only affect `jarvis-agent` benchmarks. Direct benchmarks are only sensitive to `temperature` / `max_tokens`. Structure experiments accordingly.

---

## Available edit types

The M1 teacher proposes edits across 3 pillars. As of the current branch, all 8 edit types flow through to eval runs via `$OPENJARVIS_HOME` overrides:

| Pillar | Edit op | Applied via | Risk tier |
|---|---|---|---|
| intelligence | `set_model_param` | eval TOML `[defaults]` | auto |
| intelligence | `set_model_for_query_class` | `[learning.routing.policy_map]` | auto |
| agent | `set_agent_param` | `[agent]` in `$OPENJARVIS_HOME/config.toml` | auto |
| agent | `replace_system_prompt` | `$OPENJARVIS_HOME/agents/{name}/system_prompt.md` | review |
| agent | `edit_few_shot_exemplars` | `$OPENJARVIS_HOME/agents/{name}/few_shot.json` | review |
| agent | `set_agent_class` | config-level routing | review |
| tools | `add_tool_to_agent` / `remove_tool_from_agent` | eval TOML `[[benchmarks]] tools` | auto |
| tools | `edit_tool_description` | `$OPENJARVIS_HOME/tools/descriptions.toml` | auto |

The M3 hill-climb currently proposes only the subset of edits that apply via the eval TOML or the global `[agent]` config: `set_temperature`, `set_max_turns`, `set_max_tokens`, `add_tool`, `remove_tool`. Extending it to also propose prompt / description / exemplar edits is the top near-term expansion (since these are the most frequent edit types in M1 data and can move behavior more than numeric hyperparameters).

---

## How to run M3 on a new cell

```bash
source /data/home/jonsaadfalcon/jonsf/OpenJarvis/.env

# Default: auto-measure today's baseline at k=k_final before hill-climb
.venv/bin/python scripts/experiments/m3_hill_climb.py \
    --student 9b --benchmark pinchbench \
    --rounds 4 --k-subsample 15 --k-final 23
```

The script:
1. Auto-measures today's baseline at `k_final` (prevents anchoring to unreproducible reference numbers)
2. Hill-climbs `rounds` proposals, each verified at `k_subsample`
3. Runs final eval at `k_final` with the best config found
4. Writes state to `results/neurips-2026/distillation-m3/<student>-<benchmark>/state.json` (resumable)

Options:
- `--rounds N` — more rounds let the proposer find further-from-baseline optima, at the cost of more API calls and wall time
- `--k-subsample K` — per-round eval size. Higher k = better accept/reject decisions, more cost. 15 is a lower bound; 20-30 is safer if budget allows.
- `--k-final K` — final eval size; use whatever matches the benchmark's reference sample count
- `--trust-baseline` + `--baseline-score X` — skip baseline measurement, use provided value (only for resumed runs or benchmarks with known-stable baselines)
- `--fresh` — overwrite any existing state.json
- `--out-dir PATH` — alternate output root for A/B comparisons

---

## Open research questions

### 1. Infrastructure drift on agent-benchmark baselines
Historical agent-benchmark baselines from earlier setups may not reproduce in the current environment. Direct-backend benchmarks (TC15, LCB) reproduce exactly. Root causes to investigate: vLLM version differences, tool-call format parsing, agent-code drift between milestones.

### 2. Iterative M3 (hill-climb on the hill-climb)
Each M3 run finds a local optimum from the baseline starting point. Does a second M3 run starting from the M3 final config find additional improvements, or does it always noop? Max-rounds is currently arbitrary.

### 3. Unlocking the full edit surface for M3
M1 teachers most frequently propose `replace_system_prompt`, `edit_tool_description`, and `edit_few_shot_exemplars`. The plumbing to apply these at eval time landed in earlier branch commits. Extending the M3 proposer to actually emit them (not just `set_temperature` / `add_tool`) is a high-value next step.

### 4. Multi-objective hill-climbing
Current M3 optimizes accuracy only. Spec-level distillation's deployment value is `small model + edits ≈ large model raw` on cost/latency. A Pareto-front optimizer could find configs that trade a small accuracy for a large cost reduction.

### 5. Composing per-cell configs at inference time
M3 produces a different config per (student, benchmark) pair. At deployment, queries don't carry a "benchmark" label. A lightweight query classifier that dispatches to the right config at inference time would capture per-cell gains without knowing the benchmark a priori.

### 6. Proposer blind spots
The current proposer under-explores `remove_tool` relative to its M1 empirical importance. Prompt nudges help partially; a bandit-style exploration policy or reinforcement-of-successful-axes would be more principled.

### 7. Capability floors and ceilings
When the baseline score is near zero (model fundamentally cannot solve the benchmark) or near ceiling, no config edit can move accuracy. Detecting these regimes from baseline distribution and skipping hill-climb for them would save budget on cells where it can't help.

---

## Key scripts

| Path | What |
|---|---|
| `scripts/experiments/m3_hill_climb.py` | **M3 per-cell hill-climb optimizer.** |
| `scripts/experiments/m2_create_distilled_configs.py` | Generate M2 distilled eval configs from M1 consensus |
| `scripts/experiments/m2_run_distilled_evals.sh` | Orchestrator for the M2 matrix runner |
| `scripts/experiments/m2_collect_results.py` | Aggregate M2 results into comparison tables |
| `scripts/experiments/run_distillation_experiments.sh` | M1 runner (now with real student runner) |

## Results layout

| Path | What |
|---|---|
| `results/neurips-2026/agent-optimization/distillation/` | M1 session artifacts (diagnosis.md, plan.json, teacher traces) |
| `results/neurips-2026/distilled/` | M2 per-cell eval outputs |
| `results/neurips-2026/distillation-m3/` | M3 hill-climb state + final configs per cell |
| `/scratch/user/$USER/openjarvis-m1/` | Isolated M1 home (traces.db, learning sessions) |
| `/scratch/user/$USER/openjarvis-m2/` | M2 per-model configs + full-run logs |
